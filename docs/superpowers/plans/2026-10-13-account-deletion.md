# 账号注销入口(T-17)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task(全局约定:superpowers 类任务一律内联执行,不派发子 agent)。Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付一条完整的账号注销链路 —— `DELETE /api/v1/users/me`(手机号二次确认 + 立即硬删除 + IM 删号)、App 与 Web 双端入口、隐私政策文案与接口文档同步,满足 App Store 与国内五大商店的「应用内可注销」硬性要求。

**Architecture:** 后端在现有 `users/views.py::me` 上增加 DELETE 方法(不新增路由),数据清理收敛到 `users/services.py::delete_account(user)`(单事务删数据 + `on_commit` 删磁盘文件 / 清 Redis / 入队 IM 删号);IM 侧在 `im/client.py` 加 `account_delete` 封装、`im/tasks.py` 加删号任务(唯一一处「任务参数不是 user_id」的例外,因为执行时用户行已删)。App/Web 各自复用既有的「登出通道」把本地会话收干净。

**Tech Stack:** Django 5.2 + DRF(APITestCase / 真实 provider + 假网络)、Celery + Redis、Flutter 3.47(Riverpod / go_router / flutter_test + ScriptedAdapter)、Vue 3 + Pinia + vitest + msw。

**Spec:** `docs/superpowers/specs/2026-10-13-account-deletion-design.md`(一切行为细节以它为准)

## Global Constraints

- **后端**:所有命令 cwd = `chatapp/`,Python 用 anaconda 环境 `Django`;**前置 Redis 必须在跑**(`docker compose -f docker-compose.dev.yml up -d`),否则验证码/限流/presence 相关用例会红。
- **接口文档门禁**:新增/修改任何 `/api/v1` 接口,**同一次改动内**必须同步 `docs/api/`(`python manage.py test` 会跑 `ApiDocsCoverageTests` 双向比对)。本计划在 **Task 3** 内一次性完成 —— 给 `me` 视图加 DELETE 的那一刻门禁就会变红。
- **错误契约**:失败一律 `{"code": <HTTP状态码>, "message": "<中文>", "request_id": ...}`;业务码 = 前 3 位 HTTP + 2 位序号(`config/error_codes.py`)。一律走 DRF 异常(`serializers.ValidationError` / `PermissionDenied`),**不手搓 `Response({"code": ...})`**。
- **IM 纪律**:`im/client.py` 的函数对外**永不抛异常**(失败记日志返回 `False`);`im/tasks.py` 把 `False` 转成异常让 Celery 重试;响应路径**禁止**任何第三方网络调用,跨系统副作用一律经 Celery。
- **跨栈约定**:IM 账号 = `u{user_id}`,全项目只在 `accounts/models.py::User.im_user_id` 拼,别处一律用该属性。
- **前端(App)**:`flutter analyze` 零告警 + `flutter test` 全绿(基线 **329**);所有命令 cwd = `app/`,用 `../flutter/bin/flutter.bat`。
- **「心跳」规则**:不新增视觉 token(**不动 `app/lib/core/theme/app_colors.dart`、不动 `web/src/styles/tokens.css`**);新代码禁止裸 hex / 裸字号 / 裸间距 / 裸圆角;只复用既有 core 组件(`AppDialog` / `AppTextField` / `AppButton.dangerFilled` / `AppListRow` / `AppToast`)。
- **网页端**:`vue-tsc` 零错误 + `eslint --max-warnings 0` 零告警 + `npm run test:coverage` 达标(70/60/70/70);页面**只碰 store,不直接调 `http`**;401 只走 `api/http.ts` 刷新通道;错误统一 `ApiError` + `parseApiError`。
- **协议文案双份维护**:`app/lib/features/legal/legal_texts.dart` 与 `web/src/features/legal/privacy.ts` 必须**逐字一致**;改文案时两端版本号(`legalVersion` / `LEGAL_VERSION`)同一次改动内一起 +1(下次启动各重弹一次协议弹窗)。
- **行为与文案**:除本计划显式写出的改动外,既有接口行为、key、文案逐字不变。
- **新增 App key**:`settings.row.deleteAccount`、`deleteAccount.phone`、`deleteAccount.cancel`、`deleteAccount.confirm`。既有 key 一律不得改名/删除。
- **提交**:信息中文,前缀沿用仓库风格(`feat(api):` / `feat(app):` / `feat(web):` / `docs:` / `test:`);分支 `feat/account-deletion`;每个 Task 收尾必须提交。
- **不改动**:`chatapp/moderation/permissions.py`(`BAN_EXEMPT` 白名单**不放**注销口子 —— 重封禁必须被 403 挡住,这是「防注销洗白」的天然屏障)。

---

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `chatapp/im/client.py` | 腾讯云 IM REST 封装(永不抛异常) | 加 `delete_account(identifier)` |
| `chatapp/im/tasks.py` | IM 副作用唯一入口 | 加 `delete_account(im_user_id)` 任务 |
| `chatapp/users/serializers.py` | 用户域序列化/校验 | 加 `DeleteAccountSerializer` |
| `chatapp/users/services.py` | 用户域服务(资料、照片审核、IM 同步) | 加 `delete_account(user)` + `logger` |
| `chatapp/users/presence.py` | 在线状态读写 | 加 `clear(user_id)` |
| `chatapp/users/views.py` | 用户域视图 | `me` 加 DELETE 分支 |
| `chatapp/users/tests.py` | 用户域测试 | 加 `DeleteAccountTests` |
| `chatapp/im/tests.py` | IM 域测试 | 加 client 3 例 + task 4 例 |
| `docs/api/users.md` | 用户分册对外文档 | 加 §2.10 + 改首段接口数 |
| `docs/pitfalls/backend.md` | 后端踩坑册 | 加「注销」一节 |
| `CLAUDE.md` | 项目总纲 | 接口表 + 里程碑 + IM 纪律例外 |
| `app/lib/core/api_client.dart` | Dio 薄封装 | `delete()` 支持 body |
| `app/lib/features/settings/settings_repository.dart` | 设置页账号级操作 | **新建** |
| `app/lib/features/settings/widgets/delete_account_dialog.dart` | 注销第二步确认弹窗 | **新建** |
| `app/lib/features/settings/settings_page.dart` | 设置页 | 加注销行 + 编排 |
| `app/lib/features/legal/legal_texts.dart` | 协议全文 | §四加注销路径 + 版本 2 |
| `app/test/features/settings/delete_account_dialog_test.dart` | 弹窗测试 | **新建** |
| `app/test/features/settings/settings_page_test.dart` | 设置页测试 | 加 2 例 |
| `web/src/api/users.ts` | 用户域 api 层 | 加 `deleteAccount` |
| `web/src/stores/session.ts` | 会话 store | 加 `deleteAccount` action |
| `web/src/features/settings/DeleteAccountDialog.vue` | 注销确认弹窗 | **新建** |
| `web/src/features/settings/SettingsPage.vue` | 设置页 | 危险区 + 编排 |
| `web/src/features/legal/privacy.ts` | 隐私政策正文 | §四加注销路径 |
| `web/src/features/legal/agreed.ts` | 协议版本号 | `LEGAL_VERSION` → 2 |
| `web/tests/unit/session-store.spec.ts` | store 单测 | 加 2 例 |
| `web/tests/component/settings-page.spec.ts` | 设置页组件测试 | 加 2 例 |

---

### Task 0: 基线与分支

**Files:** 无代码改动

**Interfaces:**
- Produces: 分支 `feat/account-deletion`(后续全部任务在此分支提交)

- [ ] **Step 1: 建分支**

```bash
git checkout master
git pull --ff-only
git checkout -b feat/account-deletion
git log --oneline -2   # 应含 fd4c825(spec)
```

- [ ] **Step 2: 起 Redis(后端测试前置)**

```bash
cd chatapp
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml ps   # redis 应 Up
```

- [ ] **Step 3: 后端基线全绿**

```bash
cd chatapp
python manage.py test
```

Expected: 全绿(基线 337,含 `ApiDocsCoverageTests`)。红了先停下排查,别带病开工。

- [ ] **Step 4: App 基线全绿**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

Expected: analyze 零告警;测试 **329 全绿**。

- [ ] **Step 5: Web 基线全绿**

```bash
cd web
npm run type-check
npm run lint
npm run test:coverage
```

Expected: 类型零错误、lint 零告警、覆盖率门槛(70/60/70/70)通过。

---

### Task 1: `im/client.py::delete_account`(IM 删号封装)

**Files:**
- Modify: `chatapp/im/client.py`(在 `kick_user` 之后新增函数)
- Test: `chatapp/im/tests.py`(`ImClientTests` 内追加 3 例 + 顶部 import 补名字)

**Interfaces:**
- Consumes: 模块内既有的 `_request(service, command, payload=None, identifier=None) -> dict` 与 `_check(result, what) -> bool`
- Produces: `delete_account(identifier: str) -> bool` —— Task 2 的任务体调用它

- [ ] **Step 1: 写失败测试**

在 `chatapp/im/tests.py` 顶部把 `delete_account` 加进 client 的 import 列表(保持字母序):

```python
from .client import (_request, black_list_add, black_list_delete, delete_account,
                     ensure_account, import_account, kick_user, send_ban_lifted,
                     send_ban_notice, send_custom_elem, send_match_notice,
                     send_post_commented, send_report_handled, send_text,
                     set_profile_avatar, set_profile_nick)
```

在 `class ImClientTests(SimpleTestCase)` 内、`test_kick_user_network_error_returns_false` 之后追加:

```python
    def test_delete_account_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(delete_account("u9"))
        args, _ = req.call_args
        self.assertEqual(args[0], "im_open_login_svc")
        self.assertEqual(args[1], "account_delete")
        self.assertEqual(args[2], {"DeleteItem": [{"UserID": "u9"}]})

    def test_delete_account_error_code_returns_false(self):
        with patch("im.client._request",
                   return_value={"ErrorCode": 7011, "ErrorInfo": "account not exist"}):
            self.assertFalse(delete_account("u9"))

    def test_delete_account_network_error_returns_false(self):
        with patch("im.client._request", side_effect=Exception("boom")):
            self.assertFalse(delete_account("u9"))
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd chatapp
python manage.py test im.tests.ImClientTests -v 2
```

Expected: FAIL —— `ImportError: cannot import name 'delete_account' from 'im.client'`。

- [ ] **Step 3: 最小实现**

在 `chatapp/im/client.py` 的 `kick_user` 函数之后插入:

```python
def delete_account(identifier: str) -> bool:
    """删除 IM 账号(注销账号用)。

    ⚠️ 参数形状实施时用真凭据实测:本仓库已有两处同类前车之鉴 ——
    `sendmsg` 的 identifier 必须是管理员(否则 60010)、`account_import`
    对已存在账号会**覆盖** Nick/FaceUrl 而不是返回 7015。
    """
    payload = {"DeleteItem": [{"UserID": identifier}]}
    try:
        result = _request("im_open_login_svc", "account_delete", payload)
    except Exception:
        logger.exception("IM account_delete 调用失败 identifier=%s", identifier)
        return False
    return _check(result, "account_delete")
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd chatapp
python manage.py test im.tests.ImClientTests -v 2
```

Expected: PASS(3 例新增全绿,既有用例不回归)。

- [ ] **Step 5: 提交**

```bash
git add chatapp/im/client.py chatapp/im/tests.py
git commit -m "feat(im): client 加 account_delete 封装(注销账号用)"
```

---

### Task 2: `im/tasks.py::delete_account` 删号任务

**Files:**
- Modify: `chatapp/im/tasks.py`(文件末尾新增任务)
- Test: `chatapp/im/tests.py`(新增 `ImDeleteAccountTaskTests` 类 + 顶部 import 补名字)

**Interfaces:**
- Consumes: `im/client.py::kick_user(identifier) -> bool`、`im/client.py::delete_account(identifier) -> bool`(Task 1)、模块内 `RETRY_POLICY` 与 `_require(ok, what)`
- Produces: Celery 任务 `delete_account(im_user_id: str) -> None` —— Task 4 的服务层用 `im_tasks.delete_account.delay(im_user_id)` 入队

**⚠️ 本任务打破一条既有纪律(有意为之,必须写进注释):** 参数是 `im_user_id` 字符串,不是 `user_id`。原因:该任务由注销流程在**用户行已删除之后**入队,任务内查库必然拿到 `None`,沿用现有 `_user()` 兜底会**静默跳过**,删号永远不会发生。

- [ ] **Step 1: 写失败测试**

在 `chatapp/im/tests.py` 顶部 tasks 的 import 里加上 `delete_account as delete_account_task`:

```python
from .tasks import (ban_lifted, ban_notice, blacklist_add, blacklist_remove,
                    delete_account as delete_account_task,
                    import_account as import_account_task, kick_pending,
                    kick_pending_key, post_commented as post_commented_task,
                    report_handled as report_handled_task, sync_profile)
```

在 `class ImSideEffectTaskTests` 之后追加新类:

```python
class ImDeleteAccountTaskTests(TestCase):
    """注销删号:先踢后删;踢失败不阻塞删号;删号失败抛异常让 Celery 重试。

    回归重点:任务**不查库** —— 调用时用户行已经删掉了,参数是 im_user_id。
    """

    def test_kicks_then_deletes(self):
        calls = []
        with patch("im.client.kick_user",
                   side_effect=lambda *a: calls.append("kick") or True), \
                patch("im.client.delete_account",
                      side_effect=lambda *a: calls.append("delete") or True):
            delete_account_task.run("u9")
        self.assertEqual(calls, ["kick", "delete"])   # 顺序不能反:先断在线会话再删号

    def test_kick_failure_does_not_block_delete(self):
        with patch("im.client.kick_user", return_value=False), \
                patch("im.client.delete_account", return_value=True) as delete:
            delete_account_task.run("u9")   # 不抛异常
        delete.assert_called_once_with("u9")

    def test_delete_failure_raises_so_celery_retries(self):
        with patch("im.client.kick_user", return_value=True), \
                patch("im.client.delete_account", return_value=False):
            with self.assertRaises(RuntimeError):
                delete_account_task.run("u9")

    def test_does_not_touch_database(self):
        with patch("im.client.kick_user", return_value=True), \
                patch("im.client.delete_account", return_value=True), \
                patch("im.tasks._user") as user_lookup:
            delete_account_task.run("u9")
        user_lookup.assert_not_called()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd chatapp
python manage.py test im.tests.ImDeleteAccountTaskTests -v 2
```

Expected: FAIL —— `ImportError: cannot import name 'delete_account' from 'im.tasks'`。

- [ ] **Step 3: 最小实现**

在 `chatapp/im/tasks.py` 文件末尾追加:

```python
@shared_task(**RETRY_POLICY)
def delete_account(im_user_id: str) -> None:
    """注销账号:先踢下线,再删 IM 账号。

    🔴 参数是 **im_user_id 字符串**,不是 user_id —— 这是全项目唯一一处
    「任务参数不是 user_id」的例外:本任务由注销流程在**用户行已删除之后**入队,
    任务内查库必然拿到 None,沿用 `_user()` 兜底会静默跳过、删号永不发生。
    调用方在事务提交后传入注销前取好的 `user.im_user_id`(即 f"u{user.id}")。

    踢失败不阻塞删号(删号才是目的);删号失败抛异常交给 RETRY_POLICY 重试。
    """
    im_client.kick_user(im_user_id)
    _require(im_client.delete_account(im_user_id), "delete_account")
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd chatapp
python manage.py test im -v 2
```

Expected: PASS(4 例新增全绿,IM 域不回归)。

- [ ] **Step 5: 提交**

```bash
git add chatapp/im/tasks.py chatapp/im/tests.py
git commit -m "feat(im): 注销删号任务(参数为 im_user_id,任务内不查库)"
```

---

### Task 3: `DELETE /api/v1/users/me` 契约层 + 数据删除 + 接口文档

**Files:**
- Modify: `chatapp/users/serializers.py`(文件末尾新增序列化器)
- Modify: `chatapp/users/services.py`(新增 `delete_account` + `logger`)
- Modify: `chatapp/users/views.py`(`me` 视图加 DELETE 分支 + import)
- Modify: `docs/api/users.md`(首段接口数 + 新增 §2.10)
- Test: `chatapp/users/tests.py`(新增 `DeleteAccountTests`)

**Interfaces:**
- Consumes: `users/services.py::get_profile(user)`(既有)、`config/exceptions.py::api_exception_handler`(既有全局异常处理器)、`moderation/permissions.py::IsNotHeavyBanned`(既有全局权限类)
- Produces:
  - `DeleteAccountSerializer`(字段 `phone = CharField(max_length=20)`,`validate_phone` 与 `context["request"].user.phone` 比对)
  - `delete_account(user) -> None`(本任务只做数据删除;Task 4 扩展副作用)
  - 端点 `DELETE /api/v1/users/me` → 204

**⚠️ 门禁联动:** 给 `me` 加 DELETE 的那一刻,`ApiDocsCoverageTests` 就会红。所以 `docs/api/users.md` 必须在**同一个 Task 内**改完(Step 3 一起做)。

- [ ] **Step 1: 写失败测试**

在 `chatapp/users/tests.py` 顶部 import 区补充(现有 import 保留)。注意 `moderation.models` **已经有一行** `from moderation.models import Block`,把它就地扩成下面这行,别再加第二行:

```python
from django.conf import settings
from django.db.models import Q

from accounts import sms_codes
from discovery.models import Match, Swipe
from feed.models import Post, PostComment, PostImage
from moderation.models import BanLog, Block, Report
```

在文件末尾追加测试类:

```python
class DeleteAccountTests(AuthMixin, APITestCase):
    """注销账号:立即硬删除 + 手机号二次确认 + 重封禁 403(防注销洗白)。"""

    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)   # 别把测试图片写进真 media/
        override.enable()
        self.addCleanup(override.disable)
        # 清掉别的用例留下的 IP 限流计数 / 验证码 / presence 残留
        # (本类末尾要真调一次 /auth/sms/verify,不清会被别处的限流计数连累)
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(phone="13800138000")
        self.login(self.user)
        self.url = "/api/v1/users/me"

    def _delete(self, phone="13800138000"):
        return self.client.delete(self.url, {"phone": phone}, format="json")

    def test_requires_auth(self):
        self.client.credentials()
        resp = self._delete()
        self.assertEqual(resp.status_code, 401)

    def test_phone_mismatch_rejected_and_data_kept(self):
        resp = self._delete(phone="13900139000")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 400)
        self.assertEqual(resp.json()["message"], "手机号与当前账号不一致")
        self.assertTrue(User.objects.filter(id=self.user.id).exists())

    def test_phone_missing_rejected(self):
        resp = self.client.delete(self.url, {}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 400)
        self.assertTrue(User.objects.filter(id=self.user.id).exists())

    def test_heavy_banned_cannot_delete(self):
        Profile.objects.create(user=self.user, status=ProfileStatus.BANNED_HEAVY)
        resp = self._delete()
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(User.objects.filter(id=self.user.id).exists())

    def test_light_banned_can_delete(self):
        Profile.objects.create(user=self.user, status=ProfileStatus.BANNED_LIGHT)
        self.assertEqual(self._delete().status_code, 204)

    def test_success_deletes_user_and_all_related_rows(self):
        user_id = self.user.id
        other = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.user, nickname="小明")
        Photo.objects.create(user=self.user, file="photos/a.png")
        Swipe.objects.create(swiper=self.user, target=other, action="like")
        Swipe.objects.create(swiper=other, target=self.user, action="like")
        Match.objects.create(**Match.pair_kwargs(self.user, other))
        post = Post.objects.create(author=self.user, text="动态")
        PostImage.objects.create(post=post, file="posts/a.png")
        PostComment.objects.create(post=post, author=other, text="评论")
        Block.objects.create(blocker=self.user, blocked=other)
        Report.objects.create(reporter=other, target=self.user, type="harassment")
        BanLog.objects.create(user=self.user, action="ban_light", reason="x")

        resp = self._delete()

        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.content, b"")
        self.assertFalse(User.objects.filter(id=user_id).exists())
        self.assertFalse(Profile.objects.filter(user_id=user_id).exists())
        self.assertFalse(Photo.objects.filter(user_id=user_id).exists())
        self.assertFalse(Swipe.objects.filter(Q(swiper_id=user_id) | Q(target_id=user_id)).exists())
        self.assertFalse(Match.objects.filter(Q(user_a_id=user_id) | Q(user_b_id=user_id)).exists())
        self.assertFalse(Post.objects.filter(author_id=user_id).exists())
        self.assertFalse(PostImage.objects.filter(post__author_id=user_id).exists())
        self.assertFalse(PostComment.objects.filter(author_id=user_id).exists())
        self.assertFalse(Block.objects.filter(Q(blocker_id=user_id) | Q(blocked_id=user_id)).exists())
        self.assertFalse(Report.objects.filter(Q(reporter_id=user_id) | Q(target_id=user_id)).exists())
        self.assertFalse(BanLog.objects.filter(user_id=user_id).exists())

    def test_other_users_data_untouched(self):
        other = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=other, nickname="小红")
        Photo.objects.create(user=other, file="photos/b.png")
        self.assertEqual(self._delete().status_code, 204)
        self.assertTrue(User.objects.filter(id=other.id).exists())
        self.assertTrue(Profile.objects.filter(user=other).exists())
        self.assertTrue(Photo.objects.filter(user=other).exists())

    def test_old_token_rejected_after_delete(self):
        self.assertEqual(self._delete().status_code, 204)
        # 同一个 access token:用户行没了 → 鉴权失败
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 401)

    def test_same_phone_can_register_again_as_new_user(self):
        old_id = self.user.id
        self.assertEqual(self._delete().status_code, 204)

        self.client.credentials()   # 旧令牌已失效,换匿名请求
        cache.delete(f"sms:send:13800138000")
        sms_codes.store("13800138000", settings.SMS_DEV_CODE)
        resp = self.client.post("/api/v1/auth/sms/verify",
                                {"phone": "13800138000", "code": settings.SMS_DEV_CODE},
                                format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["is_new_user"])
        self.assertNotEqual(resp.json()["user_id"], old_id)
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd chatapp
python manage.py test users.tests.DeleteAccountTests -v 2
```

Expected: FAIL —— 多数用例拿到 405(视图不接受 DELETE);`test_same_phone_can_register_again_as_new_user` 会在「同号仍能登录且 `is_new_user` 为 False」处失败。

- [ ] **Step 3: 最小实现(三处代码 + 一处文档)**

**(a) `chatapp/users/serializers.py`** —— 文件末尾追加:

```python
class DeleteAccountSerializer(serializers.Serializer):
    """注销账号:要求输入完整手机号做二次确认(不可恢复操作)。"""

    phone = serializers.CharField(max_length=20)

    def validate_phone(self, value):
        request = self.context.get("request")
        if request is None or value.strip() != request.user.phone:
            raise serializers.ValidationError("手机号与当前账号不一致")
        return value.strip()
```

**(b) `chatapp/users/services.py`** —— 顶部加 `import logging`,并追加:

```python
logger = logging.getLogger(__name__)
```

文件末尾追加:

```python
def delete_account(user) -> None:
    """注销账号:删除该用户的全部数据。

    本函数只负责数据层(事务内);磁盘文件 / Redis / IM 删号等副作用
    由后续任务补在 `transaction.on_commit` 里。

    ⚠️ 调用前必须取好 `user.id` / `user.im_user_id` —— `user.delete()` 之后
    Django 会把实例的主键置为 None(见 users/tests.py 的回归用例)。
    """
    user.delete()
```

**(c) `chatapp/users/views.py`** —— 改 import 与 `me` 视图:

```python
from .serializers import (DeleteAccountSerializer, PhotoSerializer, PhotoUploadSerializer,
                          PreferenceSerializer, ProfileSerializer, ProfileUpdateSerializer,
                          PublicProfileSerializer, TagSerializer)
from .services import delete_account, get_profile, sync_im_avatar, sync_im_nickname
```

```python
@api_view(["GET", "PATCH", "DELETE"])
def me(request):
    if request.method == "DELETE":
        # 手机号二次确认:不可恢复操作,body 必须带上当前账号的手机号。
        # 重封禁用户由全局 IsNotHeavyBanned 拦成 403(白名单只放行 GET),防「注销洗白」。
        serializer = DeleteAccountSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        delete_account(request.user)
        return Response(status=204)
    profile = get_profile(request.user)
    if request.method == "PATCH":
        serializer = ProfileUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        tag_ids = data.pop("tag_ids", None)
        old_nickname = profile.nickname
        for field, value in data.items():
            setattr(profile, field, value)
        profile.save()
        if tag_ids is not None:
            profile.tags.set(Tag.objects.filter(id__in=tag_ids))
        profile.refresh_status()
        if profile.nickname != old_nickname:
            sync_im_nickname(profile.user)
    return Response(ProfileSerializer(profile, context={"request": request}).data)
```

**(d) `docs/api/users.md`** —— 首段改成 10 个接口并补一句;文件末尾追加新分节。⚠️ 下面这段要整段粘进 `.md`,**它自己含 bash 代码块**,所以这里用四反引号包住,粘贴时不要带上外层围栏:

````markdown
本分册含 10 个接口:我的资料(查/改/注销)、标签池、照片(传/删)、择偶偏好(查/改)、他人公开资料、在线状态。
````

````markdown
---

### 2.10 注销账号

> `DELETE` `/api/v1/users/me` · 需要鉴权 · 无额外限流

**接口描述**

注销当前账号(不可恢复)。请求体必须带上当前账号的完整手机号做二次确认,不匹配则拒绝且**不删除任何数据**。校验通过后服务端立即硬删除账号及其全部关联数据(资料、照片与图片文件、滑卡记录、配对关系、广场动态与评论、拉黑与举报记录、封禁审计记录),并释放该手机号 —— 同一手机号可立即重新注册,得到的是一个**全新账号**。

服务端同时会清掉在线状态、异步删除腾讯云 IM 账号。**重封禁(`banned_heavy`)账号无法自助注销**(返回 403),需联系客服;轻封禁(`banned_light`)可以注销。

**请求参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| phone | 是 | String | 当前账号的完整手机号(请求体 JSON 字段,二次确认用) |

**响应参数**

无(HTTP 204,响应体为空)。

**请求示例**

```bash
curl -X DELETE http://<域名>/api/v1/users/me \
  -H "Authorization: Bearer <access>" \
  -H "Content-Type: application/json" \
  -d '{"phone": "13800138000"}'
```

**响应示例**

```
HTTP/1.1 204 No Content
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 400 | 400 | 请输入手机号 / 手机号与当前账号不一致 | 提示用户重新输入当前账号的手机号 |
| 403 | 403 | 账号已被封禁,如有疑问请联系客服 | 重封禁账号不能自助注销 |
| 401 | 401 | 未认证或令牌失效(账号已注销后再调用也会落到这里) | 重新登录或刷新令牌 |
````

- [ ] **Step 4: 跑测试确认通过(含文档门禁)**

```bash
cd chatapp
python manage.py test users.tests.DeleteAccountTests -v 2
python manage.py test config.tests -v 2
```

Expected: PASS;`ApiDocsCoverageTests` 绿(若红,报错会直接指出缺哪个端点的文档行)。

- [ ] **Step 5: 提交**

```bash
git add chatapp/users/serializers.py chatapp/users/services.py chatapp/users/views.py \
        chatapp/users/tests.py docs/api/users.md
git commit -m "feat(api): DELETE /users/me 注销账号(手机号二次确认 + 硬删除)+ 接口文档"
```

---

### Task 4: 注销副作用(磁盘文件 + presence 清理 + IM 删号入队)

**Files:**
- Modify: `chatapp/users/presence.py`(新增 `clear`)
- Modify: `chatapp/users/services.py`(`delete_account` 扩展)
- Test: `chatapp/users/tests.py`(`DeleteAccountTests` 追加 4 例)

**Interfaces:**
- Consumes: `im/tasks.py::delete_account(im_user_id)`(Task 2)、`im/tasks.py::kick_pending_key(user_id) -> str`(既有)、`users/presence.py::_key`(模块私有,故本任务补一个公开 `clear`)
- Produces: `presence.clear(user_id) -> None`

**⚠️ 两个必须避开的坑:**

1. **`user.delete()` 之后 `user.id` 变成 `None`** —— 所有要在 `on_commit` 里用到的值(`user_id`、`im_user_id`)必须在 `user.delete()` **之前**取好。
2. **`on_commit` 必须用 `captureOnCommitCallbacks(execute=True)` 才能在测试里跑起来**(`APITestCase` 全程包在事务里,普通写法回调永不执行)。

- [ ] **Step 1: 写失败测试**

在 `chatapp/users/tests.py` 顶部 import 区补:

```python
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from im import tasks as im_tasks
```

在 `DeleteAccountTests` 内追加(放在 `test_other_users_data_untouched` 之前位置随意,保持同类相邻):

```python
    def test_deletes_photo_and_post_image_files_on_disk(self):
        user_id = self.user.id
        photo = Photo.objects.create(user=self.user)
        photo.file.save("a.png", ContentFile(PNG_1PX), save=True)
        post = Post.objects.create(author=self.user, text="动态")
        image = PostImage.objects.create(post=post)
        image.file.save("b.png", ContentFile(PNG_1PX), save=True)
        photo_name, image_name = photo.file.name, image.file.name
        self.assertTrue(default_storage.exists(photo_name))
        self.assertTrue(default_storage.exists(image_name))

        with self.captureOnCommitCallbacks(execute=True):
            resp = self._delete()

        self.assertEqual(resp.status_code, 204)
        self.assertFalse(default_storage.exists(photo_name))
        self.assertFalse(default_storage.exists(image_name))

    def test_clears_presence_and_kick_pending_flag(self):
        user_id = self.user.id
        presence.touch(user_id)
        cache.set(im_tasks.kick_pending_key(user_id), 1, 60)
        self.assertIsNotNone(presence.get_presence([user_id])[user_id]["last_active_at"])

        with self.captureOnCommitCallbacks(execute=True):
            self._delete()

        self.assertIsNone(presence.get_presence([user_id])[user_id]["last_active_at"])
        self.assertIsNone(cache.get(im_tasks.kick_pending_key(user_id)))

    @patch("im.tasks.delete_account.delay")
    def test_enqueues_im_delete_with_im_user_id_after_commit(self, delay):
        user_id = self.user.id          # ⚠️ 必须在注销前取,删完 user.id 会是 None
        with self.captureOnCommitCallbacks(execute=True):
            resp = self._delete()
        self.assertEqual(resp.status_code, 204)
        delay.assert_called_once_with(f"u{user_id}")

    @patch("im.tasks.delete_account.delay")
    def test_nothing_enqueued_when_phone_mismatch(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self._delete(phone="13900139000")
        self.assertEqual(resp.status_code, 400)
        delay.assert_not_called()
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd chatapp
python manage.py test users.tests.DeleteAccountTests -v 2
```

Expected: FAIL 4 例 —— 文件仍在磁盘上、presence 仍在、`delay` 未被调用。

- [ ] **Step 3: 最小实现**

**(a) `chatapp/users/presence.py`** —— 在 `touch` 之后追加:

```python
def clear(user_id: int) -> None:
    """注销账号时抹掉在线痕迹;失败只记日志。"""
    try:
        cache.delete(_key(user_id))
    except Exception:
        logger.warning("presence 清理失败 user_id=%s", user_id, exc_info=True)
```

**(b) `chatapp/users/services.py`** —— 把顶部 import 区改成下面这样(相对现状:新增 `logging`、`cache`、`default_storage`、`presence`),并把 `delete_account` 换成完整实现:

```python
import logging

from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import transaction
from django.utils import timezone

from im import tasks as im_tasks

from . import presence
from .models import PhotoStatus, Preference, Profile

logger = logging.getLogger(__name__)
```

```python
def delete_account(user) -> None:
    """注销账号:删除该用户的全部数据,并清理磁盘文件 / 缓存 / IM 账号。

    顺序有讲究:
      1. 事务内先**收集**待删文件路径与 im_user_id(删行之后就取不到了,
         且 `user.delete()` 会把实例主键置为 None);
      2. 事务内删 User 行(CASCADE 清掉全部关联数据);
      3. 事务提交后(on_commit)删磁盘文件、清 Redis、入队 IM 删号 ——
         响应路径禁止外部调用,且入队必须晚于提交(否则事务回滚了 IM 号却没了)。
    """
    from feed.models import PostImage   # 延迟导入,避免 app 加载顺序问题(同 im/tasks.py)

    file_names = list(user.photos.values_list("file", flat=True))
    file_names += list(PostImage.objects.filter(post__author=user).values_list("file", flat=True))
    user_id = user.id
    im_user_id = user.im_user_id

    user.delete()

    def _cleanup():
        for name in file_names:
            try:
                default_storage.delete(name)
            except Exception:
                logger.warning("注销删文件失败 name=%s", name, exc_info=True)
        presence.clear(user_id)
        cache.delete(im_tasks.kick_pending_key(user_id))
        im_tasks.delete_account.delay(im_user_id)

    transaction.on_commit(_cleanup, robust=True)
```

(Task 3 已经在同文件加过 `logger = logging.getLogger(__name__)`;这里只是把它并入新的 import 区,不要重复定义。)

- [ ] **Step 4: 跑测试确认通过**

```bash
cd chatapp
python manage.py test users.tests.DeleteAccountTests -v 2
python manage.py test users -v 2
```

Expected: PASS(全部 4 例新增绿,且 Task 3 的 9 例不回归 —— 注意 `Photo.objects.create(file="photos/a.png")` 这类**假路径**在 `default_storage.delete` 下是静默无害的)。

- [ ] **Step 5: 提交**

```bash
git add chatapp/users/presence.py chatapp/users/services.py chatapp/users/tests.py
git commit -m "feat(api): 注销副作用 — 删磁盘文件 / 清 presence 与待踢标记 / 入队 IM 删号"
```

---

### Task 5: App 网络层(`ApiClient.delete` 支持 body + `SettingsRepository`)

**Files:**
- Modify: `app/lib/core/api_client.dart`(`delete` 加可选 `data`)
- Create: `app/lib/features/settings/settings_repository.dart`
- Test: `app/test/features/settings/settings_repository_test.dart`

**Interfaces:**
- Consumes: `core/api_client.dart::ApiClient`、`core/providers.dart::apiClientProvider`、`core/providers.dart::baseDioProvider`(测试 override 点)
- Produces: `SettingsRepository.deleteAccount(String phone) -> Future<void>` 与 `settingsRepositoryProvider` —— Task 7 的设置页调用它

- [ ] **Step 1: 写失败测试**

新建 `app/test/features/settings/settings_repository_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/settings/settings_repository.dart';

import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;

  ProviderContainer makeContainer() {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))
      ..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
    ]);
    addTearDown(container.dispose);
    return container;
  }

  // ⚠️ 必须 mock:apiClientProvider 会挂 AuthInterceptor,它读凭证要 SharedPreferences,
  // 不 mock 会抛 MissingPluginException(同 blocked_users_page_test.dart)。
  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
  });

  test('deleteAccount 发 DELETE /users/me 并带上手机号', () async {
    adapter.routes['DELETE /users/me'] = (options) => ok({}, status: 204);

    await makeContainer().read(settingsRepositoryProvider).deleteAccount('13800138000');

    final request = adapter.log.single;
    expect(request.method, 'DELETE');
    expect(request.path, '/users/me');
    expect(request.data, {'phone': '13800138000'});
  });

  test('deleteAccount 把 400 翻成 ApiException(手机号不匹配)', () async {
    adapter.routes['DELETE /users/me'] =
        (options) => jsonError(400, '手机号与当前账号不一致');

    await expectLater(
      makeContainer().read(settingsRepositoryProvider).deleteAccount('13900139000'),
      throwsA(isA<ApiException>().having((e) => e.statusCode, 'statusCode', 400)),
    );
  });
}
```

(上面 import 区已含 `api_exception.dart`,无需另加。)

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/settings/settings_repository_test.dart
```

Expected: FAIL —— `Target of URI doesn't exist: 'package:chatapp_app/features/settings/settings_repository.dart'`。

- [ ] **Step 3: 最小实现**

**(a) `app/lib/core/api_client.dart`** —— 把 `delete` 换成:

```dart
  /// [data] 用于 DELETE 带请求体(注销账号要带手机号做二次确认)。
  Future<dynamic> delete(String path, {Object? data}) =>
      _guard(() => _dio.delete<dynamic>(path, data: data));
```

**(b) 新建 `app/lib/features/settings/settings_repository.dart`:**

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';

/// 设置页里的账号级操作。注销是**不可恢复**操作,故单独成一个仓库,
/// 不塞进 ProfileRepository(它只管资料读写)。
class SettingsRepository {
  SettingsRepository(this._api);

  final ApiClient _api;

  /// 注销账号:后端要求带上完整手机号做二次确认,不匹配返回 400。
  Future<void> deleteAccount(String phone) async {
    await _api.delete('/users/me', data: {'phone': phone});
  }
}

final settingsRepositoryProvider = Provider<SettingsRepository>(
    (ref) => SettingsRepository(ref.watch(apiClientProvider)));
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/settings/settings_repository_test.dart
../flutter/bin/flutter.bat analyze
```

Expected: 2 例 PASS;analyze 零告警。

- [ ] **Step 5: 提交**

```bash
git add app/lib/core/api_client.dart app/lib/features/settings/settings_repository.dart \
        app/test/features/settings/settings_repository_test.dart
git commit -m "feat(app): ApiClient.delete 支持请求体 + SettingsRepository.deleteAccount"
```

---

### Task 6: App `DeleteAccountDialog`(注销第二步确认)

**Files:**
- Create: `app/lib/features/settings/widgets/delete_account_dialog.dart`
- Test: `app/test/features/settings/delete_account_dialog_test.dart`

**Interfaces:**
- Consumes: `core/widgets/app_dialog.dart::AppDialog`、`core/widgets/app_text_field.dart::AppTextField`、`core/widgets/app_button.dart::AppButton/AppButtonVariant.dangerFilled`、`core/theme/*` token
- Produces: `Future<String?> showDeleteAccountDialog(BuildContext context)` —— **返回用户输入的手机号**(`null` = 取消)。Task 7 的设置页拿它去调 `SettingsRepository.deleteAccount`

**⚠️ 组件测试的坑(批次⑥实测):** `AppTextField` 根节点是 `mainAxisSize.max` 的 `Column`,直接塞进 `Scaffold(body:)` 会撑满整屏、按 key 点击会落空。本弹窗走 `AppDialog`(有界约束)所以生产环境没问题;测试里也**必须**通过 `showDialog` 打开(照 `app_dialog_test.dart` 的写法),不要直接 `pumpWidget` 这个私有 widget。

- [ ] **Step 1: 写失败测试**

新建 `app/test/features/settings/delete_account_dialog_test.dart`:

```dart
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/widgets/app_button.dart';
import 'package:chatapp_app/features/settings/widgets/delete_account_dialog.dart';

void main() {
  /// 照 app_dialog_test.dart 的写法:用按钮打开弹窗,把返回值存进闭包变量。
  Future<void> openDialog(WidgetTester tester, void Function(String?) onResult) async {
    await tester.pumpWidget(MaterialApp(
      home: Scaffold(
        body: Builder(
          builder: (context) => TextButton(
            onPressed: () async => onResult(await showDeleteAccountDialog(context)),
            child: const Text('开'),
          ),
        ),
      ),
    ));
    await tester.tap(find.text('开'));
    await tester.pumpAndSettle();
  }

  testWidgets('手机号不合法时确认按钮禁用,填对了才可点', (tester) async {
    await openDialog(tester, (_) {});

    expect(find.text('注销账号'), findsOneWidget);
    expect(find.byKey(const Key('deleteAccount.phone')), findsOneWidget);
    expect(
      tester.widget<AppButton>(find.byKey(const Key('deleteAccount.confirm'))).onPressed,
      isNull, // 未输入 → 禁用
    );

    await tester.enterText(find.byKey(const Key('deleteAccount.phone')), '138');
    await tester.pumpAndSettle();
    expect(
      tester.widget<AppButton>(find.byKey(const Key('deleteAccount.confirm'))).onPressed,
      isNull, // 位数不够 → 仍禁用
    );

    await tester.enterText(find.byKey(const Key('deleteAccount.phone')), '13800138000');
    await tester.pumpAndSettle();
    expect(
      tester.widget<AppButton>(find.byKey(const Key('deleteAccount.confirm'))).onPressed,
      isNotNull,
    );
  });

  testWidgets('确认返回输入的手机号;取消返回 null', (tester) async {
    String? result;
    await openDialog(tester, (value) => result = value);

    await tester.enterText(find.byKey(const Key('deleteAccount.phone')), '13800138000');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('deleteAccount.confirm')));
    await tester.pumpAndSettle();
    expect(result, '13800138000');

    await tester.tap(find.text('开'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('deleteAccount.cancel')));
    await tester.pumpAndSettle();
    expect(result, isNull);
  });

  testWidgets('确认按钮是危险实底(§7「实底(二次确认后)」)', (tester) async {
    await openDialog(tester, (_) {});
    expect(
      tester.widget<AppButton>(find.byKey(const Key('deleteAccount.confirm'))).variant,
      AppButtonVariant.dangerFilled,
    );
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/settings/delete_account_dialog_test.dart
```

Expected: FAIL —— `Target of URI doesn't exist: .../widgets/delete_account_dialog.dart`。

- [ ] **Step 3: 最小实现**

新建 `app/lib/features/settings/widgets/delete_account_dialog.dart`:

```dart
import 'package:flutter/material.dart';

import '../../../core/theme/app_colors.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/theme/app_typography.dart';
import '../../../core/widgets/app_button.dart';
import '../../../core/widgets/app_dialog.dart';
import '../../../core/widgets/app_text_field.dart';

/// 注销账号的第二步确认:必须输入完整手机号才能提交(不可恢复操作)。
///
/// 返回用户输入的手机号;取消 / 点外部返回 null。请求由调用方发。
Future<String?> showDeleteAccountDialog(BuildContext context) =>
    showDialog<String>(context: context, builder: (_) => const _DeleteAccountDialog());

class _DeleteAccountDialog extends StatefulWidget {
  const _DeleteAccountDialog();

  @override
  State<_DeleteAccountDialog> createState() => _DeleteAccountDialogState();
}

class _DeleteAccountDialogState extends State<_DeleteAccountDialog> {
  static final _phonePattern = RegExp(r'^\d{11}$');

  /// 注销后会被永久删除的内容(与隐私政策 §四、docs/api/users.md §2.10 口径一致)。
  static const _consequences = [
    '个人资料、标签与全部照片',
    '配对关系与聊天关系',
    '你发布的动态与评论',
    '拉黑与举报记录',
    '账号本身(手机号将被释放)',
  ];

  final _controller = TextEditingController();
  var _valid = false;

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AppDialog(
        title: '注销账号',
        message: '以下内容将被永久删除,且无法恢复:',
        content: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            for (final item in _consequences)
              Padding(
                padding: const EdgeInsets.only(bottom: AppSpacing.xs),
                child: Text('· $item',
                    style: AppText.caption.copyWith(color: AppColors.text2)),
              ),
            const SizedBox(height: AppSpacing.md),
            AppTextField(
              key: const Key('deleteAccount.phone'),
              controller: _controller,
              label: '请输入当前账号的手机号以确认',
              hint: '11 位手机号',
              keyboardType: TextInputType.phone,
              onChanged: (value) =>
                  setState(() => _valid = _phonePattern.hasMatch(value.trim())),
            ),
          ],
        ),
        actions: [
          AppButton(
            key: const Key('deleteAccount.cancel'),
            label: '取消',
            variant: AppButtonVariant.secondary,
            onPressed: () => Navigator.pop(context),
          ),
          AppButton(
            key: const Key('deleteAccount.confirm'),
            label: '确认注销',
            variant: AppButtonVariant.dangerFilled,
            onPressed: _valid ? () => Navigator.pop(context, _controller.text.trim()) : null,
          ),
        ],
      );
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/settings/delete_account_dialog_test.dart
../flutter/bin/flutter.bat analyze
```

Expected: 3 例 PASS;analyze 零告警。

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/settings/widgets/delete_account_dialog.dart \
        app/test/features/settings/delete_account_dialog_test.dart
git commit -m "feat(app): 注销第二步确认弹窗(后果清单 + 手机号校验)"
```

---

### Task 7: App 设置页接入注销入口

**Files:**
- Modify: `app/lib/features/settings/settings_page.dart`
- Test: `app/test/features/settings/settings_page_test.dart`(追加 2 例)

**Interfaces:**
- Consumes: `showConfirmDialog`(既有)、`showDeleteAccountDialog`(Task 6)、`settingsRepositoryProvider`(Task 5)、`sessionProvider.notifier.logout()`(既有唯一登出通道)、`AppToast.show(context, message)`(既有)
- Produces: key `settings.row.deleteAccount`(新增)

- [ ] **Step 1: 写失败测试**

在 `app/test/features/settings/settings_page_test.dart` 的 `main()` 内追加(import 保持不变):

```dart
  testWidgets('注销账号:两步确认 → 清空凭证回到登录页', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'DELETE /users/me': (options) => ok({}, status: 204),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('my.row.settings')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('my.row.settings')));
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('settings.row.deleteAccount')), findsOneWidget);

    // 第一步:后果说明
    await tester.tap(find.byKey(const Key('settings.row.deleteAccount')));
    await tester.pumpAndSettle();
    expect(find.text('注销账号?'), findsOneWidget);
    await tester.tap(find.text('继续'));
    await tester.pumpAndSettle();

    // 第二步:输入手机号
    await tester.enterText(find.byKey(const Key('deleteAccount.phone')), '13800138000');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('deleteAccount.confirm')));
    await tester.pumpAndSettle();

    expect(find.text('获取验证码'), findsOneWidget); // 回到登录页
    final delete = adapter.log.lastWhere((r) => r.method == 'DELETE');
    expect(delete.path, '/users/me');
    expect(delete.data, {'phone': '13800138000'});
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('auth.refresh'), isNull);

    await drainToast(tester); // 注销成功 Toast 的 2s Timer 必须推过去
  });

  testWidgets('注销失败(手机号不匹配)留在设置页', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'DELETE /users/me': (options) => jsonError(400, '手机号与当前账号不一致'),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('my.row.settings')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('my.row.settings')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('settings.row.deleteAccount')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('继续'));
    await tester.pumpAndSettle();
    await tester.enterText(find.byKey(const Key('deleteAccount.phone')), '13900139000');
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('deleteAccount.confirm')));
    await tester.pumpAndSettle();

    expect(find.text('手机号与当前账号不一致'), findsOneWidget); // 失败 Toast
    expect(find.byKey(const Key('settings.row.deleteAccount')), findsOneWidget); // 仍在设置页
    final prefs = await SharedPreferences.getInstance();
    expect(prefs.getString('auth.refresh'), 'r'); // 凭证未被清

    await drainToast(tester);
  });
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/settings/settings_page_test.dart
```

Expected: FAIL —— `find.byKey(const Key('settings.row.deleteAccount'))` 找不到。

- [ ] **Step 3: 最小实现**

改 `app/lib/features/settings/settings_page.dart`:

import 区补:

```dart
import '../../core/api_exception.dart';
import '../../core/widgets/app_toast.dart';
import 'settings_repository.dart';
import 'widgets/delete_account_dialog.dart';
```

在 `_logout` 之后新增:

```dart
  /// 注销账号:第一步后果说明 → 第二步输入手机号 → 成功即走登出通道回登录页。
  /// 不可恢复,所以两次确认缺一不可。
  Future<void> _deleteAccount(BuildContext context, WidgetRef ref) async {
    final confirmed = await showConfirmDialog(
      context,
      title: '注销账号?',
      message: '注销后,你的资料、照片、配对关系、聊天关系与广场动态将被永久删除,且无法恢复。',
      confirmLabel: '继续',
      danger: true,
    );
    if (!confirmed) return;
    if (!context.mounted) return;

    final phone = await showDeleteAccountDialog(context);
    if (phone == null) return;
    if (!context.mounted) return;

    try {
      await ref.read(settingsRepositoryProvider).deleteAccount(phone);
    } on ApiException catch (error) {
      if (!context.mounted) return;
      AppToast.show(context, error.message);
      return;
    }
    if (!context.mounted) return;
    AppToast.show(context, '账号已注销');
    await ref.read(sessionProvider.notifier).logout();
  }
```

危险区分组卡改成两行(注销在上、退出在下,与 Web 端顺序一致):

```dart
                    AppRowGroup(
                      children: [
                        AppListRow(
                          key: const Key('settings.row.deleteAccount'),
                          title: '注销账号',
                          centerTitle: true,
                          danger: true,
                          onTap: () => _deleteAccount(context, ref),
                        ),
                        AppListRow(
                          key: const Key('settings.logout'),
                          title: '退出登录',
                          centerTitle: true,
                          danger: true,
                          onTap: () => _logout(context, ref),
                        ),
                      ],
                    ),
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/settings/settings_page_test.dart
../flutter/bin/flutter.bat test
../flutter/bin/flutter.bat analyze
```

Expected: 设置页 3 例(1 既有 + 2 新增)PASS;全量 **334** 全绿(基线 329 + Task 5 的 2 + Task 6 的 3 + 本任务 2 = 336,以实际数字为准,**不得低于基线**);analyze 零告警。

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/settings/settings_page.dart \
        app/test/features/settings/settings_page_test.dart
git commit -m "feat(app): 设置页加注销账号入口(两步确认 + 失败留在本页)"
```

---

### Task 8: Web 网络层 + 会话 store

**Files:**
- Modify: `web/src/api/users.ts`
- Modify: `web/src/stores/session.ts`
- Test: `web/tests/unit/session-store.spec.ts`(追加 2 例)

**Interfaces:**
- Consumes: `web/src/api/http.ts::http`(axios 实例,支持 `delete(url, { data })`)、`web/src/api/error.ts::parseApiError`
- Produces: `usersApi.deleteAccount(phone: string) -> Promise<void>` 与 `sessionStore.deleteAccount(phone) -> Promise<void>`(只调接口,**不清会话**)—— Task 9 的设置页调用

- [ ] **Step 1: 写失败测试**

在 `web/tests/unit/session-store.spec.ts` 的 `describe` 内追加:

```ts
  it('deleteAccount 只调接口,不自己清会话(清会话由页面编排)', async () => {
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
    tokenStore.userId = 5
    server.use(
      mswHttp.delete('/api/v1/users/me', () => new HttpResponse(null, { status: 204 })),
    )
    const store = useSessionStore()

    await store.deleteAccount('13800138000')

    expect(store.status).toBe('loading') // 未被自己改掉
    expect(tokenStore.access).toBe('a')
  })

  it('deleteAccount 失败向上抛(手机号不匹配)', async () => {
    server.use(
      mswHttp.delete('/api/v1/users/me', () =>
        HttpResponse.json(
          { code: 400, message: '手机号与当前账号不一致', request_id: 'r' },
          { status: 400 },
        ),
      ),
    )

    await expect(useSessionStore().deleteAccount('13900139000')).rejects.toMatchObject({
      code: 400,
    })
  })
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd web
npx vitest run tests/unit/session-store.spec.ts
```

Expected: FAIL —— `store.deleteAccount is not a function`。

- [ ] **Step 3: 最小实现**

**(a) `web/src/api/users.ts`** —— 文件末尾追加:

```ts
/** 注销账号(不可恢复)。后端要求带上当前账号的完整手机号做二次确认。 */
export async function deleteAccount(phone: string): Promise<void> {
  await http.delete('/users/me', { data: { phone } })
}
```

**(b) `web/src/stores/session.ts`** —— import 区加 `import * as usersApi from '@/api/users'`;在 `logout` 之后新增:

```ts
  /**
   * 注销账号:**只调接口**,失败向上抛。
   * 清会话与跳转留在页面编排(与 onLogout 同一条路径:先断 IM 再清会话)。
   */
  async function deleteAccount(phone: string): Promise<void> {
    await usersApi.deleteAccount(phone)
  }
```

并把文件末尾的 `return` 改成(只多一个 `deleteAccount`):

```ts
  return { status, userId, kicked, sendCode, verify, deleteAccount, logout, restore, acknowledgeKicked }
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd web
npx vitest run tests/unit/session-store.spec.ts
npm run type-check
npm run lint
```

Expected: 2 例 PASS;类型零错误;lint 零告警。

- [ ] **Step 5: 提交**

```bash
git add web/src/api/users.ts web/src/stores/session.ts web/tests/unit/session-store.spec.ts
git commit -m "feat(web): users api 与 session store 加 deleteAccount"
```

---

### Task 9: Web `DeleteAccountDialog.vue` + 设置页接入

**Files:**
- Create: `web/src/features/settings/DeleteAccountDialog.vue`
- Modify: `web/src/features/settings/SettingsPage.vue`
- Test: `web/tests/component/settings-page.spec.ts`(追加 2 例)

**Interfaces:**
- Consumes: `components/AppButton.vue`(`variant: 'primary' | 'ghost' | 'danger'`、`disabled`、`block`、`size`)、`components/AppInput.vue`(`modelValue` / `inputmode` / `placeholder` / `error`)、`stores/session.ts::deleteAccount`(Task 8)、`stores/chat.ts::close()`、`api/error.ts::parseApiError`
- Produces: `DeleteAccountDialog.vue` props `{ open: boolean }`,emits `close` / `submitted: [string]`

**⚠️ 一处顺带视觉调整(有意为之,请复核):** 「退出登录」从 `variant="danger"` 改为 `variant="ghost"` —— 退出登录是可逆的(重新登录即可),注销不可逆,危险样式应该留给注销。既有测试只断言点击行为与文案,不涉及 variant,不会红。

- [ ] **Step 1: 写失败测试**

在 `web/tests/component/settings-page.spec.ts` 的 `describe` 内追加:

```ts
  it('注销账号:两步确认后清会话并跳登录页', async () => {
    const im = stubIm()
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
    tokenStore.userId = 9
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    server.use(mswHttp.delete('/api/v1/users/me', () => new HttpResponse(null, { status: 204 })))

    const { w, router } = await mountPage()

    await w.find('.settings__delete').trigger('click')
    await flushPromises()

    // 弹窗:先填错 → 提交按钮禁用;填对 → 可提交
    const input = w.find('.delete-dialog__input input')
    const submit = w.find('.delete-dialog__confirm')
    expect(submit.attributes('disabled')).toBeDefined()

    await input.setValue('138')
    expect(submit.attributes('disabled')).toBeDefined()

    await input.setValue('13800138000')
    expect(submit.attributes('disabled')).toBeUndefined()

    await submit.trigger('click')
    await flushPromises()

    expect(im.logout).toHaveBeenCalled()
    expect(tokenStore.access).toBeNull()
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('注销失败(后端 400)留在设置页并显示错误', async () => {
    stubIm()
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
    tokenStore.userId = 9
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    // ⚠️ support/server.ts 是 onUnhandledRequest: 'error',未铺的请求会直接抛,
    // 所以必须显式铺一条 400 的 handler,不能靠「没铺 = 失败」。
    server.use(
      mswHttp.delete('/api/v1/users/me', () =>
        HttpResponse.json(
          { code: 400, message: '手机号与当前账号不一致', request_id: 'r' },
          { status: 400 },
        ),
      ),
    )

    const { w, router } = await mountPage()
    await w.find('.settings__delete').trigger('click')
    await flushPromises()
    await w.find('.delete-dialog__input input').setValue('13900139000')
    await w.find('.delete-dialog__confirm').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/')       // 没跳登录页
    expect(tokenStore.access).toBe('a')                    // 凭证没被清
    expect(w.find('.settings__error').text()).toContain('手机号与当前账号不一致')
  })
```

`web/tests/component/settings-page.spec.ts` 顶部 import 区补两行(其余既有 import 不动):

```ts
import { HttpResponse, http as mswHttp } from 'msw'
import { server } from '../support/server'
```

(第 1 例也必须在 `mountPage()` 之前铺 `server.use(mswHttp.delete('/api/v1/users/me', () => new HttpResponse(null, { status: 204 })))` —— 同样是因为 `onUnhandledRequest: 'error'`。)

- [ ] **Step 2: 跑测试确认失败**

```bash
cd web
npx vitest run tests/component/settings-page.spec.ts
```

Expected: FAIL —— `.settings__delete` 找不到。

- [ ] **Step 3: 最小实现**

**(a) 新建 `web/src/features/settings/DeleteAccountDialog.vue`:**

```vue
<script setup lang="ts">
import { ref, watch } from 'vue'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; submitted: [string] }>()

/** 注销后会被永久删除的内容(与 App 弹窗、隐私政策 §四口径一致)。 */
const CONSEQUENCES = [
  '个人资料、标签与全部照片',
  '配对关系与聊天关系',
  '你发布的动态与评论',
  '拉黑与举报记录',
  '账号本身(手机号将被释放)',
]

const phone = ref('')
const error = ref('')

// 每次打开都从干净状态开始(与 ReportDialog 同范式)
watch(
  () => props.open,
  (open) => {
    if (open) {
      phone.value = ''
      error.value = ''
    }
  },
)

function onSubmit() {
  if (!/^\d{11}$/.test(phone.value.trim())) {
    error.value = '请输入 11 位手机号'
    return
  }
  emit('submitted', phone.value.trim())
}
</script>

<template>
  <div v-if="props.open" class="delete-dialog" role="dialog" aria-modal="true">
    <div class="delete-dialog__panel">
      <h2 class="delete-dialog__title">注销账号</h2>
      <p class="delete-dialog__desc">以下内容将被永久删除,且无法恢复:</p>
      <ul class="delete-dialog__list">
        <li v-for="item in CONSEQUENCES" :key="item">{{ item }}</li>
      </ul>

      <div class="delete-dialog__input">
        <AppInput
          v-model="phone"
          inputmode="numeric"
          placeholder="请输入当前账号的手机号"
          :error="error"
        />
      </div>

      <div class="delete-dialog__actions">
        <AppButton class="delete-dialog__cancel" variant="ghost" block @click="emit('close')">
          取消
        </AppButton>
        <AppButton
          class="delete-dialog__confirm"
          variant="danger"
          block
          :disabled="!/^\d{11}$/.test(phone.trim())"
          @click="onSubmit"
        >
          确认注销
        </AppButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.delete-dialog {
  position: fixed;
  inset: 0;
  z-index: 85;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--scrim-strong);
}
.delete-dialog__panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  width: clamp(280px, 40%, var(--form-card-max));
  padding: var(--space-xxl);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-floating-bar);
}
.delete-dialog__title {
  margin: 0;
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
}
.delete-dialog__desc {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.delete-dialog__list {
  margin: 0;
  padding-left: var(--space-lg);
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.delete-dialog__input {
  margin-top: var(--space-sm);
}
.delete-dialog__actions {
  display: flex;
  gap: var(--space-md);
}
</style>
```

**(b) 改 `web/src/features/settings/SettingsPage.vue`:**

script 区补:

```ts
import { ref } from 'vue'
import { parseApiError } from '@/api/error'
import DeleteAccountDialog from './DeleteAccountDialog.vue'

const deleteOpen = ref(false)
const deleteError = ref('')

async function onDeleteAccount() {
  if (!window.confirm('注销后,你的资料、照片、配对关系、聊天关系与广场动态将被永久删除,且无法恢复。确定继续?')) {
    return
  }
  deleteError.value = ''
  deleteOpen.value = true
}

async function onDeleteSubmitted(phone: string) {
  try {
    await session.deleteAccount(phone)
  } catch (e) {
    deleteError.value = parseApiError(e).message
    return
  }
  deleteOpen.value = false
  // 顺序与 onLogout 一致:先登出 IM,再清本地会话
  await chat.close().catch(() => {})
  session.logout()
  await router.push({ name: 'login' })
}
```

template 区把危险区改成(注销在上、退出在下):

```vue
    <AppButton
      class="settings__delete"
      variant="danger"
      block
      size="lg"
      @click="onDeleteAccount"
    >
      注销账号
    </AppButton>

    <AppButton
      class="settings__logout"
      variant="ghost"
      block
      size="lg"
      @click="onLogout"
    >
      退出登录
    </AppButton>
    <p v-if="deleteError" class="settings__error">{{ deleteError }}</p>

    <DeleteAccountDialog
      :open="deleteOpen"
      @close="deleteOpen = false"
      @submitted="onDeleteSubmitted"
    />
```

style 区补:

```css
.settings__error {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-danger);
  text-align: center;
}
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd web
npx vitest run tests/component/settings-page.spec.ts
npm run test:coverage
npm run type-check
npm run lint
```

Expected: 设置页 5 例(3 既有 + 2 新增)PASS;覆盖率门槛通过;类型零错误;lint 零告警。

- [ ] **Step 5: 提交**

```bash
git add web/src/features/settings/DeleteAccountDialog.vue \
        web/src/features/settings/SettingsPage.vue \
        web/tests/component/settings-page.spec.ts
git commit -m "feat(web): 设置页加注销账号入口(确认弹窗 + 危险区重排)"
```

---

### Task 10: 隐私政策补注销路径 + 双端版本号升 2

**Files:**
- Modify: `app/lib/features/legal/legal_texts.dart`
- Modify: `web/src/features/legal/privacy.ts`
- Modify: `web/src/features/legal/agreed.ts`
- Test: `web/tests/component/legal-page.spec.ts`(追加 1 例)

**Interfaces:**
- Consumes: 无
- Produces: `legalVersion == 2`(Dart)与 `LEGAL_VERSION == 2`(TS);隐私政策 §四新增注销路径句

**⚠️ 两份文案必须逐字一致**(`legal_texts.dart` 的 `privacyPolicyText` 与 `privacy.ts` 的 `privacyText`)。

- [ ] **Step 1: 写失败测试**

在 `web/tests/component/legal-page.spec.ts` 的 `describe` 内追加:

```ts
  it('隐私政策写明账号注销路径(商店与 App 备案材料会比对)', () => {
    const privacy = mount(LegalPage, { props: { kind: 'privacy' } })
      .find('.legal__body')
      .text()
    expect(privacy).toContain('注销账号')
    expect(privacy).toContain('永久删除')
  })
```

- [ ] **Step 2: 跑测试确认失败**

```bash
cd web
npx vitest run tests/component/legal-page.spec.ts
```

Expected: FAIL —— 隐私政策正文里没有「注销账号」。

- [ ] **Step 3: 最小实现**

**(a) `app/lib/features/legal/legal_texts.dart`** —— 版本号 1 → 2,并把 §四改成:

```dart
const int legalVersion = 2;
```

```dart
四、你的权利
你可以在「我的」中查看和修改资料、删除照片,在「设置-黑名单」中管理拉黑关系,也可以退出登录终止使用。你也可以随时在「设置-注销账号」中注销账号:注销后你的资料、照片、配对关系、聊天关系、广场动态、拉黑与举报记录将被永久删除且无法恢复,手机号将被释放;该操作需要输入当前账号的手机号二次确认,重封禁账号需联系客服处理。
```

**(b) `web/src/features/legal/privacy.ts`** —— 把 §四那一行改成**与上面逐字相同**的文本:

```ts
四、你的权利
你可以在「我的」中查看和修改资料、删除照片,在「设置-黑名单」中管理拉黑关系,也可以退出登录终止使用。你也可以随时在「设置-注销账号」中注销账号:注销后你的资料、照片、配对关系、聊天关系、广场动态、拉黑与举报记录将被永久删除且无法恢复,手机号将被释放;该操作需要输入当前账号的手机号二次确认,重封禁账号需联系客服处理。
```

**(c) `web/src/features/legal/agreed.ts`** —— `LEGAL_VERSION` 1 → 2:

```ts
export const LEGAL_VERSION = 2
```

- [ ] **Step 4: 跑测试确认通过**

```bash
cd web
npx vitest run tests/component/legal-page.spec.ts tests/component/legal-gate.spec.ts
npm run test:coverage
cd ../app
../flutter/bin/flutter.bat test test/features/legal
../flutter/bin/flutter.bat test
../flutter/bin/flutter.bat analyze
```

Expected: Web legal 用例全绿(含升版后重弹的那条,它用 `LEGAL_VERSION - 1` 所以自适应);App legal 用例全绿(harness 用 `legalVersion` 动态铺 prefs);analyze 零告警。

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/legal/legal_texts.dart web/src/features/legal/privacy.ts \
        web/src/features/legal/agreed.ts web/tests/component/legal-page.spec.ts
git commit -m "docs(legal): 隐私政策补账号注销路径,双端协议版本升 2"
```

---

### Task 11: 文档收尾 + 全量回归

**Files:**
- Modify: `docs/pitfalls/backend.md`(新增「注销」一节)
- Modify: `CLAUDE.md`(接口表 + 里程碑 + IM 纪律例外)
- Test: 无新增代码测试;跑全量回归

**Interfaces:**
- Consumes: 前 10 个任务的全部产物
- Produces: 可交付的文档状态

- [ ] **Step 1: 踩坑册补「注销」一节**

在 `docs/pitfalls/backend.md` 末尾追加(标题层级照该文件既有风格):

```markdown
## 账号注销

- **`user.delete()` 之后 `user.id` 会变成 `None`** —— Django 的 Collector 会把被删实例的主键置空。所有要在 `transaction.on_commit` 里用到的值(`user_id`、`user.im_user_id`)必须在 `delete()` **之前**取好,否则会拼出 `uNone`,而且不报错、静默错。
- **`on_commit` 回调在 `APITestCase` 里默认不执行**(整个用例包在事务里且最终回滚)。要测副作用必须 `with self.captureOnCommitCallbacks(execute=True):` 包住请求。
- **IM 删号任务的参数是 `im_user_id` 而不是 `user_id`** —— 全项目唯一一处例外。原因:该任务在用户行删除**之后**入队,任务内查库必然拿到 `None`,沿用 `_user()` 兜底会静默跳过、删号永不发生。`im/tasks.py::delete_account` 的 docstring 有完整说明。
- **重封禁用户的注销天然被 403 挡住** —— `moderation/permissions.py::BAN_EXEMPT` 白名单只含 `("GET", "/api/v1/users/me")` 与 `("GET", "/api/v1/users/tags")`,`DELETE` 不在内。这是「防注销洗白」的屏障,**不要**为了「让被封禁的人也能注销」把 DELETE 加进白名单。
- **`feed.PostReport` 是 `post=SET_NULL`**:注销用户时,「别人举报他动态」的那些举报行会保留(`post` 置 NULL,运营留档),而「他举报别人」的行随 `reporter` 级联删除。这是既有模型行为,不是 bug。
- **给 `@api_view` 加方法会让文档门禁立刻变红** —— `ApiDocsCoverageTests` 双向比对 URLconf 与 `docs/api/*.md` 的信息行,新增 `DELETE /api/v1/users/me` 必须在同一次改动内写进 `docs/api/users.md`。
```

- [ ] **Step 2: CLAUDE.md 三处更新**

**(a)** 「后端接口」表格里,`GET/PATCH /users/me` 那一行改成:

```markdown
| `GET/PATCH/DELETE /users/me` | 我的资料(昵称/性别/生日/城市/简介/`tag_ids`);未满 18 岁 400;`id`=profile 主键。**DELETE = 注销账号**(body 带 `phone` 二次确认,立即硬删除全部数据 + 释放手机号;重封禁 403) |
```

**(b)** 「核心契约与纪律」里 `IM 副作用唯一入口 im/tasks.py` 那条,句尾补:

```markdown
(唯一例外:`im/tasks.py::delete_account` 的参数是 `im_user_id` 字符串 —— 它在用户行删除后入队,任务内查库必然拿到 `None`,详见 `docs/pitfalls/backend.md`「账号注销」)
```

**(c)** 「里程碑」表末尾追加一行:

```markdown
| 2026-10-13 | 上线合规轨 T-17「账号注销入口」交付(`DELETE /users/me` 手机号二次确认 + 立即硬删除 + IM 删号;App/Web 双端入口;隐私政策补注销路径并升版 2) |
```

并把该节末尾的「**下一步**」改成:

```markdown
**下一步**:上线合规轨继续推进 —— 按 `2026-09-18-launch-execution.md` 走 S0/S1(主体与备案由用户线下办理,Claude 侧可执行项:T-06 软著材料、T-10 隐私政策页部署、T-12 安全评估报告、T-18 备份策略、T-19 PIPIA/未成年人保护方案)。
```

- [ ] **Step 3: 后端全量回归**

```bash
cd chatapp
python manage.py test
```

Expected: 全绿(基线 337 + 本批新增 ≈ 20,含 `ApiDocsCoverageTests`)。

- [ ] **Step 4: App 全量回归**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

Expected: analyze 零告警;测试全绿且数量 > 329。

- [ ] **Step 5: Web 全量回归**

```bash
cd web
npm run type-check
npm run lint
npm run test:coverage
```

Expected: 类型零错误;lint 零告警;覆盖率门槛(70/60/70/70)通过。

- [ ] **Step 6: 提交**

```bash
git add docs/pitfalls/backend.md CLAUDE.md
git commit -m "docs: 注销踩坑册分节 + CLAUDE.md 接口/纪律/里程碑同步"
```

---

## 手测清单(交用户,模拟器 release 包)

1. **正常注销**:设置 → 注销账号 → 第一步后果说明(点「取消」应无任何请求)→ 点「继续」→ 输错手机号(确认按钮禁用)→ 输对 → 确认 → Toast「账号已注销」→ 回登录页。
2. **注销后同号重新登录** = 全新账号(要重新走引导页),「我的」页 ID 与注销前不同。
3. **重封禁账号**:注销入口点击后收到「账号已被封禁,如有疑问请联系客服」,账号仍在。
4. **数据确实没了**:注销前记下自己发的动态 ID,注销后在广场/我的动态里查不到;另一个账号看你已不存在(配对列表少一条)。
5. **Web 端同流程**:设置页「注销账号」→ 浏览器 confirm → 弹窗输手机号 → 回登录页。
6. **协议升版**:App 与 Web 下次启动各重弹一次协议弹窗,隐私政策 §四能看到注销路径描述。
7. **聊天关系**:注销后,对方在 IM 会话里给你发消息应失败(IM 账号已删);对方本机历史消息仍在(预期)。

---

## 执行记录

(执行时回填:各任务提交号、测试数量、手测结果、实测发现。)
