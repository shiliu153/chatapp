# 举报处理通知 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 运营处理完举报(ops「已处理」/「快速封禁」或 admin 改状态)时,以「系统通知」身份给举报者发一条 IM 消息,形成反馈闭环。

**Architecture:** 复用 `ban_notice` 的全套模式:client 纯 REST 封装(失败只记日志返回 False)→ Celery 任务(带重试,参数 user_id)→ 服务层 `_enqueue`(on_commit + robust)入队。触发点全部挂在各自已有的「首次标记已处理」分支上,天然幂等。前端把新类型 `report_handled` 归入现有系统通知灰条,无新视觉。

**Tech Stack:** Django 5.2 + DRF(后端,Celery/Redis)、Flutter(前端,tencent_cloud_chat_sdk)。

## Global Constraints

- 铁律:**HTTP 响应路径禁止任何第三方网络调用**;IM 副作用一律经 `chatapp/im/tasks.py` 任务,由 `transaction.on_commit(fn, robust=True)` 入队。
- 任务参数一律 **user_id**(任务内查库取 `im_user_id`);用户不存在时任务静默返回。
- 消息契约(跨栈,后端/前端一致):custom Data `{"type": "report_handled"}`,From = `system_notice`;Desc 文案逐字 = `您提交的举报已处理,感谢您对社区安全的支持。`
- 文案不披露处罚细节;运营的 `handled_note` 是内部语言,不进通知。
- 测试纪律:测 on_commit 必须 `with self.captureOnCommitCallbacks(execute=True):`;所有会触发 IM 的路径 patch `im.tasks.<任务名>.delay`;任务体用 `.run(...)` 直测并 mock `im.client.*`(腾讯 REST 一次都不能真打)。
- 回归基线:后端全量 247 全绿 → 完成后 256;前端全量 156 全绿 → 完成后 157;`flutter analyze` 零告警。
- 后端测试前置:Redis 在跑(`docker compose -f docker-compose.dev.yml up -d`,已在跑)。命令 cwd 约定:后端 = `chatapp/`;前端 = `app/`。

---

### Task 1: 发送层(im/client + im/tasks)

**Files:**
- Modify: `chatapp/im/client.py`(尾部 `send_ban_lifted` 附近)
- Modify: `chatapp/im/tasks.py`(在 `ban_lifted` 任务后)
- Test: `chatapp/im/tests.py`

**Interfaces:**
- Consumes: 现有 `send_custom_elem(from_identifier, to_identifier, data, desc)`、`SYSTEM_NOTICE_IDENTIFIER`、`_user(user_id)`、`_require(ok, what)`、`RETRY_POLICY`。
- Produces: `im.client.send_report_handled(to_identifier: str) -> bool`;`im.tasks.report_handled(reporter_id: int)`;常量 `im.client.REPORT_HANDLED_TEXT`(后续任务的测试引用它)。

- [ ] **Step 1: 写失败测试(client payload + 任务体)**

在 `chatapp/im/tests.py` 的 `ImClientTests` 类中,`test_send_ban_notice_network_error_returns_false` 之后追加:

```python
    def test_send_report_handled_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(send_report_handled("u9"))
        args = req.call_args[0]
        self.assertEqual(args[:2], ("openim", "sendmsg"))
        payload = args[2]
        self.assertEqual(payload["From_Account"], "system_notice")
        self.assertEqual(payload["To_Account"], "u9")
        content = payload["MsgBody"][0]["MsgContent"]
        self.assertEqual(json.loads(content["Data"]), {"type": "report_handled"})
        self.assertEqual(content["Desc"], "您提交的举报已处理,感谢您对社区安全的支持。")

    def test_send_report_handled_network_error_returns_false(self):
        with patch("im.client._request", side_effect=RuntimeError("boom")):
            self.assertFalse(send_report_handled("u9"))
```

同时更新文件顶部的 client import(按字母序插进 `send_match_notice` 与 `send_text` 之间):`send_report_handled`。

在 `ImSideEffectTaskTests` 类中,`test_missing_user_is_noop` 之前追加:

```python
    def test_report_handled_task(self):
        with patch("im.client.send_report_handled", return_value=True) as send:
            report_handled_task.run(self.a.id)
        send.assert_called_once_with(self.a.im_user_id)

    def test_report_handled_failure_raises_so_celery_retries(self):
        with patch("im.client.send_report_handled", return_value=False):
            with self.assertRaises(RuntimeError):
                report_handled_task.run(self.a.id)

    def test_report_handled_missing_user_is_noop(self):
        report_handled_task.run(999999)   # 不抛异常、不调用
```

并在 tasks import 处(`from .tasks import (ban_lifted, ban_notice, ...)`)加 `report_handled as report_handled_task`。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test im.tests.ImClientTests.test_send_report_handled_payload im.tests.ImSideEffectTaskTests.test_report_handled_task`
Expected: FAIL — `ImportError: cannot import name 'send_report_handled'`(import 阶段就炸)

- [ ] **Step 3: 实现 client 与 task**

`chatapp/im/client.py` 在 `BAN_LIFTED_TEXT` 常量下方加:

```python
REPORT_HANDLED_TEXT = "您提交的举报已处理,感谢您对社区安全的支持。"
```

在 `send_ban_lifted` 之后加:

```python
def send_report_handled(to_identifier: str) -> bool:
    """举报处理结果通知:以「系统通知」身份告知举报者(固定文案,不披露处罚细节)。"""
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "report_handled"}, REPORT_HANDLED_TEXT)
```

`chatapp/im/tasks.py` 在 `ban_lifted` 任务之后加:

```python
@shared_task(**RETRY_POLICY)
def report_handled(reporter_id: int) -> None:
    """举报处理完成:告知举报者(收件人是举报者,不是被举报人)。"""
    user = _user(reporter_id)
    if user is None:
        return
    _require(im_client.send_report_handled(user.im_user_id), "report_handled")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test im`
Expected: PASS(全部用例)

- [ ] **Step 5: Commit**

```bash
git add chatapp/im/client.py chatapp/im/tasks.py chatapp/im/tests.py
git commit -m "feat(chatapp): 举报处理通知的发送层(im/client + im/tasks)"
```

---

### Task 2: ops 两路径触发(服务层收口)

**Files:**
- Modify: `chatapp/moderation/services.py`(`sync_im_blacklist` 之后)
- Modify: `chatapp/ops/views.py`(`report_handle`、`report_ban`)
- Test: `chatapp/ops/tests.py`

**Interfaces:**
- Consumes: Task 1 的 `im_tasks.report_handled`;现有 `_enqueue(task, *args)`。
- Produces: `moderation.services.notify_report_handled(report) -> None`(Task 3 的 admin 也要调它)。

- [ ] **Step 1: 写失败测试(新增 3 条 + 补 mock 现有 1 条)**

在 `chatapp/ops/tests.py::ReportActionTests` 中:

① 先给现有 `test_quick_ban_heavy_bans_and_handles` 补上对新任务的 mock(新代码会在同一路径入队通知;捕获执行 on_commit 时不 mock 会把任务发进测试 broker)。把它的 `with patch(...)` 改成:

```python
        with patch("im.tasks.ban_notice.delay") as delay, \
                patch("im.tasks.report_handled.delay"):
```

② 在类末尾追加 3 条新用例:

```python
    def test_handle_notifies_reporter(self):
        with patch("im.tasks.report_handled.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(f"/ops/reports/{self.report.id}/handle", {"note": "已警告"})
        delay.assert_called_once_with(self.reporter.id)

    def test_handle_twice_notifies_once(self):
        with patch("im.tasks.report_handled.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(f"/ops/reports/{self.report.id}/handle", {"note": "一"})
                self.client.post(f"/ops/reports/{self.report.id}/handle", {"note": "二"})
        self.assertEqual(delay.call_count, 1)

    def test_quick_ban_notifies_reporter(self):
        with patch("im.tasks.ban_notice.delay") as ban_delay, \
                patch("im.tasks.report_handled.delay") as report_delay:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(f"/ops/reports/{self.report.id}/ban",
                                 {"level": "ban_heavy", "reason": "色情图片"})
        ban_delay.assert_called_once_with(self.target.id, "heavy", "色情图片")
        report_delay.assert_called_once_with(self.reporter.id)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test ops.tests.ReportActionTests`
Expected: 3 条新用例 FAIL(`delay.assert_called_once_with` 未被调用);补 mock 的那条仍 PASS。

- [ ] **Step 3: 实现服务层函数 + 两个视图调用**

`chatapp/moderation/services.py` 在 `sync_im_blacklist` 之后加:

```python
def notify_report_handled(report) -> None:
    """举报首次标记「已处理」时调用:给举报者发系统通知(经任务队列)。

    只在处理状态从 pending 变为 handled 的那一刻调用;重复处理不要调,
    否则举报者会收到多条同样的通知。
    """
    _enqueue(im_tasks.report_handled, report.reporter_id)
```

`chatapp/ops/views.py`:
- 顶部 import 行 `from moderation.services import log_ban_change` 改为 `from moderation.services import log_ban_change, notify_report_handled`。
- `report_handle` 的保存分支末尾(`report.save(...)` 之后)加一行:

```python
            notify_report_handled(report)
```

- `report_ban` 中标记分支(`report.save(...)` 之后)同样加一行:

```python
                notify_report_handled(report)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test ops`
Expected: PASS(全部用例,含既有 302/内容断言不受影响)

- [ ] **Step 5: Commit**

```bash
git add chatapp/moderation/services.py chatapp/ops/views.py chatapp/ops/tests.py
git commit -m "feat(chatapp): ops 处理举报时给举报者发通知(服务层收口 + 两路径)"
```

---

### Task 3: admin 后台触发

**Files:**
- Modify: `chatapp/moderation/admin.py`(`ReportAdmin.save_model`)
- Test: `chatapp/moderation/tests.py`(`ReportAdminTests`)

**Interfaces:**
- Consumes: Task 2 的 `moderation.services.notify_report_handled(report)`。
- Produces: 无新接口(行为扩展)。

- [ ] **Step 1: 更新测试(改造现有 1 条 + 新增 1 条)**

`chatapp/moderation/tests.py::ReportAdminTests`:

① `test_handling_report_fills_handler_and_time` 改为带 mock 与通知断言:

```python
    def test_handling_report_fills_handler_and_time(self):
        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        from .admin import ReportAdmin

        request = RequestFactory().post("/admin/")
        request.user = self.staff
        model_admin = ReportAdmin(Report, django_admin.site)
        obj = Report.objects.get(pk=self.report.pk)
        obj.status = ReportStatus.HANDLED
        obj.handled_note = "已警告"
        with patch("im.tasks.report_handled.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                model_admin.save_model(request, obj, form=None, change=True)
        obj.refresh_from_db()
        self.assertEqual(obj.handled_by, self.staff)
        self.assertIsNotNone(obj.handled_at)
        self.assertEqual(obj.handled_note, "已警告")
        delay.assert_called_once_with(self.reporter.id)
```

② 追加新用例(重复保存不再通知):

```python
    def test_resaving_handled_report_does_not_notify_again(self):
        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        from .admin import ReportAdmin

        request = RequestFactory().post("/admin/")
        request.user = self.staff
        model_admin = ReportAdmin(Report, django_admin.site)
        with patch("im.tasks.report_handled.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                first = Report.objects.get(pk=self.report.pk)
                first.status = ReportStatus.HANDLED
                model_admin.save_model(request, first, form=None, change=True)
                second = Report.objects.get(pk=self.report.pk)
                model_admin.save_model(request, second, form=None, change=True)
        self.assertEqual(delay.call_count, 1)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test moderation.tests.ReportAdminTests`
Expected: `test_handling_report_fills_handler_and_time` FAIL(delay 未调用);新用例 FAIL(call_count 0 ≠ 1)。

- [ ] **Step 3: 实现 save_model 钩子**

`chatapp/moderation/admin.py`:
- 顶部加 import:`from .services import notify_report_handled`
- `save_model` 改为:

```python
    def save_model(self, request, obj, form, change):
        first_handling = obj.status == ReportStatus.HANDLED and obj.handled_at is None
        if first_handling:
            obj.handled_at = timezone.now()
            obj.handled_by = request.user
        super().save_model(request, obj, form, change)
        if first_handling:
            notify_report_handled(obj)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test moderation`
Expected: PASS(全部用例)

- [ ] **Step 5: Commit**

```bash
git add chatapp/moderation/admin.py chatapp/moderation/tests.py
git commit -m "feat(chatapp): admin 处理举报时给举报者发通知"
```

---

### Task 4: 前端把 report_handled 归入系统通知灰条

**Files:**
- Modify: `app/lib/im/tencent_im_client.dart`(`_kindOf` 的 custom 分支,约 67-69 行)
- Test: `app/test/im/tencent_im_client_test.dart`

**Interfaces:**
- Consumes: 后端契约字符串 `report_handled`(Task 1 的 `{"type": "report_handled"}`)。
- Produces: 无新接口(kind 映射扩展;渲染/预览复用 `ChatMessageKind.banNotice` 分支,零新代码)。

- [ ] **Step 1: 写失败测试**

`app/test/im/tencent_im_client_test.dart` 在 `ban_lifted` 用例之后追加:

```dart
  test('report_handled 自定义消息 → banNotice 灰条,文案取 Desc', () {
    final message = chatMessageFromSdk(sdkMessage(
      isSelf: false,
      sender: 'system_notice',
      elem: customElem('{"type":"report_handled"}',
          desc: '您提交的举报已处理,感谢您对社区安全的支持。'),
    ));

    expect(message.kind, ChatMessageKind.banNotice);
    expect(message.text, '您提交的举报已处理,感谢您对社区安全的支持。');
    expect(message.peerId, 'system_notice');
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/im/tencent_im_client_test.dart`
Expected: 新用例 FAIL(`Actual: ChatMessageKind.other`)

- [ ] **Step 3: 实现映射**

`app/lib/im/tencent_im_client.dart` 的 `_kindOf` 中,把:

```dart
    if (type == 'ban_notice' || type == 'ban_lifted') {
      return ChatMessageKind.banNotice;
    }
```

改为:

```dart
    if (type == 'ban_notice' || type == 'ban_lifted' || type == 'report_handled') {
      return ChatMessageKind.banNotice;
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat test test/im/tencent_im_client_test.dart`
Expected: PASS(全部用例)

- [ ] **Step 5: Commit**

```bash
git add app/lib/im/tencent_im_client.dart app/test/im/tencent_im_client_test.dart
git commit -m "feat(app): 系统通知灰条支持 report_handled 类型"
```

---

### Task 5: 全量回归 + CLAUDE.md 补记

**Files:**
- Modify: `CLAUDE.md`(「腾讯云 IM 集成要点」节,封禁/解封系统消息条目附近)

**Interfaces:**
- Consumes: 前 4 个任务的全部产出。
- Produces: 无(收尾)。

- [ ] **Step 1: 后端全量测试**

Run: `cd chatapp && python manage.py test`
Expected: PASS,256 个用例(原 247 + 新增 9)

- [ ] **Step 2: 前端全量测试 + analyze**

Run: `cd app && ../flutter/bin/flutter.bat test && ../flutter/bin/flutter.bat analyze`
Expected: 157 个用例全绿;`No issues found!`

- [ ] **Step 3: CLAUDE.md 补记**

在「腾讯云 IM 集成要点」的「**封禁/解封系统消息**」条目之后新增一行:

```markdown
- **举报处理通知**:举报首次标记「已处理」时,给**举报者**发 custom `type=report_handled`(固定文案「您提交的举报已处理…」,不披露处罚细节);由 `moderation/services.py::notify_report_handled` 入队 `im/tasks.py::report_handled`,触发点 3 处(ops 已处理/快速封禁、admin save_model)全挂在各自「首次处理」分支上;App 端归入系统通知灰条。
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: CLAUDE.md 补记举报处理通知机制"
```

- [ ] **Step 5: 手测(用户在双模拟器上执行)**

1. 用现有账号在 App 里举报另一账号 → 打开 `/ops/`(账号 `13900000000`)点「已处理」→ 举报者消息页「系统通知」置顶行出现灰条「您提交的举报已处理,感谢您对社区安全的支持。」
2. 走「快速封禁」路径:举报者收到同款通知;被举报者收到原有封禁通知(两条互不影响)。
3. 对同一条举报重复点「已处理」→ 不产生第二条通知。
4. 部署形态说明:全部改动为后端任务 + 前端一行映射;**手测前重打 APK 覆盖安装**(`cd app && ../flutter/bin/flutter.bat build apk --release --dart-define=API_BASE=http://10.0.2.2:8000/api/v1`),并**确认 Celery worker 已重启**(worker 不 autoreload,新任务 `report_handled` 需要重启才能注册)。

---

## 执行记录

(执行时在此勾选/记录偏差)

- [x] Task 1
- [x] Task 2
- [x] Task 3
- [x] Task 4
- [x] Task 5

执行记录:2026-09-12 全部完成;后端 256 / 前端 157 全绿、analyze 零告警;双模拟器 + /ops/ 手测通过(「已处理」与「快速封禁」两条路径通知、重复点击不重发)。
