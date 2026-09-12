# 接口标准化 第 2 期(全后端对齐:IM 任务迁移 / request_id / 限流 / 分页) 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把剩下的 IM 副作用(配对灰条 / 封禁通知 / 黑名单 / 昵称头像同步)全部从后台线程迁到 Celery 任务;补上 request_id 请求追踪与请求日志、限流维度、`/matches` 与 `/blocks` 统一分页。

**Architecture:** `im/tasks.py` 成为唯一 IM 副作用入口(带重试);discovery/moderation/users 三个域删除 `threading` 辅助函数,一律 `transaction.on_commit(fn, robust=True)` 入队;HTTP 侧新增 `RequestIdMiddleware`(contextvar + 日志 Filter,经 Celery header 传递到 worker);列表接口改用 DRF `LimitOffsetPagination`,前端 repository 跟 `next` 拉全量。

**Tech Stack:** Django 5.2 + DRF + MySQL + Redis/Celery(第 1 期已就位);Flutter 3.47.2(**仅改 core/im/moderation 三个 lib 文件 + 测试**)。

**Spec:** `docs/superpowers/specs/2026-09-12-backend-standardization-design.md` §6(通用接口规范)、§9 第 3 步。第 1 期已完成 §4/§5/§6 错误码/§7(计划: `plans/2026-09-12-backend-standardization.md`)。

**期次边界:** spec §9 第 4 步(gunicorn/nginx/systemd 部署形态、`/healthz`/`/readyz`、部署文档)与第 5 步的收尾**不在本计划**;本计划 = CLAUDE.md 所述「第 2 期:其余 IM 任务迁移 / request_id / 请求日志 / 限流维度 / 分页」。fakeredis 测试基建按 spec §8 回退方案**不引入**(第 1 期已用真 Redis DB15,工作良好)。

## Global Constraints

- 后端 cwd = `chatapp/`,`python` 即 anaconda `Django` 环境(3.10);前端 cwd = `app/`,命令一律 `../flutter/bin/flutter.bat`,`flutter analyze` 必须零告警
- **跑后端测试前置**:Redis 在跑(`docker compose -f docker-compose.dev.yml up -d`);测试自动用 Redis DB15(缓存)/DB14(broker)
- **测试里任务永不真执行**:断「入队了什么」用 `patch("im.tasks.<任务名>.delay")`;测任务体直接 `.run(...)`(此时 mock `im.client.*`,腾讯 REST 一次都不能真打)
- ⚠️ **`TestCase`/`APITestCase` 内 `on_commit` 回调不会执行**:凡断言入队的用例必须 `with self.captureOnCommitCallbacks(execute=True):` 包住请求(否则断言恒 0 次)
- `im/client.py` 对外**永不抛异常**;让 Celery 重试生效是 `im/tasks.py` 的职责(False → 抛异常)
- **响应路径禁止外部调用**:view 里不得出现 `requests` / 直调 `im.client.*`;跨系统副作用一律经 tasks + `on_commit(robust=True)`
- 提交信息用中文,沿用现有风格(`feat(chatapp):` / `refactor(chatapp):` / `docs:`);每步全绿再进下一步
- **不动 `flutter/`**(SDK 源码);本计划**无数据库迁移**;管理命令(`seed_fake_users` / `im_sync_nicknames` / `im_setup_system_account`)是运维工具,保持同步直调,**不改**

---

### Task 1: `im/tasks.py` 补齐副作用任务(配对灰条/封禁通知/黑名单/资料同步)

**Files:**
- Modify: `chatapp/im/tasks.py`(追加 6 个任务 + `_user` 辅助)
- Modify: `chatapp/im/client.py`(仅更新顶部 docstring:任务队列已落地)
- Modify: `chatapp/config/settings.py`(加 `MEDIA_BASE_URL`)
- Test: `chatapp/im/tests.py`(追加 `ImSideEffectTaskTests`)

**Interfaces:**
- Produces(后续任务全部依赖,参数一律 **user_id** 不是 im 标识符):
  - `im.tasks.send_match_notice(user_a_id: int, user_b_id: int)`
  - `im.tasks.blacklist_add(owner_id: int, other_id: int)`
  - `im.tasks.blacklist_remove(owner_id: int, other_id: int)`
  - `im.tasks.ban_notice(user_id: int, level: str, reason: str = "")`(heavy 时任务内**先发通知再踢**)
  - `im.tasks.ban_lifted(user_id: int)`
  - `im.tasks.sync_profile(user_id: int, kind: str)`(kind ∈ `"nick"` / `"avatar"`)
- Consumes: 现有 `RETRY_POLICY`、`_require`、`im/client.py` 的 REST 封装

- [ ] **Step 1: 写失败测试**(`chatapp/im/tests.py`:import 区先改成)

```python
from users.models import Photo, PhotoStatus, Profile, ProfileStatus

from .client import (_request, black_list_add, black_list_delete, ensure_account,
                     import_account, kick_user, send_ban_lifted, send_ban_notice,
                     send_custom_elem, send_match_notice, send_text, set_profile_avatar,
                     set_profile_nick)
from .signature import _hmac_sha256, decode_user_sig, gen_user_sig
from .tasks import (ban_lifted, ban_notice, blacklist_add, blacklist_remove,
                    import_account as import_account_task, kick_pending,
                    kick_pending_key, sync_profile)
from .tasks import send_match_notice as send_match_notice_task
```

文件末尾追加:

```python
class ImSideEffectTaskTests(TestCase):
    """第 2 期:配对灰条 / 封禁通知 / 黑名单 / 资料同步的任务体。"""

    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.b, nickname="小红")

    def test_send_match_notice_task(self):
        with patch("im.client.send_match_notice", return_value=True) as send:
            send_match_notice_task.run(self.a.id, self.b.id)
        send.assert_called_once_with(self.a.im_user_id, self.b.im_user_id)

    def test_blacklist_add_and_remove(self):
        with patch("im.client.black_list_add", return_value=True) as add:
            blacklist_add.run(self.a.id, self.b.id)
        add.assert_called_once_with(self.a.im_user_id, self.b.im_user_id)
        with patch("im.client.black_list_delete", return_value=True) as delete:
            blacklist_remove.run(self.a.id, self.b.id)
        delete.assert_called_once_with(self.a.im_user_id, self.b.im_user_id)

    def test_ban_notice_light_only_sends(self):
        with patch("im.client.send_ban_notice", return_value=True) as send, \
                patch("im.client.kick_user") as kick:
            ban_notice.run(self.b.id, "light", "骚扰他人")
        send.assert_called_once_with(self.b.im_user_id, "light", "骚扰他人")
        kick.assert_not_called()

    def test_ban_notice_heavy_sends_then_kicks(self):
        calls = []
        with patch("im.client.send_ban_notice",
                   side_effect=lambda *a: calls.append("send") or True), \
                patch("im.client.kick_user",
                      side_effect=lambda *a: calls.append("kick") or True):
            ban_notice.run(self.b.id, "heavy", "严重违规")
        self.assertEqual(calls, ["send", "kick"])   # 顺序不能反:先说明原因再断线

    def test_ban_notice_failure_raises_so_celery_retries(self):
        with patch("im.client.send_ban_notice", return_value=False):
            with self.assertRaises(RuntimeError):
                ban_notice.run(self.b.id, "light", "骚扰他人")

    def test_ban_lifted_task(self):
        with patch("im.client.send_ban_lifted", return_value=True) as send:
            ban_lifted.run(self.b.id)
        send.assert_called_once_with(self.b.im_user_id)

    def test_sync_profile_nick(self):
        with patch("im.client.set_profile_nick", return_value=True) as sync:
            sync_profile.run(self.b.id, "nick")
        sync.assert_called_once_with(self.b.im_user_id, "小红")

    @override_settings(MEDIA_BASE_URL="http://cdn.test")
    def test_sync_profile_avatar_uses_absolute_url(self):
        Photo.objects.create(user=self.b, file="photos/a.png", status=PhotoStatus.APPROVED)
        with patch("im.client.set_profile_avatar", return_value=True) as sync:
            sync_profile.run(self.b.id, "avatar")
        sync.assert_called_once_with(self.b.im_user_id, "http://cdn.test/media/photos/a.png")

    def test_sync_profile_avatar_without_approved_photo_is_noop(self):
        with patch("im.client.set_profile_avatar") as sync:
            sync_profile.run(self.b.id, "avatar")
        sync.assert_not_called()

    def test_missing_user_is_noop(self):
        send_match_notice_task.run(self.a.id, 999999)   # 不抛异常
        sync_profile.run(999999, "nick")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test im.tests.ImSideEffectTaskTests`
Expected: FAIL — `ImportError: cannot import name 'ban_notice' from 'im.tasks'`

- [ ] **Step 3: 实现**

`chatapp/config/settings.py` 的照片配置块附近追加:

```python
# IM 头像同步用:任务里没有 request,拿不到绝对 URL,配域名前缀(生产改成正式域名/CDN)
MEDIA_BASE_URL = os.getenv("MEDIA_BASE_URL", "http://127.0.0.1:8000")
```

`chatapp/im/client.py` 顶部 docstring 改为:

```python
"""腾讯云 IM REST 客户端。

约定:业务函数对外**永不抛异常**,失败只记日志并返回 False —— IM 抖动不应该拖垮主流程。
跨系统副作用统一经 im/tasks.py 的 Celery 任务调用(带重试);这里保持纯 REST 封装。
"""
```

`chatapp/im/tasks.py` 追加(顶部 import 加 `from django.conf import settings` 与 `from users.models import PhotoStatus`):

```python
def _user(user_id: int):
    return get_user_model().objects.filter(id=user_id).first()


@shared_task(**RETRY_POLICY)
def send_match_notice(user_a_id: int, user_b_id: int) -> None:
    a, b = _user(user_a_id), _user(user_b_id)
    if a is None or b is None:
        return
    _require(im_client.send_match_notice(a.im_user_id, b.im_user_id), "send_match_notice")


@shared_task(**RETRY_POLICY)
def blacklist_add(owner_id: int, other_id: int) -> None:
    owner, other = _user(owner_id), _user(other_id)
    if owner is None or other is None:
        return
    _require(im_client.black_list_add(owner.im_user_id, other.im_user_id), "black_list_add")


@shared_task(**RETRY_POLICY)
def blacklist_remove(owner_id: int, other_id: int) -> None:
    owner, other = _user(owner_id), _user(other_id)
    if owner is None or other is None:
        return
    _require(im_client.black_list_delete(owner.im_user_id, other.im_user_id), "black_list_delete")


@shared_task(**RETRY_POLICY)
def ban_notice(user_id: int, level: str, reason: str = "") -> None:
    """封禁说明;heavy 先发消息再踢下线(同一任务内串行,顺序不被多 worker 打乱)。"""
    user = _user(user_id)
    if user is None:
        return
    sent = im_client.send_ban_notice(user.im_user_id, level, reason)
    kicked = True
    if level == "heavy":
        kicked = im_client.kick_user(user.im_user_id)
    _require(sent and kicked, "ban_notice")


@shared_task(**RETRY_POLICY)
def ban_lifted(user_id: int) -> None:
    user = _user(user_id)
    if user is None:
        return
    _require(im_client.send_ban_lifted(user.im_user_id), "ban_lifted")


@shared_task(**RETRY_POLICY)
def sync_profile(user_id: int, kind: str) -> None:
    """把资料同步到 IM(kind: nick|avatar);没有可同步的值时静默跳过。"""
    user = _user(user_id)
    if user is None:
        return
    profile = getattr(user, "profile", None)
    if profile is None:
        return
    if kind == "nick":
        if not profile.nickname:
            return
        _require(im_client.set_profile_nick(user.im_user_id, profile.nickname), "sync_profile:nick")
    elif kind == "avatar":
        photo = user.photos.filter(status=PhotoStatus.APPROVED).first()
        if photo is None:
            return
        url = f"{settings.MEDIA_BASE_URL.rstrip('/')}{photo.file.url}"
        _require(im_client.set_profile_avatar(user.im_user_id, url), "sync_profile:avatar")
    else:
        raise ValueError(f"未知的资料同步类型 kind={kind}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test im`
Expected: PASS(新增 10 个用例 + 原有全绿)

- [ ] **Step 5: Commit**

```bash
git add chatapp/im/tasks.py chatapp/im/client.py chatapp/im/tests.py chatapp/config/settings.py
git commit -m "feat(chatapp): im/tasks 补齐副作用任务(配对灰条/封禁通知/黑名单/资料同步)"
```

---

### Task 2: discovery 迁移 — 配对灰条改走任务队列

**Files:**
- Modify: `chatapp/discovery/services.py`(删 `_notify_async`,改 `notify_match` 入队)
- Test: `chatapp/discovery/tests.py`(改 patch 点,删线程测试类)

**Interfaces:**
- Consumes: Task 1 的 `im.tasks.send_match_notice(user_a_id, user_b_id)`
- Produces: `discovery.services.notify_match(match)` 签名不变(内部改入队)

- [ ] **Step 1: 改测试(先红)**

`chatapp/discovery/tests.py`:

1. 删除整类 `MatchNoticeDispatchTests`(测后台线程的,机制已不存在);顶部 `import threading` 同时删(确认无其他使用)。
2. `SwipeApiTests` 三个用例改写:

```python
    def test_mutual_like_creates_one_match(self):
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        with patch("im.tasks.send_match_notice.delay") as notice:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.swipe(self.target.id)
        self.assertEqual(resp.json(), {"matched": True})
        self.assertEqual(Match.objects.count(), 1)
        self.assertEqual(Match.objects.first().user_a, self.me)
        notice.assert_called_once_with(self.me.id, self.target.id)

    def test_mutual_like_after_match_does_not_resend_notice(self):
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        with patch("im.tasks.send_match_notice.delay") as notice:
            with self.captureOnCommitCallbacks(execute=True):
                self.swipe(self.target.id)
                again = self.swipe(self.target.id)
        self.assertEqual(again.json(), {"matched": True})
        self.assertEqual(notice.call_count, 1)

    def test_enqueue_failure_does_not_break_swipe(self):
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        with patch("im.tasks.send_match_notice.delay", side_effect=Exception("broker down")):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.swipe(self.target.id)
        self.assertEqual(resp.status_code, 200)   # robust=True 兜住,配对结果不受影响
        self.assertEqual(resp.json(), {"matched": True})
```

3. 若 `from . import services as discovery_services` / `cache` 等 import 不再被使用,一并删除(grep 确认后)。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test discovery`
Expected: FAIL — `test_mutual_like_creates_one_match` 的 `notice.assert_called_once_with` 失败(旧代码没入队)

- [ ] **Step 3: 实现**

`chatapp/discovery/services.py` 全文替换为:

```python
from django.db import transaction

from im import tasks as im_tasks


def notify_match(match):
    """配对成功后给双方各发一条 IM 灰条消息(经任务队列,失败可重试)。

    on_commit:配对真正落库后才入队;robust=True:broker 抖动不影响配对结果。
    """
    a_id, b_id = match.user_a_id, match.user_b_id
    transaction.on_commit(lambda: im_tasks.send_match_notice.delay(a_id, b_id), robust=True)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test discovery`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chatapp/discovery/services.py chatapp/discovery/tests.py
git commit -m "refactor(chatapp): 配对灰条改走任务队列(删 discovery 后台线程)"
```

---

### Task 3: moderation 迁移 — 封禁通知与黑名单同步改走任务队列

**Files:**
- Modify: `chatapp/moderation/services.py`(删 `_dispatch_async`/`_send_notice_then_kick`,改入队)
- Test: `chatapp/moderation/tests.py`、`chatapp/ops/tests.py`

**Interfaces:**
- Consumes: Task 1 的 `im.tasks.ban_notice / ban_lifted / blacklist_add / blacklist_remove`
- Produces: `log_ban_change(user, old_status, new_status, reason, operator)`、`sync_im_blacklist(blocker, blocked, *, add)` 签名不变

- [ ] **Step 1: 改测试(先红)**

`chatapp/moderation/tests.py`:

1. import 改:`from .services import log_ban_change`(去掉 `_send_notice_then_kick`);`from im import client as im_client` 若不再使用则删(grep 确认)。
2. `BanAuditServiceTests` 四个用例改写(并**删除** `test_send_notice_then_kick_sends_before_kick` —— 顺序语义已移到 `im/tests.py::ImSideEffectTaskTests::test_ban_notice_heavy_sends_then_kicks`):

```python
    def test_heavy_ban_enqueues_notice(self):
        with patch("im.tasks.ban_notice.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                log_ban_change(self.target, ProfileStatus.COMPLETE, ProfileStatus.BANNED_HEAVY,
                               "骚扰他人", self.operator)
        log = BanLog.objects.get(user=self.target)
        self.assertEqual(log.action, BanAction.BAN_HEAVY)
        self.assertEqual(log.reason, "骚扰他人")
        self.assertEqual(log.operator, self.operator)
        delay.assert_called_once_with(self.target.id, "heavy", "骚扰他人")

    def test_light_ban_enqueues_notice_without_kick(self):
        with patch("im.tasks.ban_notice.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                log_ban_change(self.target, ProfileStatus.COMPLETE, ProfileStatus.BANNED_LIGHT,
                               "轻度违规", self.operator)
        self.assertEqual(BanLog.objects.get(user=self.target).action, BanAction.BAN_LIGHT)
        delay.assert_called_once_with(self.target.id, "light", "轻度违规")

    def test_unban_enqueues_lifted_notice(self):
        with patch("im.tasks.ban_lifted.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                log_ban_change(self.target, ProfileStatus.BANNED_HEAVY, ProfileStatus.COMPLETE,
                               "申诉通过", self.operator)
        self.assertEqual(BanLog.objects.get(user=self.target).action, BanAction.UNBAN)
        delay.assert_called_once_with(self.target.id)

    def test_non_ban_transition_writes_nothing(self):
        with patch("im.tasks.ban_notice.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                log_ban_change(self.target, ProfileStatus.INCOMPLETE, ProfileStatus.COMPLETE,
                               "", self.operator)
        self.assertFalse(BanLog.objects.exists())
        delay.assert_not_called()
```

3. `ProfileAdminHookTests._save` 里的 `with patch("moderation.services._dispatch_async"):` 改为:

```python
        with patch("im.tasks.ban_notice.delay"), patch("im.tasks.ban_lifted.delay"):
            model_admin.save_model(request, obj, form=None, change=True)
```

4. `BlockApiTests` 四个用例改写:

```python
    def test_block_creates_row_and_syncs_im(self):
        with patch("im.tasks.blacklist_add.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(self.URL, {"target_user_id": self.target.id}, format="json")
        self.assertEqual(resp.status_code, 201)
        self.assertTrue(Block.objects.filter(blocker=self.me, blocked=self.target).exists())
        delay.assert_called_once_with(self.me.id, self.target.id)

    def test_duplicate_block_idempotent_without_resync(self):
        Block.objects.create(blocker=self.me, blocked=self.target)
        with patch("im.tasks.blacklist_add.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(self.URL, {"target_user_id": self.target.id}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Block.objects.count(), 1)
        delay.assert_not_called()

    def test_unblock_removes_and_syncs_im(self):
        Block.objects.create(blocker=self.me, blocked=self.target)
        with patch("im.tasks.blacklist_remove.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.delete(f"{self.URL}/{self.target.id}")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Block.objects.exists())
        delay.assert_called_once_with(self.me.id, self.target.id)

    def test_unblock_missing_is_idempotent(self):
        with patch("im.tasks.blacklist_remove.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.delete(f"{self.URL}/{self.target.id}")
        self.assertEqual(resp.status_code, 204)
        delay.assert_not_called()
```

`chatapp/ops/tests.py`:

1. import 去掉 `from im import client as im_client`、`from moderation.services import _send_notice_then_kick`(确认无其他使用后删)。
2. `OpsReportTests` 两个用例改写:

```python
    def test_quick_ban_heavy_bans_and_handles(self):
        with patch("im.tasks.ban_notice.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/ops/reports/{self.report.id}/ban",
                                        {"level": "ban_heavy", "reason": "色情图片"})
        self.assertContains(resp, "已处理")
        profile = Profile.objects.get(user=self.target)
        self.assertEqual(profile.status, ProfileStatus.BANNED_HEAVY)
        self.assertEqual(profile.ban_reason, "色情图片")
        self.assertTrue(BanLog.objects.filter(user=self.target, action=BanAction.BAN_HEAVY,
                                              operator=self.staff).exists())
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ReportStatus.HANDLED)
        self.assertEqual(self.report.handled_note, "封禁处理")
        delay.assert_called_once_with(self.target.id, "heavy", "色情图片")

    def test_quick_ban_requires_reason(self):
        with patch("im.tasks.ban_notice.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/ops/reports/{self.report.id}/ban",
                                        {"level": "ban_light", "reason": ""})
        self.assertContains(resp, "必须填写原因")
        profile = Profile.objects.get(user=self.target)
        self.assertEqual(profile.status, ProfileStatus.COMPLETE)
        self.report.refresh_from_db()
        self.assertEqual(self.report.status, ReportStatus.PENDING)
        delay.assert_not_called()
```

3. `OpsUserBanTests` 四个用例改写:

```python
    def test_ban_light_dispatches_notice_no_kick(self):
        with patch("im.tasks.ban_notice.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/ops/users/{self.user.id}/ban",
                                        {"action": "ban_light", "reason": "骚扰他人"})
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.BANNED_LIGHT)
        self.assertEqual(self.profile.ban_reason, "骚扰他人")
        self.assertTrue(BanLog.objects.filter(user=self.user, action=BanAction.BAN_LIGHT,
                                              operator=self.staff).exists())
        delay.assert_called_once_with(self.user.id, "light", "骚扰他人")

    def test_ban_heavy_kicks_im(self):
        with patch("im.tasks.ban_notice.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(f"/ops/users/{self.user.id}/ban",
                                 {"action": "ban_heavy", "reason": "严重违规"})
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.BANNED_HEAVY)
        delay.assert_called_once_with(self.user.id, "heavy", "严重违规")

    def test_ban_requires_reason(self):
        with patch("im.tasks.ban_notice.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/ops/users/{self.user.id}/ban",
                                        {"action": "ban_heavy", "reason": "  "})
        self.assertContains(resp, "必须填写原因")
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.COMPLETE)
        delay.assert_not_called()

    def test_unban_recomputes_status_and_clears_reason(self):
        with patch("im.tasks.ban_notice.delay"), patch("im.tasks.ban_lifted.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                self.client.post(f"/ops/users/{self.user.id}/ban",
                                 {"action": "ban_light", "reason": "先封"})
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.post(f"/ops/users/{self.user.id}/ban",
                                        {"action": "unban", "reason": ""})
        self.assertEqual(resp.status_code, 200)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.status, ProfileStatus.COMPLETE)   # 资料齐全+有照片 → 重算回已完善
        self.assertEqual(self.profile.ban_reason, "")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test moderation ops`
Expected: FAIL — 多处 `assert_called_once_with` 不匹配(旧代码 dispatch 的是 im_client 函数)

- [ ] **Step 3: 实现**

`chatapp/moderation/services.py` 全文替换为:

```python
import logging

from django.db import transaction

from im import tasks as im_tasks
from users.models import Profile, ProfileStatus

from .models import BanAction, BanLog, Block

logger = logging.getLogger(__name__)


def blocked_user_ids(user) -> set[int]:
    """与我有拉黑关系的人(我拉黑的 ∪ 拉黑我的);候选/配对/资料卡统一用它。"""
    made = Block.objects.filter(blocker=user).values_list("blocked_id", flat=True)
    received = Block.objects.filter(blocked=user).values_list("blocker_id", flat=True)
    return set(made) | set(received)


def log_ban_change(user, old_status, new_status, reason, operator) -> None:
    """admin 保存 Profile / ops 封禁时调用:状态跨封禁边界就写审计 + 发系统通知。

    通知与踢下线经任务队列(ban_notice 任务内保证 heavy 先发后踢);响应路径不等腾讯。
    """
    if new_status == old_status:
        return
    if new_status == ProfileStatus.BANNED_LIGHT:
        _write_log(user, BanAction.BAN_LIGHT, reason, operator)
        _enqueue(im_tasks.ban_notice, user.id, "light", reason or "")
    elif new_status == ProfileStatus.BANNED_HEAVY:
        _write_log(user, BanAction.BAN_HEAVY, reason, operator)
        _enqueue(im_tasks.ban_notice, user.id, "heavy", reason or "")
    elif old_status in Profile.BANNED_STATUSES:
        _write_log(user, BanAction.UNBAN, reason, operator)
        _enqueue(im_tasks.ban_lifted, user.id)


def sync_im_blacklist(blocker, blocked, *, add: bool) -> None:
    """拉黑/解除后同步 IM 黑名单(经任务队列;UI 侧还有双向不可见兜底)。"""
    task = im_tasks.blacklist_add if add else im_tasks.blacklist_remove
    _enqueue(task, blocker.id, blocked.id)


def _write_log(user, action, reason, operator) -> None:
    try:
        BanLog.objects.create(user=user, action=action, reason=reason or "", operator=operator)
    except Exception:
        # 审计写失败不该炸掉运营的保存动作(Profile 已经保存过了)
        logger.exception("写 BanLog 失败 user=%s action=%s", user.pk, action)


def _enqueue(task, *args) -> None:
    """入队统一走 on_commit(robust=True):在事务里等提交,不在事务里立即入队(很快)。"""
    transaction.on_commit(lambda: task.delay(*args), robust=True)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test moderation ops`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chatapp/moderation/services.py chatapp/moderation/tests.py chatapp/ops/tests.py
git commit -m "refactor(chatapp): 封禁通知与黑名单同步改走任务队列(删 moderation 后台线程)"
```

---

### Task 4: users 迁移 — 昵称同步走任务 + 照片过审同步 IM 头像

**Files:**
- Modify: `chatapp/users/services.py`(删 `_dispatch_async`;`sync_im_nickname` 入队;新增 `sync_im_avatar`;`review_photos` 过审时入队头像同步)
- Modify: `chatapp/users/views.py`(`upload_photo` 自动过审也入队)
- Test: `chatapp/users/tests.py`

**Interfaces:**
- Consumes: Task 1 的 `im.tasks.sync_profile(user_id, kind)`
- Produces: `users.services.sync_im_nickname(user)`(签名不变)、新增 `users.services.sync_im_avatar(user_id)`

- [ ] **Step 1: 改测试(先红)**

`chatapp/users/tests.py`:

1. `ProfileUpdateTests` 五处 `@patch("users.services._dispatch_async")` 替换:

```python
    @patch("im.tasks.sync_profile.delay")
    def test_update_fields(self, delay):
        tag = Tag.objects.first()
        resp = self.client.patch(self.url, {**self._full_profile(), "tag_ids": [tag.id]}, format="json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["nickname"], "小明")
        self.assertEqual(data["age"], calculate_age(date(2000, 1, 1)))
        self.assertEqual([t["id"] for t in data["tags"]], [tag.id])
        self.assertEqual(data["status"], "incomplete")   # 还差照片

    @patch("im.tasks.sync_profile.delay")
    def test_partial_update_keeps_other_fields(self, delay):   # 断言体不变
        ...

    @patch("im.tasks.sync_profile.delay")
    def test_patch_nickname_triggers_im_sync(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.patch(self.url, {"nickname": "新名字"}, format="json")
        self.assertEqual(resp.status_code, 200)
        delay.assert_called_once_with(self.user.id, "nick")

    @patch("im.tasks.sync_profile.delay")
    def test_patch_same_nickname_no_sync(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(self.url, {"nickname": "小明"}, format="json")
            self.client.patch(self.url, {"nickname": "小明"}, format="json")
        self.assertEqual(delay.call_count, 1)   # 只有第一次实际变化时同步

    @patch("im.tasks.sync_profile.delay")
    def test_patch_other_field_no_sync(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(self.url, {"city": "杭州"}, format="json")
        delay.assert_not_called()
```

2. `PhotoTests.fill_profile` 里的 `with patch("users.services._dispatch_async"):` 改为 `with patch("im.tasks.sync_profile.delay"):`。
3. `PhotoTests` 新增一个用例:

```python
    @patch("im.tasks.sync_profile.delay")
    def test_upload_approved_photo_syncs_im_avatar(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.upload()
        self.assertEqual(resp.status_code, 201)
        delay.assert_called_once_with(self.user.id, "avatar")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test users`
Expected: FAIL — `AttributeError: <module 'users.services'> does not have the attribute '_dispatch_async'`

- [ ] **Step 3: 实现**

`chatapp/users/services.py` 全文替换为:

```python
from django.db import transaction
from django.utils import timezone

from im import tasks as im_tasks

from .models import PhotoStatus, Preference, Profile


def get_profile(user):
    """取当前用户资料;没有就建空 Profile + 空 Preference(资料是懒创建的)。"""
    profile, _ = Profile.objects.get_or_create(user=user)
    Preference.objects.get_or_create(profile=profile)
    return profile


def review_photos(queryset, status, operator=None) -> int:
    """通过/驳回照片:落审核审计 + 重算资料完善状态;过审时把头像同步到 IM。admin 与 ops 共用。"""
    user_ids = set(queryset.values_list("user_id", flat=True))
    count = queryset.update(status=status, reviewed_by=operator, reviewed_at=timezone.now())
    # 照片数量变化会影响「资料完善」判定(掉回未完善 = 失去候选资格),必须重算
    for profile in Profile.objects.filter(user_id__in=user_ids):
        profile.refresh_status()
    if status == PhotoStatus.APPROVED:
        for user_id in user_ids:
            sync_im_avatar(user_id)
    return count


def sync_im_nickname(user) -> None:
    """昵称变更后同步到 IM 资料(经任务队列;失败可重试,不影响业务)。"""
    nickname = getattr(getattr(user, "profile", None), "nickname", "")
    if not nickname:
        return
    transaction.on_commit(lambda: im_tasks.sync_profile.delay(user.id, "nick"), robust=True)


def sync_im_avatar(user_id: int) -> None:
    """照片过审后把头像同步到 IM(任务内部取第一张过审照片的绝对 URL)。"""
    transaction.on_commit(lambda: im_tasks.sync_profile.delay(user_id, "avatar"), robust=True)
```

`chatapp/users/views.py`:

1. import 改:`from .services import get_profile, sync_im_avatar, sync_im_nickname`
2. `upload_photo` 的 `get_profile(request.user).refresh_status()` 之后加:

```python
    if status == PhotoStatus.APPROVED:
        sync_im_avatar(request.user.id)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test users`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chatapp/users chatapp/ops/tests.py
git commit -m "refactor(chatapp): 昵称/头像同步改走任务队列 + 照片过审同步 IM 头像"
```

(注:若 `ops/tests.py` 在 Step 1 无需改动则不加该文件;`git add` 按实际改动的文件来)

---

### Task 5: request_id 请求追踪 + 请求日志

**Files:**
- Create: `chatapp/config/request_id.py`、`chatapp/config/middleware.py`
- Modify: `chatapp/config/celery.py`(信号:入队带 header / worker 绑定)
- Modify: `chatapp/config/exceptions.py`(错误体补 `request_id` 字段 → `{code, message, request_id}`)
- Modify: `chatapp/config/settings.py`(MIDDLEWARE 首行、LOGGING、`REQUEST_SLOW_MS`、`LOG_FILE`、`CORS_EXPOSE_HEADERS`)
- Modify: `chatapp/.env.example`
- Test: `chatapp/config/tests.py`

**Interfaces:**
- Produces: `config.request_id.set_request_id(value)` / `current_request_id()` / `RequestIdFilter`;`config.celery._inject_request_id(headers=...)` / `_bind_request_id(task=...)`(模块级普通函数,供单测直接调用)
- 行为:任何响应带 `X-Request-Id`(客户端带了就回显);**错误体为标准契约 `{code, message, request_id}`**;日志每行带 `[request_id]`;`chatapp.request` 记录「方法 路径 状态 耗时」,≥ `REQUEST_SLOW_MS`(默认 500)升 WARNING;`LOG_FILE` 非空时额外落盘

- [ ] **Step 1: 写失败测试**(`chatapp/config/tests.py` 追加;顶部 import 补 `from django.test import SimpleTestCase, override_settings`)

```python
class RequestIdTests(APITestCase):
    def test_response_echoes_provided_request_id(self):
        resp = self.client.get("/api/v1/health", HTTP_X_REQUEST_ID="rid-123")
        self.assertEqual(resp["X-Request-Id"], "rid-123")

    def test_generates_request_id_when_absent(self):
        resp = self.client.get("/api/v1/health")
        self.assertTrue(resp["X-Request-Id"])

    def test_error_body_carries_request_id(self):
        resp = self.client.post("/api/v1/health", HTTP_X_REQUEST_ID="rid-err")   # 405
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.json()["request_id"], "rid-err")

    @override_settings(REQUEST_SLOW_MS=0)
    def test_request_log_carries_request_id(self):
        with self.assertLogs("chatapp.request", level="WARNING") as captured:
            self.client.get("/api/v1/health", HTTP_X_REQUEST_ID="rid-456")
        self.assertIn("rid-456", captured.output[0])
        self.assertIn("GET /api/v1/health", captured.output[0])


class CeleryRequestIdTests(SimpleTestCase):
    def test_inject_request_id_reads_context_var(self):
        from config.celery import _inject_request_id
        from config.request_id import set_request_id

        set_request_id("rid-1")
        self.addCleanup(set_request_id, None)
        headers = {}
        _inject_request_id(headers=headers)
        self.assertEqual(headers["request_id"], "rid-1")

    def test_inject_request_id_noop_without_context(self):
        from config.celery import _inject_request_id
        from config.request_id import set_request_id

        set_request_id(None)
        headers = {}
        _inject_request_id(headers=headers)
        self.assertNotIn("request_id", headers)

    def test_bind_request_id_from_task_headers(self):
        from config.celery import _bind_request_id
        from config.request_id import current_request_id, set_request_id

        set_request_id(None)
        self.addCleanup(set_request_id, None)

        class FakeTask:
            request = type("Req", (), {"headers": {"request_id": "rid-2"}})()

        _bind_request_id(task=FakeTask())
        self.assertEqual(current_request_id(), "rid-2")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test config.tests.RequestIdTests config.tests.CeleryRequestIdTests`
Expected: FAIL — 响应无 `X-Request-Id`、`ModuleNotFoundError: config.request_id`

- [ ] **Step 3: 实现**

`chatapp/config/request_id.py`(新建):

```python
"""请求追踪 ID:HTTP 中间件写入,日志 Filter 读取,Celery 任务随消息 header 传递。"""

import contextvars
import logging

_request_id = contextvars.ContextVar("request_id", default=None)


def set_request_id(value: str | None) -> None:
    _request_id.set(value)


def current_request_id() -> str | None:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """把当前请求 ID 塞进每条日志记录(没有则 '-');日志格式里用 %(request_id)s 引用。"""

    def filter(self, record):
        record.request_id = current_request_id() or "-"
        return True
```

`chatapp/config/middleware.py`(新建):

```python
"""请求追踪中间件:接受/生成 X-Request-Id,写响应头 + 请求日志(带耗时)。"""

import logging
import time
import uuid

from django.conf import settings

from .request_id import set_request_id

logger = logging.getLogger("chatapp.request")


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-Id") or uuid.uuid4().hex
        request.request_id = request_id
        set_request_id(request_id)
        start = time.monotonic()
        try:
            response = self.get_response(request)
            duration_ms = (time.monotonic() - start) * 1000
            # 慢请求升 WARNING(阈值 REQUEST_SLOW_MS 可调);日志里带 request_id 便于两端对账
            level = logging.WARNING if duration_ms >= settings.REQUEST_SLOW_MS else logging.INFO
            logger.log(level, "%s %s -> %s %.0fms",
                       request.method, request.path, response.status_code, duration_ms)
            response["X-Request-Id"] = request_id
            return response
        finally:
            set_request_id(None)
```

`chatapp/config/celery.py` 追加(⚠️ 用 `signal.connect(函数)` 显式注册,**不要用装饰器** —— Celery 的 `Signal.connect` 返回 signal 本身,装饰器会把函数名绑到 signal 上导致不可单测):

```python
from celery.signals import before_task_publish, task_postrun, task_prerun

from .request_id import current_request_id, set_request_id


def _inject_request_id(headers=None, **kwargs):
    """入队时把当前请求 ID 带进消息 header(worker 侧日志可用同一 ID 对账)。"""
    request_id = current_request_id()
    if request_id and isinstance(headers, dict):
        headers.setdefault("request_id", request_id)


def _bind_request_id(task=None, **kwargs):
    headers = getattr(getattr(task, "request", None), "headers", None) or {}
    set_request_id(headers.get("request_id"))


def _clear_request_id(**kwargs):
    set_request_id(None)


before_task_publish.connect(_inject_request_id)
task_prerun.connect(_bind_request_id)
task_postrun.connect(_clear_request_id)
```

`chatapp/config/settings.py`:

1. `MIDDLEWARE` 列表首位插入 `"config.middleware.RequestIdMiddleware",`
2. `CORS_ALLOWED_ORIGIN_REGEXES` 下加 `CORS_EXPOSE_HEADERS = ["X-Request-Id"]`
3. `LOGGING` 块整段替换为:

```python
# --- 日志:开发期要能在终端看到验证码;每行带 request_id ---
LOG_FILE = os.getenv("LOG_FILE", "")          # 置为文件路径则额外落盘(手测配 --noreload)
REQUEST_SLOW_MS = int(os.getenv("REQUEST_SLOW_MS", "500"))

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {"request_id": {"()": "config.request_id.RequestIdFilter"}},
    "formatters": {
        "console": {"format": "%(levelname)s %(asctime)s [%(request_id)s] %(name)s %(message)s"},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler",
                    "filters": ["request_id"], "formatter": "console"},
    },
    "loggers": {
        "accounts": {"handlers": ["console"], "level": "INFO"},
        "im": {"handlers": ["console"], "level": "INFO"},
        "chatapp.request": {"handlers": ["console"], "level": "INFO"},
    },
}
if LOG_FILE:
    # ⚠️ 手测时用 runserver --noreload:autoreload 的两个进程会抢写同一文件
    LOGGING["handlers"]["file"] = {
        "class": "logging.handlers.RotatingFileHandler",
        "filename": LOG_FILE,
        "maxBytes": 5 * 1024 * 1024,
        "backupCount": 3,
        "encoding": "utf-8",
        "filters": ["request_id"],
        "formatter": "console",
    }
    LOGGING["root"] = {"handlers": ["console", "file"], "level": "INFO"}
```

`chatapp/config/exceptions.py` 的错误体补 `request_id`(标准契约 `{code, message, request_id}`):

```python
from rest_framework.views import exception_handler

from .request_id import current_request_id
```

```python
    response.data = {
        "code": detail_code if detail_code is not None else response.status_code,
        "message": _first_message(response.data),
        "request_id": current_request_id(),
    }
```

`chatapp/.env.example` 追加(本地 `.env` 也同步加,可留空值):

```
# 可选:限流/日志/头像同步(不设置走 settings 默认)
# SMS_SEND_IP_RATE=20/hour
# SMS_VERIFY_IP_RATE=60/hour
# REQUEST_SLOW_MS=500
# LOG_FILE=logs/chatapp.log
# MEDIA_BASE_URL=http://127.0.0.1:8000
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test config`
Expected: PASS(新增 6 个用例 + 原有全绿)

- [ ] **Step 5: 全量后端回归(日志格式改动影响面大,提前跑一次)**

Run: `cd chatapp && python manage.py test`
Expected: 全绿

- [ ] **Step 6: Commit**

```bash
git add chatapp/config chatapp/.env.example
git commit -m "feat(chatapp): request_id 请求追踪(响应头+日志+Celery header)与请求耗时日志"
```

---

### Task 6: 限流维度补齐(sms_send/sms_verify env 化 + 锁定 Retry-After)

**Files:**
- Modify: `chatapp/accounts/throttles.py`(新增 `SmsVerifyThrottle`)
- Modify: `chatapp/accounts/views.py`(`sms_verify` 挂限流)
- Modify: `chatapp/accounts/exceptions.py`(`SmsLocked` 支持 `wait`)
- Modify: `chatapp/accounts/services.py`(`check_code` 传 `wait`)
- Modify: `chatapp/config/settings.py`(`SMS_SEND_IP_RATE` / `SMS_VERIFY_IP_RATE` 环境变量 + `DEFAULT_THROTTLE_RATES`)
- Test: `chatapp/accounts/tests.py`

**Interfaces:**
- Produces: `accounts.throttles.SmsVerifyThrottle`(scope `sms_verify`);`SmsLocked(wait=...)` 响应带 `Retry-After`
- 维度现状:号码重发 60s = `sms:send:{phone}` 自有键(不变);IP 维度 = DRF throttling(计数在 Redis)

- [ ] **Step 1: 写失败测试**(`chatapp/accounts/tests.py`;`SmsVerifyTests` 类内追加)

```python
    def test_verify_ip_throttle(self):
        from accounts.throttles import SmsVerifyThrottle
        with patch.object(SmsVerifyThrottle, "rate", "3/hour", create=True):
            for i in range(3):
                resp = self.verify("000000", phone=f"1380013800{i}")
                self.assertEqual(resp.status_code, 400)   # 码错(限流额度内)
            resp = self.verify("000000", phone="13800138009")
        self.assertEqual(resp.status_code, 429)

    def test_lock_response_carries_retry_after(self):
        self.issue_code()
        for _ in range(settings.SMS_MAX_ATTEMPTS):
            self.verify("000000")
        resp = self.verify("000000")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.headers.get("Retry-After"), str(settings.SMS_LOCK_TTL))

    def test_verify_path_never_calls_im_rest(self):
        """响应路径零外部调用:登录成功只入队任务,绝不同步打腾讯(第 1 期铁律的回归)。"""
        code = self.issue_code()
        with patch("im.client._request") as rest, patch("im.tasks.import_account.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.verify(code)
        self.assertEqual(resp.status_code, 200)
        rest.assert_not_called()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test accounts.tests.SmsVerifyTests`
Expected: FAIL — `AttributeError: module 'accounts.throttles' has no attribute 'SmsVerifyThrottle'`

- [ ] **Step 3: 实现**

`chatapp/accounts/throttles.py` 追加:

```python
class SmsVerifyThrottle(SimpleRateThrottle):
    """按 IP 限流校验验证码(防扫号);额度在 settings.DEFAULT_THROTTLE_RATES["sms_verify"]。"""

    scope = "sms_verify"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
```

`chatapp/accounts/views.py`:`from .throttles import SmsSendThrottle, SmsVerifyThrottle`;`sms_verify` 装饰器加一行:

```python
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SmsVerifyThrottle])
def sms_verify(request):
```

`chatapp/accounts/exceptions.py` 的 `SmsLocked` 改为(其余异常不动):

```python
class SmsLocked(APIException):
    status_code = 429
    default_detail = "错误次数过多,请稍后再试"
    detail_code = error_codes.SMS_TOO_MANY_ATTEMPTS

    def __init__(self, wait=None):
        self.wait = wait      # DRF 全局处理器见到 wait 会给响应加 Retry-After
        super().__init__()
```

`chatapp/accounts/services.py` 的 `check_code` 末行改为:

```python
    if result in (sms_codes.CodeResult.LOCKED, sms_codes.CodeResult.JUST_LOCKED):
        raise SmsLocked(wait=settings.SMS_LOCK_TTL)
```

`chatapp/config/settings.py`:在 `REST_FRAMEWORK = {` 之前加限流额度块,并改 `DEFAULT_THROTTLE_RATES`:

```python
# --- 限流额度(env 可调;DEBUG 下放宽,免得两台模拟器共享 127.0.0.1 触发 IP 限流) ---
SMS_SEND_IP_RATE = os.getenv("SMS_SEND_IP_RATE", "200/hour" if DEBUG else "20/hour")
SMS_VERIFY_IP_RATE = os.getenv("SMS_VERIFY_IP_RATE", "600/hour" if DEBUG else "60/hour")

REST_FRAMEWORK = {
    ...(原有键不动)...
    "DEFAULT_THROTTLE_RATES": {
        "sms_send": SMS_SEND_IP_RATE,
        "sms_verify": SMS_VERIFY_IP_RATE,
        "swipe": "300/hour",
        "report": "20/day",
    },
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test accounts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add chatapp/accounts chatapp/config/settings.py
git commit -m "feat(chatapp): 限流维度补齐(verify IP 限流 + rate env 化 + 锁定 Retry-After)"
```

---

### Task 7: `/matches` 与 `/blocks` 统一分页(LimitOffset + 前端跟页)

**Files:**
- Create: `chatapp/config/pagination.py`
- Modify: `chatapp/config/settings.py`(`DEFAULT_PAGINATION_CLASS`)
- Modify: `chatapp/discovery/views.py`(`match_list`)
- Modify: `chatapp/moderation/views.py`(`blocks` GET)
- Modify: `app/lib/core/api_client.dart`(新增 `getAllPages`)
- Modify: `app/lib/im/im_repository.dart`(`fetchMatches`)
- Modify: `app/lib/features/moderation/moderation_repository.dart`(`fetchBlockedUsers`)
- Test: `chatapp/discovery/tests.py`、`chatapp/moderation/tests.py`、`app/test/**`(见 Step 1)

**Interfaces:**
- 后端响应新契约:`{"count": n, "next": url|null, "previous": url|null, "results": [...]}`
- 前端 `ApiClient.getAllPages(path, {pageSize = 50}) -> List<dynamic>`(循环跟 `next`,返回 results 拼接)

- [ ] **Step 1: 改测试(先红)**

后端 `chatapp/discovery/tests.py::MatchListTests` 四个用例改写 + 新增一个:

```python
    def test_lists_both_sides(self):
        other = self._make_user("13900139000", nickname="小红")
        Match.objects.create(**Match.pair_kwargs(self.me, other))
        data = self.client.get(self.URL).json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["user_id"], other.id)
        self.assertEqual(data["results"][0]["im_user_id"], other.im_user_id)
        self.assertEqual(data["results"][0]["nickname"], "小红")
        self.assertTrue(data["results"][0]["avatar_url"].startswith("http://testserver/media/"))

    def test_avatar_null_without_approved_photo(self):
        other = self._make_user("13900139000", with_photo=False)
        Match.objects.create(**Match.pair_kwargs(self.me, other))
        self.assertIsNone(self.client.get(self.URL).json()["results"][0]["avatar_url"])

    def test_only_my_matches(self):
        other = self._make_user("13900139000")
        stranger_a = self._make_user("13900139001")
        stranger_b = self._make_user("13900139002")
        Match.objects.create(**Match.pair_kwargs(self.me, other))
        Match.objects.create(**Match.pair_kwargs(stranger_a, stranger_b))
        data = self.client.get(self.URL).json()
        self.assertEqual([item["user_id"] for item in data["results"]], [other.id])

    def test_pagination_limit_and_offset(self):
        others = [self._make_user(f"1390013910{i}") for i in range(3)]
        for other in others:
            Match.objects.create(**Match.pair_kwargs(self.me, other))
        first = self.client.get(self.URL, {"limit": 2}).json()
        self.assertEqual(first["count"], 3)
        self.assertEqual(len(first["results"]), 2)
        second = self.client.get(self.URL, {"limit": 2, "offset": 2}).json()
        self.assertEqual(len(second["results"]), 1)
        ids = [item["user_id"] for item in first["results"] + second["results"]]
        self.assertEqual(sorted(ids), sorted(other.id for other in others))   # 翻页不重不漏
```

(`test_requires_auth` 不动)

后端 `chatapp/moderation/tests.py::BlockApiTests` 两个列表用例改写:

```python
    def test_list_shows_nickname_and_avatar(self):
        Block.objects.create(blocker=self.me, blocked=self.target)
        data = self.client.get(self.URL).json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["results"][0]["user_id"], self.target.id)
        self.assertEqual(data["results"][0]["nickname"], "小红")
        self.assertTrue(data["results"][0]["avatar_url"].startswith("http://testserver/media/"))

    def test_list_avatar_null_without_approved_photo(self):
        Photo.objects.update(status=PhotoStatus.PENDING)
        Block.objects.create(blocker=self.me, blocked=self.target)
        self.assertIsNone(self.client.get(self.URL).json()["results"][0]["avatar_url"])
```

前端:

1. `app/test/support/sample_data.dart` 追加:

```dart
/// 造一份 LimitOffset 分页响应;hasNext=true 时给一个非空 next(测跟页用)。
Map<String, dynamic> pageJson(List<dynamic> items, {bool hasNext = false}) => {
      'count': items.length,
      'next': hasNext ? 'http://test/api/v1/next' : null,
      'previous': null,
      'results': items,
    };
```

2. 以下 7 处把 `ok([...])` 包成 `ok(pageJson([...]))`(调用点不变,只改响应体):
   - `app/test/im/im_repository_test.dart:` `'GET /matches'`(第 40 行)
   - `app/test/features/chat/match_cache_test.dart:` `'GET /matches'`(第 38 行)
   - `app/test/features/chat/chat_page_test.dart:` 第 61 行、第 257 行(`ok([])` → `ok(pageJson([]))`)
   - `app/test/features/chat/chats_page_test.dart:` `'GET /matches'`(第 22 行)
   - `app/test/features/moderation/moderation_repository_test.dart:` `'GET /blocks'`(第 47 行)
   - `app/test/features/settings/blocked_users_page_test.dart:` 第 36、44 行
   - `app/test/features/profile/user_profile_page_test.dart:` 第 141 行
3. `app/test/im/im_repository_test.dart` 新增跟页用例:

```dart
  test('fetchMatches 跟 next 拉完所有页(分页约定)', () async {
    adapter.routes['GET /matches'] = (options) {
      final offset = options.uri.queryParameters['offset'] ?? '0';
      if (offset == '0') {
        return ok(pageJson([matchJson(userId: 9, nickname: '小红')], hasNext: true));
      }
      return ok(pageJson([matchJson(userId: 10, nickname: '小刚')]));
    };

    final matches = await repository.fetchMatches();

    expect(matches.map((entry) => entry.userId), [9, 10]);
    expect(adapter.log.length, 2);                                  // 拉了 2 页
    expect(adapter.log.last.uri.queryParameters['offset'], '1');    // 第二页 offset=第一页实际条数
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test discovery.tests.MatchListTests moderation.tests.BlockApiTests`
Run: `cd app && ../flutter/bin/flutter.bat test test/im/im_repository_test.dart`
Expected: 双端 FAIL — 后端返回裸 list(取 `["results"]` KeyError/TypeError);前端 `data as List` 对新对象 cast 失败

- [ ] **Step 3: 实现**

`chatapp/config/pagination.py`(新建):

```python
"""列表接口统一分页约定:LimitOffset(参数 limit/offset,响应 count/next/previous/results)。"""

from rest_framework.pagination import LimitOffsetPagination


class DefaultLimitOffsetPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 100
```

`chatapp/config/settings.py` 的 `REST_FRAMEWORK` 加一行 `"DEFAULT_PAGINATION_CLASS": "config.pagination.DefaultLimitOffsetPagination",`

`chatapp/discovery/views.py`:

1. import 加 `from config.pagination import DefaultLimitOffsetPagination`
2. `match_list` 结尾改为:

```python
@api_view(["GET"])
def match_list(request):
    me = request.user
    blocked_ids = blocked_user_ids(me)
    matches = (Match.objects.filter(Q(user_a=me) | Q(user_b=me))
               .exclude(Q(user_a_id__in=blocked_ids) | Q(user_b_id__in=blocked_ids))
               .select_related("user_a__profile", "user_b__profile")
               .prefetch_related("user_a__photos", "user_b__photos"))
    entries = [_match_entry(match, me, request) for match in matches]
    paginator = DefaultLimitOffsetPagination()   # Match Meta ordering=-created_at,翻页顺序稳定
    page = paginator.paginate_queryset(entries, request)
    return paginator.get_paginated_response(page)
```

`chatapp/moderation/views.py`:

1. import 加 `from config.pagination import DefaultLimitOffsetPagination`
2. `blocks` 的 GET 分支改为:

```python
    entries = (Block.objects.filter(blocker=request.user)
               .select_related("blocked__profile").prefetch_related("blocked__photos"))
    paginator = DefaultLimitOffsetPagination()
    page = paginator.paginate_queryset(entries, request)
    return paginator.get_paginated_response(
        [BlockSerializer(block, context={"request": request}).data for block in page])
```

`app/lib/core/api_client.dart` 追加方法:

```dart
  /// 跟 LimitOffset 分页约定拉全量:循环请求直到 next 为空,返回 results 拼接。
  Future<List<dynamic>> getAllPages(String path, {int pageSize = 50}) async {
    final items = <dynamic>[];
    var offset = 0;
    while (true) {
      final page = await get(path, query: {'limit': pageSize, 'offset': offset})
          as Map<String, dynamic>;
      final results = page['results'] as List<dynamic>;
      items.addAll(results);
      offset += results.length;
      if (page['next'] == null || results.isEmpty) return items;
    }
  }
```

`app/lib/im/im_repository.dart` 的 `fetchMatches` 第一行改:

```dart
    final data = await _api.getAllPages('/matches');
```

`app/lib/features/moderation/moderation_repository.dart` 的 `fetchBlockedUsers` 第一行改:

```dart
    final data = await _api.getAllPages('/blocks');
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test discovery moderation`
Run: `cd app && ../flutter/bin/flutter.bat test`
Expected: 全绿

- [ ] **Step 5: Commit**

```bash
git add chatapp/config/pagination.py chatapp/config/settings.py chatapp/discovery/views.py chatapp/moderation/views.py
git commit -m "feat(chatapp): /matches 与 /blocks 统一 LimitOffset 分页"
git add app/lib app/test
git commit -m "feat(app): 配对/黑名单列表适配分页(跟 next 拉全量)"
```

---

### Task 8: 收尾(全量回归 + 手测清单 + CLAUDE.md)

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 双端全量回归**

Run: `cd chatapp && python manage.py test`
Run: `cd app && ../flutter/bin/flutter.bat test && ../flutter/bin/flutter.bat analyze`
Expected: 后端全绿(新增约 10+6+3 用例)、前端全绿、analyze 零告警

- [ ] **Step 2: 手测(Redis + runserver + worker 三者同跑,双模拟器)**

```bash
cd chatapp
docker compose -f docker-compose.dev.yml up -d
python manage.py runserver 0.0.0.0:8000 --noreload        # 终端 A(配 LOG_FILE 时避免 autoreload 双写)
python -m celery -A config worker -l info --pool=solo     # 终端 B
```

手测清单:
1. 配对:两个完善资料的号互滑 → 灰条照常出现、无变慢;worker 终端出现 `im.tasks.send_match_notice`;
2. 拉黑/解除:对方从候选/配对消失(既有),worker 出现 `blacklist_add` / `blacklist_remove`;
3. 封禁:ops 台重封一个号 → 系统通知送达 + 被踢下线;worker 出现 `im.tasks.ban_notice`(heavy);
4. 改昵称 → 对方会话列表名字变新;上传/过审照片 → worker 出现 `sync_profile`(avatar)且成功(IM 侧能否拉到 `127.0.0.1` 头像受网络限制,只看任务成功不看头像图);
5. request_id:`curl -H "X-Request-Id: test-123"` 请求 → 响应头回显、错误响应体含 `request_id`;runserver 终端日志每行带 `[test-123]`;慢请求(如带限流等待)≥500ms 显示 WARNING;
6. 分页:匹配数 > 20 时「消息」页会话名不缺失(前端跟页拉全);黑名单页正常;
7. 限流:同 IP 快速连点验证码 → 429 带 Retry-After;连错 5 次 → 429 + Retry-After(15 分钟)。

- [ ] **Step 3: 更新 CLAUDE.md**

1. 「接口标准化」节:
   - 把「⚠️ moderation / discovery / users 目前**仍是旧的后台线程**(…),第 2 期统一迁到 tasks」改为:IM 副作用**全部**经 `im/tasks.py`(配对灰条/封禁通知/黑名单/昵称头像),线程辅助函数已删除;
   - IM 副作用入口条目补任务清单:`send_match_notice / blacklist_add / blacklist_remove / ban_notice(heavy 先发后踢)/ ban_lifted / sync_profile(user_id, kind)`;
   - 新增:request_id(`X-Request-Id` 回显 + 日志 Filter + Celery header,`LOG_FILE`/`REQUEST_SLOW_MS` env)、限流 rate env(`SMS_SEND_IP_RATE`/`SMS_VERIFY_IP_RATE`,dev 放宽)、分页约定(limit/offset,响应 count/next/previous/results;前端 `ApiClient.getAllPages` 跟 next)、头像同步(`MEDIA_BASE_URL` 拼绝对 URL,过审/上传即过审触发)。
2. 「后端测试注意事项」:补一条「第 2 期起断言入队一律 `patch("im.tasks.X.delay")` + `captureOnCommitCallbacks(execute=True)`;任务体测试用 `.run()`」。
3. 「常用命令」:`seed_fake_users` 行补一句「头像/昵称会经任务同步(需 worker 在跑)」。

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: 接口标准化第 2 期落地写入 CLAUDE.md(IM 任务化/request_id/限流/分页)"
```

---

## 执行记录

(执行时在此记录:完成情况、测试数、手测结论、发现的坑)
