# 封禁系统消息 + 消息页改版 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 封禁/解封时后端以「系统通知」身份自动发 IM 消息说明原因与影响;App 底部「会话」改名「消息」,消息页改为抖音式版式(头像横滑条 + 系统通知置顶行 + 抖音风会话列表)。

**Architecture:** 复用配对灰条的既有链路——固定 IM 账号 `system_notice` 发 TIMCustomElem(`ban_notice`/`ban_lifted`),钩子挂在封禁唯一公共入口 `log_ban_change`;App 端新增 `ChatMessageKind.banNotice` 映射渲染,消息页整页重构。

**Tech Stack:** Django 5.2 + MySQL(`chatapp/`)、腾讯云 IM REST(`im/client.py`)、Flutter(`app/`,Riverpod + go_router)。

**分支:** 自 `master` 开 `ban-notice`,完成后按 finishing-a-development-branch 收尾。

## Global Constraints

- 文案一字不差(spec `docs/superpowers/specs/2026-09-11-ban-notice-message-page-design.md` 原样复制):
  - 轻度:「您的账号因「{原因}」被限制。限制期间无法使用滑卡功能,聊天、资料等其他功能不受影响。如有疑问请联系客服。」
  - 重度:「您的账号因「{原因}」已被封禁。封禁期间所有功能暂停使用,如有疑问请联系客服。」
  - 解除:「您的账号限制已解除,所有功能已恢复。请遵守社区规范。」
  - 原因空兜底:「违反社区规范」
- 跨栈契约字符串:`system_notice`(账号/peerId)、`ban_notice`、`ban_lifted`、`match_notice`
- IM 调用**永不抛异常**,失败只记日志返回 False;成功判定 `ErrorCode == 0`
- 测试纪律:后端任何触发 IM 的路径都 mock `moderation.services._dispatch_async`;Flutter 用 `pumpApp`+`FakeImClient`;`flutter analyze` 零告警
- 颜色:抖音红 `0xFFFF2C55`、浅蓝底 `0xFFE8F0FE`(官方图标)、预览灰 `0xFF8A8F98`、时间灰 `0xFF9AA0A8`、分割线 `0xFFF5F6F7`、置顶间隔条 `0xFFF7F8FA`
- 命令:后端 cwd=`chatapp/`(`python manage.py test ...`);前端 cwd=`app/`(`../flutter/bin/flutter.bat test ...`)
- 内部类名/路由(`/chat/...`)/注释里的"会话"不动,只改用户可见文案

---

### Task 1: 系统通知账号与封禁/解封消息发送函数

**Files:**
- Modify: `chatapp/im/client.py`(追加常量与函数,不改动现有函数)
- Create: `chatapp/im/management/commands/im_setup_system_account.py`
- Test: `chatapp/im/tests.py`(ImClientTests 内追加;文件末尾追加命令测试类)

**Interfaces:**
- Consumes: 现有 `_request(service, command, payload)`、`_check(result, what)`、`send_custom_elem(from, to, data, desc)`
- Produces(供 Task 2 使用):
  - `SYSTEM_NOTICE_IDENTIFIER = "system_notice"` / `SYSTEM_NOTICE_NICK = "系统通知"`
  - `send_ban_notice(to_identifier: str, level: str, reason: str) -> bool`(level 取 `"light"`/`"heavy"`)
  - `send_ban_lifted(to_identifier: str) -> bool`
  - `ensure_account(identifier: str, nickname: str = "") -> bool`
  - 管理命令 `im_setup_system_account`

- [ ] **Step 1: 写失败测试(im/tests.py)**

顶部 import 行(第 13-14 行)改为:

```python
from .client import (_request, black_list_add, black_list_delete, ensure_account,
                     import_account, kick_user, send_ban_lifted, send_ban_notice,
                     send_custom_elem, send_match_notice, send_text)
```

在 `ImClientTests` 类内(末尾)`test_import_account_network_error_returns_false` 之后追加:

```python
    def test_ensure_account_existing_is_success(self):
        with patch("im.client._request", return_value={"ErrorCode": 7015, "ErrorInfo": "exist"}):
            self.assertTrue(ensure_account("system_notice", "系统通知"))

    def test_ensure_account_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(ensure_account("system_notice", "系统通知"))
        args = req.call_args[0]
        self.assertEqual(args[0], "im_open_login_svc")
        self.assertEqual(args[1], "account_import")
        self.assertEqual(args[2]["Identifier"], "system_notice")
        self.assertEqual(args[2]["Nick"], "系统通知")

    def test_ensure_account_other_error_returns_false(self):
        with patch("im.client._request", return_value={"ErrorCode": 9999}):
            self.assertFalse(ensure_account("system_notice"))

    def test_send_ban_notice_light_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(send_ban_notice("u9", "light", "骚扰他人"))
        args = req.call_args[0]
        self.assertEqual(args[:2], ("openim", "sendmsg"))
        payload = args[2]
        self.assertEqual(payload["From_Account"], "system_notice")
        self.assertEqual(payload["To_Account"], "u9")
        content = payload["MsgBody"][0]["MsgContent"]
        self.assertEqual(json.loads(content["Data"]), {"type": "ban_notice", "level": "light"})
        self.assertIn("骚扰他人", content["Desc"])
        self.assertIn("无法使用滑卡功能", content["Desc"])

    def test_send_ban_notice_heavy_reason_fallback(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            send_ban_notice("u9", "heavy", "")
        content = req.call_args[0][2]["MsgBody"][0]["MsgContent"]
        self.assertEqual(json.loads(content["Data"]), {"type": "ban_notice", "level": "heavy"})
        self.assertIn("违反社区规范", content["Desc"])
        self.assertIn("封禁期间所有功能暂停使用", content["Desc"])

    def test_send_ban_lifted_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(send_ban_lifted("u9"))
        content = req.call_args[0][2]["MsgBody"][0]["MsgContent"]
        self.assertEqual(json.loads(content["Data"]), {"type": "ban_lifted"})
        self.assertIn("已解除", content["Desc"])

    def test_send_ban_notice_network_error_returns_false(self):
        with patch("im.client._request", side_effect=RuntimeError("boom")):
            self.assertFalse(send_ban_notice("u9", "light", "x"))
```

在文件末尾(`UserSigApiTests` 之前或之后均可,建议紧跟 `ImSendCommandTests` 后)追加:

```python
class ImSetupSystemAccountCommandTests(SimpleTestCase):
    def test_command_creates_system_account(self):
        with patch("im.management.commands.im_setup_system_account.ensure_account",
                   return_value=True) as ensure:
            call_command("im_setup_system_account")
        ensure.assert_called_once_with("system_notice", "系统通知")

    def test_command_raises_when_not_ready(self):
        with patch("im.management.commands.im_setup_system_account.ensure_account",
                   return_value=False):
            with self.assertRaises(CommandError):
                call_command("im_setup_system_account")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test im`
Expected: FAIL(`ImportError: cannot import name 'ensure_account'` / `ModuleNotFoundError` 命令不存在)

- [ ] **Step 3: 实现(im/client.py 追加)**

在 `MATCH_NOTICE_TEXT = ...` 行后追加常量;在文件末尾追加函数:

```python
SYSTEM_NOTICE_IDENTIFIER = "system_notice"
SYSTEM_NOTICE_NICK = "系统通知"

BAN_REASON_FALLBACK = "违反社区规范"
BAN_LIFTED_TEXT = "您的账号限制已解除,所有功能已恢复。请遵守社区规范。"


def _ban_notice_text(level: str, reason: str) -> str:
    reason = reason or BAN_REASON_FALLBACK
    if level == "heavy":
        return (f"您的账号因「{reason}」已被封禁。"
                "封禁期间所有功能暂停使用,如有疑问请联系客服。")
    return (f"您的账号因「{reason}」被限制。"
            "限制期间无法使用滑卡功能,聊天、资料等其他功能不受影响。如有疑问请联系客服。")


def ensure_account(identifier: str, nickname: str = "") -> bool:
    """幂等建号:已存在(ErrorCode 7015)视为成功。"""
    payload = {"Identifier": identifier, "Nick": nickname, "FaceUrl": ""}
    try:
        result = _request("im_open_login_svc", "account_import", payload)
    except Exception:
        logger.exception("IM account_import 调用失败 identifier=%s", identifier)
        return False
    if result.get("ErrorCode") == 7015:
        return True
    return _check(result, "account_import")


def send_ban_notice(to_identifier: str, level: str, reason: str) -> bool:
    """封禁说明:以「系统通知」身份发一条自定义消息(level 取 light/heavy)。"""
    data = {"type": "ban_notice", "level": level}
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier, data,
                            _ban_notice_text(level, reason))


def send_ban_lifted(to_identifier: str) -> bool:
    """解封通知:以「系统通知」身份发一条自定义消息。"""
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "ban_lifted"}, BAN_LIFTED_TEXT)
```

- [ ] **Step 4: 实现管理命令(新建 im_setup_system_account.py)**

```python
"""一次性环境步骤:创建「系统通知」IM 账号(封禁/解封消息的发送方)。

用法:
    python manage.py im_setup_system_account

可重复执行;账号已存在视为成功。
"""

from django.core.management.base import BaseCommand, CommandError

from im.client import SYSTEM_NOTICE_IDENTIFIER, SYSTEM_NOTICE_NICK, ensure_account


class Command(BaseCommand):
    help = "创建「系统通知」IM 账号(幂等)"

    def handle(self, *args, **options):
        if not ensure_account(SYSTEM_NOTICE_IDENTIFIER, SYSTEM_NOTICE_NICK):
            raise CommandError("系统账号创建失败 —— 看上面的 IM 错误日志")
        self.stdout.write(self.style.SUCCESS(
            f"系统账号就绪:{SYSTEM_NOTICE_IDENTIFIER}({SYSTEM_NOTICE_NICK})"))
```

- [ ] **Step 5: 跑测试确认通过 + 全量回归**

Run: `python manage.py test im && python manage.py test`
Expected: 全绿(im 新增 ~8 用例;全量 180 + 8 左右)

- [ ] **Step 6: Commit**

```bash
git add chatapp/im/client.py chatapp/im/tests.py chatapp/im/management/commands/im_setup_system_account.py
git commit -m "feat(im): 系统通知账号与封禁/解封消息发送函数"
```

---

### Task 2: 封禁/解封联动系统通知消息

**Files:**
- Modify: `chatapp/moderation/services.py:19-29`(log_ban_change 三个分支)+ 新增 `_send_notice_then_kick`
- Test: `chatapp/moderation/tests.py`(BanAuditServiceTests 改写 3 个用例 + 新增 1 个)
- Test: `chatapp/ops/tests.py`(3 个用例断言更新 + 1 个用例补 patch)

**Interfaces:**
- Consumes: Task 1 的 `im_client.send_ban_notice(to, level, reason)` / `im_client.send_ban_lifted(to)`
- Produces: `moderation.services._send_notice_then_kick(identifier, reason) -> None`(专供派发,先发消息后踢)

- [ ] **Step 1: 改测试为先(期望新行为,此刻会失败)**

`moderation/tests.py` 顶部第 15 行改为:

```python
from .services import _send_notice_then_kick, log_ban_change
```

`BanAuditServiceTests` 中,`test_heavy_ban_writes_log_and_kicks_offline` 的最后一个断言改为(方法名同步改为 `test_heavy_ban_dispatches_notice_then_kick`):

```python
        dispatch.assert_called_once_with(_send_notice_then_kick,
                                         self.target.im_user_id, "骚扰他人")
```

`test_light_ban_writes_log_without_kick` 方法名改为 `test_light_ban_dispatches_notice_without_kick`,内容改为:

```python
    def test_light_ban_dispatches_notice_without_kick(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            log_ban_change(self.target, ProfileStatus.COMPLETE, ProfileStatus.BANNED_LIGHT,
                           "轻度违规", self.operator)
        self.assertEqual(BanLog.objects.get(user=self.target).action, BanAction.BAN_LIGHT)
        dispatch.assert_called_once_with(im_client.send_ban_notice,
                                         self.target.im_user_id, "light", "轻度违规")
```

`test_unban_writes_unban_log` 改为(补 patch,原本没封禁动作不会派发;现在解封要派发):

```python
    def test_unban_dispatches_lifted_notice(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            log_ban_change(self.target, ProfileStatus.BANNED_HEAVY, ProfileStatus.COMPLETE,
                           "申诉通过", self.operator)
        self.assertEqual(BanLog.objects.get(user=self.target).action, BanAction.UNBAN)
        dispatch.assert_called_once_with(im_client.send_ban_lifted, self.target.im_user_id)
```

新增用例(同类内):

```python
    def test_send_notice_then_kick_sends_before_kick(self):
        calls = []
        with patch.object(im_client, "send_ban_notice",
                          side_effect=lambda *a: calls.append("send")) as send, \
             patch.object(im_client, "kick_user",
                          side_effect=lambda *a: calls.append("kick")):
            _send_notice_then_kick("u9", "骚扰他人")
        self.assertEqual(calls, ["send", "kick"])
        send.assert_called_once_with("u9", "heavy", "骚扰他人")
```

`test_non_ban_transition_writes_nothing` 改为(补 dispatch 断言):

```python
    def test_non_ban_transition_writes_nothing(self):
        with patch("moderation.services._dispatch_async") as dispatch:
            log_ban_change(self.target, ProfileStatus.INCOMPLETE, ProfileStatus.COMPLETE,
                           "", self.operator)
        self.assertFalse(BanLog.objects.exists())
        dispatch.assert_not_called()
```

`ops/tests.py` 顶部(第 8 行 `from moderation.models import ...` 之后)加:

```python
from moderation.services import _send_notice_then_kick
```

`ReportActionTests.test_quick_ban_heavy_bans_and_handles` 第 135 行断言改为:

```python
        dispatch.assert_called_once_with(_send_notice_then_kick,
                                         self.target.im_user_id, "色情图片")
```

`OpsUserBanTests.test_ban_light_records_log_without_kick` 方法名改为 `test_ban_light_dispatches_notice_no_kick`,最后断言改为:

```python
        dispatch.assert_called_once_with(im_client.send_ban_notice,
                                         self.user.im_user_id, "light", "骚扰他人")
```

`test_ban_heavy_kicks_im` 第 259 行断言改为:

```python
        dispatch.assert_called_once_with(_send_notice_then_kick,
                                         self.user.im_user_id, "严重违规")
```

`test_unban_recomputes_status_and_clears_reason` 的 unban 请求也要包 patch(现在解封会派发):

```python
    def test_unban_recomputes_status_and_clears_reason(self):
        with patch("moderation.services._dispatch_async"):
            self.client.post(f"/ops/users/{self.user.id}/ban",
                             {"action": "ban_light", "reason": "先封"})
        with patch("moderation.services._dispatch_async"):
            resp = self.client.post(f"/ops/users/{self.user.id}/ban",
                                    {"action": "unban", "reason": ""})
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.COMPLETE)   # 资料齐全+有照片 → 重算回已完善
        self.assertEqual(self.profile.ban_reason, "")
        self.assertTrue(BanLog.objects.filter(user=self.user, action=BanAction.UNBAN).exists())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test moderation.tests.BanAuditServiceTests ops.tests.OpsUserBanTests ops.tests.ReportActionTests`
Expected: FAIL(断言不匹配:`kick_user` vs `_send_notice_then_kick`;light 断言 not called 但马上会派发)

- [ ] **Step 3: 实现(moderation/services.py)**

`log_ban_change` 整体替换为:

```python
def log_ban_change(user, old_status, new_status, reason, operator) -> None:
    """admin 保存 Profile 时调用:状态跨封禁边界就写审计 + 发系统通知;重封禁顺带踢下线。"""
    if new_status == old_status:
        return
    identifier = user.im_user_id
    if new_status == ProfileStatus.BANNED_LIGHT:
        _write_log(user, BanAction.BAN_LIGHT, reason, operator)
        _dispatch_async(im_client.send_ban_notice, identifier, "light", reason or "")
    elif new_status == ProfileStatus.BANNED_HEAVY:
        _write_log(user, BanAction.BAN_HEAVY, reason, operator)
        _dispatch_async(_send_notice_then_kick, identifier, reason or "")
    elif old_status in Profile.BANNED_STATUSES:
        _write_log(user, BanAction.UNBAN, reason, operator)
        _dispatch_async(im_client.send_ban_lifted, identifier)
```

在 `_write_log` 之前新增:

```python
def _send_notice_then_kick(identifier, reason) -> None:
    """重封禁:先把封禁说明送达,再踢下线(同一线程保证顺序)。"""
    im_client.send_ban_notice(identifier, "heavy", reason)
    im_client.kick_user(identifier)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test moderation ops`
Expected: PASS(全绿)

- [ ] **Step 5: 全量回归(抓其他触发 IM 的用例)**

Run: `python manage.py test`
Expected: 全绿;且日志里**不应出现** `IM sendmsg/account_import 返回错误`(出现说明有路径漏 mock)

- [ ] **Step 6: Commit**

```bash
git add chatapp/moderation/services.py chatapp/moderation/tests.py chatapp/ops/tests.py
git commit -m "feat(moderation): 封禁/解封联动系统通知消息(先发后踢)"
```

---

### Task 3: ban_notice 消息类型映射与灰条渲染

**Files:**
- Modify: `app/lib/im/im_client.dart`(enum + 常量)
- Modify: `app/lib/im/tencent_im_client.dart:17-54`(映射)
- Modify: `app/lib/features/chat/widgets/message_bubble.dart:16-18`(灰条分支)
- Modify: `app/lib/features/chat/chats_page.dart:91-99`(`_preview` 补一个 case,保编译;Task 5 会整页重构)
- Test: `app/test/im/tencent_im_client_test.dart` / `app/test/features/chat/chat_page_test.dart`

**Interfaces:**
- Produces(供 Task 4/5 使用):`ChatMessageKind.banNotice`、`const systemNoticePeerId = 'system_notice'`
- 注意:`ChatMessageKind` 是 enum,新增成员会让所有 **exhaustive switch** 编译不过 —— 本任务内把 `tencent_im_client.dart` 与 `chats_page.dart` 的两处 switch 一并补齐

- [ ] **Step 1: 写失败测试**

`app/test/im/tencent_im_client_test.dart` 在 `'match_notice 自定义消息 → 灰条,文案取 Desc'` 测试之后追加:

```dart
  test('ban_notice 自定义消息 → banNotice,文案取 Desc', () {
    final message = chatMessageFromSdk(sdkMessage(
      isSelf: false,
      sender: 'system_notice',
      elem: customElem('{"type":"ban_notice","level":"light"}',
          desc: '您的账号因「骚扰他人」被限制。'),
    ));

    expect(message.kind, ChatMessageKind.banNotice);
    expect(message.text, '您的账号因「骚扰他人」被限制。');
    expect(message.peerId, 'system_notice');
  });

  test('ban_lifted 自定义消息 → banNotice', () {
    final message = chatMessageFromSdk(sdkMessage(
      isSelf: false,
      sender: 'system_notice',
      elem: customElem('{"type":"ban_lifted"}', desc: '您的账号限制已解除,所有功能已恢复。'),
    ));

    expect(message.kind, ChatMessageKind.banNotice);
    expect(message.text, '您的账号限制已解除,所有功能已恢复。');
  });
```

`app/test/features/chat/chat_page_test.dart` 在 `'match_notice → 居中灰条'` 测试之后追加:

```dart
  testWidgets('ban_notice → 居中灰条', (tester) async {
    fake.history = {
      'system_notice': [
        const ChatMessage(
          msgId: 's1',
          peerId: 'system_notice',
          isSelf: false,
          timestamp: 1700000000000,
          kind: ChatMessageKind.banNotice,
          text: '您的账号因「骚扰他人」被限制。',
        ),
      ],
    };
    await pumpChat(tester, peerId: 'system_notice');

    expect(find.byKey(const Key('chat.notice')), findsOneWidget);
    expect(find.text('您的账号因「骚扰他人」被限制。'), findsOneWidget);
  });
```

⚠️ `pumpChat` 现在写死了 `initialLocation: '/chat/u9'`(见 chat_page_test.dart:66)——本步骤需要先给它加一个可选参数,把 `pumpChat` 签名改为:

```dart
  Future<void> pumpChat(WidgetTester tester, {String peerId = 'u9'}) async {
```

并把 `initialLocation: '/chat/u9'` 改为 `initialLocation: '/chat/$peerId'`。

- [ ] **Step 2: 跑测试确认失败**

Run: `../flutter/bin/flutter.bat test test/im/tencent_im_client_test.dart test/features/chat/chat_page_test.dart`
Expected: FAIL(`ChatMessageKind.banNotice` 不存在,编译错)

- [ ] **Step 3: 实现**

`app/lib/im/im_client.dart`:

```dart
enum ChatMessageKind { text, matchNotice, banNotice, other }

/// 「系统通知」固定 IM 账号(与后端 im/client.py::SYSTEM_NOTICE_IDENTIFIER 是跨栈契约)。
const systemNoticePeerId = 'system_notice';
```

`app/lib/im/tencent_im_client.dart`,`chatMessageFromSdk` 的 text switch 加一行:

```dart
      ChatMessageKind.matchNotice => message.customElem?.desc ?? '',
      ChatMessageKind.banNotice => message.customElem?.desc ?? '',
      ChatMessageKind.other => '',
```

`_kindOf` 与 `_isMatchNotice` 整体替换为:

```dart
ChatMessageKind _kindOf(V2TimMessage message) {
  if (message.elemType == MessageElemType.V2TIM_ELEM_TYPE_TEXT) {
    return ChatMessageKind.text;
  }
  if (message.elemType == MessageElemType.V2TIM_ELEM_TYPE_CUSTOM) {
    final type = _customType(message.customElem?.data);
    if (type == 'match_notice') return ChatMessageKind.matchNotice;
    if (type == 'ban_notice' || type == 'ban_lifted') {
      return ChatMessageKind.banNotice;
    }
  }
  return ChatMessageKind.other;
}

String? _customType(String? data) {
  if (data == null || data.isEmpty) return null;
  try {
    final decoded = jsonDecode(data);
    return decoded is Map ? decoded['type'] as String? : null;
  } catch (_) {
    return null;
  }
}
```

`app/lib/features/chat/widgets/message_bubble.dart` 的 label switch 加分支:

```dart
        ChatMessageKind.matchNotice => message.text.isEmpty ? noticeFallback : message.text,
        ChatMessageKind.banNotice => message.text.isEmpty ? '系统通知' : message.text,
        _ => '[暂不支持的消息]',
```

`app/lib/features/chat/chats_page.dart` 的 `_preview` getter switch(第 94-98 行)加分支(仅保编译,Task 5 整页重构会保留同语义):

```dart
      ChatMessageKind.banNotice => last.text.isEmpty ? '系统通知' : last.text,
```

- [ ] **Step 4: 跑测试确认通过 + analyze**

Run: `../flutter/bin/flutter.bat test test/im/tencent_im_client_test.dart test/features/chat/chat_page_test.dart && ../flutter/bin/flutter.bat analyze`
Expected: PASS;analyze 零告警

- [ ] **Step 5: Commit**

```bash
git add app/lib/im/im_client.dart app/lib/im/tencent_im_client.dart app/lib/features/chat/widgets/message_bubble.dart app/lib/features/chat/chats_page.dart app/test/im/tencent_im_client_test.dart app/test/features/chat/chat_page_test.dart
git commit -m "feat(app): ban_notice 消息类型映射与灰条渲染"
```

---

### Task 4: 系统通知显示名与封禁页补充说明

**Files:**
- Modify: `app/lib/features/chat/match_cache.dart:33-38`(displayNameFor 特判)
- Modify: `app/lib/features/shell/banned_page.dart:27-32`(补一行)
- Test: `app/test/features/chat/match_cache_test.dart` / `app/test/features/shell/banned_page_test.dart`

**Interfaces:**
- Consumes: Task 3 的 `systemNoticePeerId`
- Produces: `displayNameFor` 对 `system_notice` 恒返回「系统通知」

- [ ] **Step 1: 写失败测试**

`app/test/features/chat/match_cache_test.dart` 的 `'显示名:缓存 > IM 名 > id;头像:缓存 > IM 头像'` 测试里追加一行断言:

```dart
    expect(displayNameFor(cache, 'system_notice'), '系统通知'); // 特判:不裸奔成 id
```

`app/test/features/shell/banned_page_test.dart` 在 `expect(find.text('原因:骚扰他人'), findsOneWidget);` 后追加:

```dart
    expect(find.text('封禁期间所有功能暂停使用'), findsOneWidget);
```

- [ ] **Step 2: 跑测试确认失败**

Run: `../flutter/bin/flutter.bat test test/features/chat/match_cache_test.dart test/features/shell/banned_page_test.dart`
Expected: FAIL(返回 'system_notice' 而非「系统通知」;封禁页无该行)

- [ ] **Step 3: 实现**

`app/lib/features/chat/match_cache.dart` 顶部加 import:

```dart
import '../../im/im_client.dart';
```

`displayNameFor` 改为:

```dart
String displayNameFor(Map<String, MatchEntry> cache, String peerId, {String? imName}) {
  if (peerId == systemNoticePeerId) return '系统通知';
  final cached = cache[peerId]?.nickname;
  if (cached != null && cached.isNotEmpty) return cached;
  if (imName != null && imName.isNotEmpty) return imName;
  return peerId;
}
```

`app/lib/features/shell/banned_page.dart`,在 `原因` block 之后、`如有疑问请联系客服` 之前插入:

```dart
                const SizedBox(height: 8),
                const Text('封禁期间所有功能暂停使用'),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `../flutter/bin/flutter.bat test test/features/chat/match_cache_test.dart test/features/shell/banned_page_test.dart`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/lib/features/chat/match_cache.dart app/lib/features/shell/banned_page.dart app/test/features/chat/match_cache_test.dart app/test/features/shell/banned_page_test.dart
git commit -m "feat(app): 系统通知显示名特判 + 封禁页补充说明"
```

---

### Task 5: 消息页抖音式改版 + 改名

**Files:**
- Modify: `app/lib/features/chat/chats_page.dart`(**整页重写**,见 Step 3)
- Modify: `app/lib/features/shell/home_shell.dart:36-44`(tab 文案 + 角标红)
- Test: `app/test/features/chat/chats_page_test.dart`(整文件替换,见 Step 1)
- Test: `app/test/features/shell/home_shell_test.dart`(两处改 + 一处加)

**Interfaces:**
- Consumes: Task 3/4 的 `systemNoticePeerId`、`ChatMessageKind.banNotice`、`displayNameFor` 特判;`conversationsProvider`、`matchCacheProvider`、`formatMessageTime`、`avatarUrlFor`
- Produces: 页面 keys —— `chats.strip`、`chats.stripItem:{peerId}`、`chats.systemNotice`、`chats.tile:{peerId}`(测试用);字体/配色按 Global Constraints

- [ ] **Step 1: 改测试为先(整文件替换 chats_page_test.dart)**

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/im/im_client.dart';

import '../../support/fake_im_client.dart';
import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

const _loggedIn = {'auth.access': 'a', 'auth.refresh': 'r', 'auth.user_id': 3};

ScriptedAdapter _adapter() => ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'POST /im/user_sig': (options) => ok({
            'user_sig': 'sig',
            'sdkappid': '1600161711',
            'im_user_id': 'u3',
            'expire': 604800,
          }),
      'GET /matches': (options) => ok([matchJson(userId: 9, nickname: '小红')]),
    });

ImConversation _conversation({int unread = 2, String text = '在吗'}) => ImConversation(
      peerId: 'u9',
      unreadCount: unread,
      lastMessage: ChatMessage(
        msgId: 'm1',
        peerId: 'u9',
        isSelf: false,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.text,
        text: text,
      ),
    );

ImConversation _systemConversation({int unread = 1}) => ImConversation(
      peerId: 'system_notice',
      unreadCount: unread,
      lastMessage: ChatMessage(
        msgId: 's1',
        peerId: 'system_notice',
        isSelf: false,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.banNotice,
        text: '您的账号因「发布违规内容」被限制。',
      ),
    );

void main() {
  testWidgets('消息页:昵称来自 matches 缓存,预览和未读都在', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation()];
    await pumpApp(tester, _adapter(), prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    expect(find.text('小红'), findsNWidgets(2)); // 横滑条 + 列表行
    expect(find.text('在吗'), findsOneWidget);
    // 列表行角标一个、底部 Tab 一个(未读总数),共两个 '2'
    expect(find.text('2'), findsNWidgets(2));
  });

  testWidgets('没有会话 → 空态,无横滑条', (tester) async {
    final fake = FakeImClient();
    await pumpApp(tester, _adapter(), prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    expect(find.text('还没有消息'), findsOneWidget);
    expect(find.byKey(const Key('chats.strip')), findsNothing);
  });

  testWidgets('IM 登录失败 → 显示原因 + 重试按钮', (tester) async {
    final fake = FakeImClient()..loginError = const ImException(6001, 'boom');
    await pumpApp(tester, _adapter(), prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    expect(find.textContaining('6001'), findsOneWidget);
    expect(find.byKey(const Key('chats.retry')), findsOneWidget);
  });

  testWidgets('系统通知:置顶在会话列表之上 + 官方标', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation(), _systemConversation()];
    await pumpApp(tester, _adapter(), prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('chats.systemNotice')), findsOneWidget);
    expect(find.text('系统通知'), findsOneWidget);
    expect(find.text('官方'), findsOneWidget);
    final systemY = tester.getTopLeft(find.byKey(const Key('chats.systemNotice'))).dy;
    final friendY = tester.getTopLeft(find.byKey(const Key('chats.tile:u9'))).dy;
    expect(systemY, lessThan(friendY));
  });

  testWidgets('点列表行 → 进聊天页', (tester) async {
    final fake = FakeImClient()
      ..conversations = [_conversation()]
      ..history = {
        'u9': [
          ChatMessage(
            msgId: 'm1',
            peerId: 'u9',
            isSelf: false,
            timestamp: DateTime.now().millisecondsSinceEpoch,
            kind: ChatMessageKind.text,
            text: '你好呀',
          ),
        ],
      };
    await pumpApp(tester, _adapter(), prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('chats.tile:u9')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('chat.input')), findsOneWidget);
    expect(find.text('你好呀'), findsOneWidget); // 历史里的那条
  });

  testWidgets('点横滑条头像 → 直达聊天页', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation()];
    await pumpApp(tester, _adapter(), prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('chats.stripItem:u9')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('chat.input')), findsOneWidget);
  });
}
```

`home_shell_test.dart` 三处修改:
1. 第 26 行 `expect(navTab('会话'), findsOneWidget);` → `expect(navTab('消息'), findsOneWidget);`
2. 测试名 `'会话 Tab 显示未读角标'` → `'消息 Tab 显示未读角标'`,并在 `expect(find.text('3'), findsWidgets);` 后追加:

```dart
    final badge = tester.widget<Badge>(find.byType(Badge));
    expect(badge.backgroundColor, const Color(0xFFFF2C55)); // 抖音红
```

- [ ] **Step 2: 跑测试确认失败**

Run: `../flutter/bin/flutter.bat test test/features/chat/chats_page_test.dart test/features/shell/home_shell_test.dart`
Expected: FAIL(navTab('消息') 找不到;`还没有消息`/keys 不存在)

- [ ] **Step 3: 实现(整页重写 chats_page.dart)**

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/format.dart';
import '../../im/im_client.dart';
import '../../im/im_manager.dart';
import '../../im/im_repository.dart';
import 'conversations_controller.dart';
import 'match_cache.dart';

class ChatsPage extends ConsumerWidget {
  const ChatsPage({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final status = ref.watch(imStatusProvider);
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            const Padding(
              padding: EdgeInsets.fromLTRB(16, 10, 16, 8),
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text('消息',
                    style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
              ),
            ),
            Expanded(
              child: switch (status) {
                ImConnecting() => const Center(child: CircularProgressIndicator()),
                ImFailed(:final message) => _FailedView(message: message),
                _ => const _ConversationList(),
              },
            ),
          ],
        ),
      ),
    );
  }
}

class _FailedView extends ConsumerWidget {
  const _FailedView({required this.message});

  final String message;

  @override
  Widget build(BuildContext context, WidgetRef ref) => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text(message),
            const SizedBox(height: 12),
            FilledButton(
              key: const Key('chats.retry'),
              onPressed: () => ref.read(imStatusProvider.notifier).retry(),
              child: const Text('重试'),
            ),
          ],
        ),
      );
}

class _ConversationList extends ConsumerWidget {
  const _ConversationList();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final conversations = ref.watch(conversationsProvider);
    final cache = ref.watch(matchCacheProvider).value ?? const <String, MatchEntry>{};
    return conversations.when(
      loading: () => const Center(child: CircularProgressIndicator()),
      error: (error, _) => Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('$error'),
            const SizedBox(height: 12),
            FilledButton(
              onPressed: () => ref.read(conversationsProvider.notifier).reload(),
              child: const Text('重试'),
            ),
          ],
        ),
      ),
      data: (items) {
        if (items.isEmpty) return const _EmptyView();
        ImConversation? system;
        final others = <ImConversation>[];
        for (final item in items) {
          if (item.peerId == systemNoticePeerId) {
            system = item;
          } else {
            others.add(item);
          }
        }
        return Column(
          children: [
            if (others.isNotEmpty) _RecentStrip(friends: others, cache: cache),
            Expanded(
              child: ListView(
                children: [
                  if (system != null) ...[
                    _SystemNoticeTile(conversation: system),
                    Container(height: 8, color: const Color(0xFFF7F8FA)),
                  ],
                  for (var i = 0; i < others.length; i++) ...[
                    if (i > 0)
                      const Divider(height: 1, thickness: 1, color: Color(0xFFF5F6F7)),
                    _ConversationTile(conversation: others[i], cache: cache),
                  ],
                ],
              ),
            ),
          ],
        );
      },
    );
  }
}

/// 最近联系人横滑条(抖音式;不含系统通知)。
class _RecentStrip extends StatelessWidget {
  const _RecentStrip({required this.friends, required this.cache});

  final List<ImConversation> friends;
  final Map<String, MatchEntry> cache;

  @override
  Widget build(BuildContext context) {
    final recent = friends.take(10).toList();
    return SizedBox(
      height: 84,
      child: ListView.separated(
        key: const Key('chats.strip'),
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 6),
        itemCount: recent.length,
        separatorBuilder: (_, _) => const SizedBox(width: 14),
        itemBuilder: (context, index) {
          final conversation = recent[index];
          final name =
              displayNameFor(cache, conversation.peerId, imName: conversation.showName);
          final avatar =
              avatarUrlFor(cache, conversation.peerId, imFaceUrl: conversation.faceUrl);
          return InkWell(
            key: Key('chats.stripItem:${conversation.peerId}'),
            onTap: () => context.push('/chat/${conversation.peerId}'),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                _Avatar(name: name, url: avatar, size: 48),
                const SizedBox(height: 4),
                SizedBox(
                  width: 56,
                  child: Text(
                    name,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 11, color: Color(0xFF555B63)),
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}

/// 「系统通知」置顶行:蓝底铃铛 + 官方标。
class _SystemNoticeTile extends StatelessWidget {
  const _SystemNoticeTile({required this.conversation});

  final ImConversation conversation;

  @override
  Widget build(BuildContext context) {
    final last = conversation.lastMessage;
    return ListTile(
      key: const Key('chats.systemNotice'),
      onTap: () => context.push('/chat/${conversation.peerId}'),
      leading: const CircleAvatar(
        radius: 24,
        backgroundColor: Color(0xFFE8F0FE),
        child: Icon(Icons.notifications_none, color: Color(0xFF2C7BE5)),
      ),
      title: Row(
        children: [
          const Text('系统通知',
              style: TextStyle(fontSize: 15.5, fontWeight: FontWeight.w600)),
          const SizedBox(width: 6),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 3),
            decoration: BoxDecoration(
              border: Border.all(color: const Color(0xFF2C7BE5)),
              borderRadius: BorderRadius.circular(3),
            ),
            child: const Text('官方',
                style: TextStyle(fontSize: 10, color: Color(0xFF2C7BE5))),
          ),
        ],
      ),
      subtitle: Text(_previewOf(last),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 13, color: Color(0xFF8A8F98))),
      trailing: _TimeBadge(last: last, unread: conversation.unreadCount),
    );
  }
}

class _ConversationTile extends StatelessWidget {
  const _ConversationTile({required this.conversation, required this.cache});

  final ImConversation conversation;
  final Map<String, MatchEntry> cache;

  @override
  Widget build(BuildContext context) {
    final name = displayNameFor(cache, conversation.peerId, imName: conversation.showName);
    final avatar = avatarUrlFor(cache, conversation.peerId, imFaceUrl: conversation.faceUrl);
    return ListTile(
      key: Key('chats.tile:${conversation.peerId}'),
      onTap: () => context.push('/chat/${conversation.peerId}'),
      leading: _Avatar(name: name, url: avatar),
      title: Text(name,
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 15.5, fontWeight: FontWeight.w600)),
      subtitle: Text(_previewOf(conversation.lastMessage),
          maxLines: 1,
          overflow: TextOverflow.ellipsis,
          style: const TextStyle(fontSize: 13, color: Color(0xFF8A8F98))),
      trailing: _TimeBadge(last: conversation.lastMessage, unread: conversation.unreadCount),
    );
  }
}

/// 圆头像:有图用图(失败静默),没图用昵称首字。
class _Avatar extends StatelessWidget {
  const _Avatar({required this.name, this.url, this.size = 48});

  final String name;
  final String? url;
  final double size;

  @override
  Widget build(BuildContext context) {
    final radius = size / 2;
    if (url != null && url!.isNotEmpty) {
      return CircleAvatar(
        radius: radius,
        backgroundImage: NetworkImage(url!),
        onBackgroundImageError: (error, stack) {},
      );
    }
    return CircleAvatar(
      radius: radius,
      backgroundColor: const Color(0xFFD6E8FF),
      child: Text(
        name.isEmpty ? '?' : name.substring(0, 1),
        style: TextStyle(
            fontSize: size * 0.38,
            fontWeight: FontWeight.w600,
            color: const Color(0xFF40454C)),
      ),
    );
  }
}

class _TimeBadge extends StatelessWidget {
  const _TimeBadge({required this.last, required this.unread});

  final ChatMessage? last;
  final int unread;

  @override
  Widget build(BuildContext context) => Column(
        mainAxisAlignment: MainAxisAlignment.center,
        crossAxisAlignment: CrossAxisAlignment.end,
        children: [
          if (last != null)
            Text(
              formatMessageTime(DateTime.fromMillisecondsSinceEpoch(last!.timestamp)),
              style: const TextStyle(fontSize: 11, color: Color(0xFF9AA0A8)),
            ),
          const SizedBox(height: 4),
          _UnreadBadge(count: unread),
        ],
      );
}

class _UnreadBadge extends StatelessWidget {
  const _UnreadBadge({required this.count});

  final int count;

  @override
  Widget build(BuildContext context) => count <= 0
      ? const SizedBox(height: 17)
      : Container(
          height: 17,
          padding: const EdgeInsets.symmetric(horizontal: 6),
          constraints: const BoxConstraints(minWidth: 17),
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: const Color(0xFFFF2C55),
            borderRadius: BorderRadius.circular(9),
          ),
          child: Text('$count',
              style: const TextStyle(color: Colors.white, fontSize: 11)),
        );
}

String _previewOf(ChatMessage? last) {
  if (last == null) return '';
  return switch (last.kind) {
    ChatMessageKind.text => last.text,
    ChatMessageKind.matchNotice => last.text.isEmpty ? '你们已互相喜欢,开始聊天吧' : last.text,
    ChatMessageKind.banNotice => last.text.isEmpty ? '系统通知' : last.text,
    ChatMessageKind.other => '[消息]',
  };
}

class _EmptyView extends StatelessWidget {
  const _EmptyView();

  @override
  Widget build(BuildContext context) => const Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.chat_bubble_outline, size: 48),
            SizedBox(height: 12),
            Text('还没有消息'),
            SizedBox(height: 4),
            Text('互相喜欢之后就能开聊了', style: TextStyle(color: Colors.black54, fontSize: 13)),
          ],
        ),
      );
}
```

`home_shell.dart` 第 36-44 行改为:

```dart
          const NavigationDestination(icon: Icon(Icons.style_outlined), label: '发现'),
          NavigationDestination(
            icon: Badge.count(
              count: unread,
              isLabelVisible: unread > 0,
              backgroundColor: const Color(0xFFFF2C55),
              child: const Icon(Icons.chat_bubble_outline),
            ),
            label: '消息',
          ),
          const NavigationDestination(icon: Icon(Icons.person_outline), label: '我的'),
```

- [ ] **Step 4: 跑测试确认通过 + analyze**

Run: `../flutter/bin/flutter.bat test test/features/chat/chats_page_test.dart test/features/shell/home_shell_test.dart && ../flutter/bin/flutter.bat analyze`
Expected: PASS;analyze 零告警

- [ ] **Step 5: 全量前端回归**

Run: `../flutter/bin/flutter.bat test`
Expected: 全绿(全仓库 `navTab('会话')` 仅存在于 chats_page_test / home_shell_test,本任务已全部更新;其余「会话」字样都在注释里,不影响测试)

- [ ] **Step 6: Commit**

```bash
git add app/lib/features/chat/chats_page.dart app/lib/features/shell/home_shell.dart app/test/features/chat/chats_page_test.dart app/test/features/shell/home_shell_test.dart
git commit -m "feat(app): 消息页抖音式版式,会话改名消息"
```

---

### Task 6: 全量回归 + CLAUDE.md + 手测交接

**Files:**
- Modify: `CLAUDE.md`(IM 集成要点 / 前端约定 / 合规 三节各加 1-3 行)
- Modify: 本计划文档(勾选进度)

- [ ] **Step 1: 双端全量回归**

Run: `cd chatapp && python manage.py test`;`cd app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test`
Expected: 后端 180+ 全绿(日志无 `IM ... 返回错误`);前端 115+ 全绿;analyze 零告警

- [ ] **Step 2: 建系统账号(真实调用,一次)**

Run: `cd chatapp && python manage.py im_setup_system_account`
Expected: `系统账号就绪:system_notice(系统通知)`(重跑也成功——7015 已存在视为成功)

- [ ] **Step 3: 更新 CLAUDE.md**

按以下要点融入对应小节现有文风:
1. 「腾讯云 IM 集成要点」加:
   - 系统消息账号 `system_notice`(昵称「系统通知」),新环境跑一次 `python manage.py im_setup_system_account`(幂等,7015 已存在视为成功);缺失时封禁通知发送失败只记日志
   - 封禁/解封系统消息:custom 消息 `type=ban_notice`(带 level)/`ban_lifted`,由 `log_ban_change` 后台线程发;重封禁**先发消息再踢**(`_send_notice_then_kick`);重封禁用户被封期间看不到消息页,留档解封后可见
2. 「前端约定」/「IM 聊天」加:
   - 底部 tab 与页面标题从「会话」改称「消息」;消息页为抖音式版式(头像横滑条 + 系统通知置顶行 + 抖音风列表);`displayNameFor` 特判 `system_notice` → 「系统通知」(常量 `systemNoticePeerId` 在 `im_client.dart`)
   - 新增 `ChatMessageKind.banNotice`(覆盖 ban_notice/ban_lifted,渲染同款灰条)
3. 「合规与审核」加:封禁联动系统通知消息一句(与上呼应)

- [ ] **Step 4: 计划文档勾选 + Commit**

把本文件所有已完成步骤勾上,执行记录(实际测试数、遇到并修复的问题)追加到文件末尾「执行记录」小节。

```bash
git add CLAUDE.md docs/superpowers/plans/2026-09-11-ban-notice-message-page.md
git commit -m "docs: 封禁系统消息+消息页改版收尾(CLAUDE.md/计划勾选)"
```

- [ ] **Step 5: 手测交接(交回用户;建议清单)**

1. 轻封 Bob(13900139000)→ Bob 端消息页出现「系统通知」置顶行(红点)→ 点开见灰条文案 → 滑卡被拒提示、聊天仍通
2. 重封 Bob → 被踢下线、整屏封禁页多一行「封禁期间所有功能暂停使用」
3. 解封 Bob → 登录后消息页收到「限制已解除」消息
4. 双端回归:Alice/Bob 正常聊天/配对不受影响;消息页版式与模拟图一致(横滑条、置顶行、行样式)

手测前重启后端(`AUTO_APPROVE` 等配置按需),确保 runserver 只有一个进程。
