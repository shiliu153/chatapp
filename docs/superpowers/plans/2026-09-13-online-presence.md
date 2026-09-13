# 在线状态(最后活跃)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 抖音式在线标识 —— 消息列表绿点、聊天页标题「● 在线 / x 分钟前在线」、发现卡昵称旁同样文案;数据由自建 Redis「最后活跃时间」提供,复用现有 45 秒登录态心跳。

**Architecture:** 后端在 `SessionJwtAuthentication` 校验通过后 `touch` 一个 Redis 键(`presence:{user_id}` = Unix 时间戳,TTL 7 天),新接口 `GET /api/v1/presence?user_ids=...` 批量查询(拉黑/不存在/自己/重封禁省略);前端一个共享 autoDispose `PresenceController`,各页面在 build 里 `track(owner, ids)` 登记关心的人,合并去重后立即拉一次 + 45 秒周期刷新。

**Tech Stack:** Django 5.2 + DRF(Redis via django-redis)、Flutter 3.47 + Riverpod 3.4。

**Spec:** `docs/superpowers/specs/2026-09-13-online-presence-design.md`

## Global Constraints

- 后端测试基线 **310 全绿**、前端基线 **170 全绿**,本计划完成后都必须保持全绿;`flutter analyze` **零告警**。
- 后端跑任何测试前 **Redis 必须已起**(`docker compose -f docker-compose.dev.yml up -d`);测试自动用 DB15 缓存,不碰开发数据。
- 涉及限流/新缓存的用例必须 `cache.clear()`(跨用例残留会导致偶发 429/脏数据)。
- HTTP 响应路径禁止任何第三方网络调用(本特性只碰本地 Redis,天然满足;别引入腾讯调用)。
- `flutter/` 是 SDK 源码目录,绝不修改、绝不提交。命令用 `../flutter/bin/flutter.bat`(cwd = `app/`),Python cwd = `chatapp/`。
- 前端 widget 测试纪律:`pumpApp` + `ScriptedAdapter` 假网络按 `"METHOD path"` 铺路由(`options.path` 不含查询串,`/presence` 的查询参数从 `options.queryParameters` 断言);别裸 `await` 走 dio 的 provider;含无限动画/倒计时的页面别 `pumpAndSettle`。
- 代码注释只写 WHY、中文;提交信息中文,沿用 `feat:` / `docs:` / `test:` 前缀。
- 时区:`TIME_ZONE="Asia/Shanghai"`,接口返回的 `last_active_at` 必须是 `+08:00` 本地时区 ISO(前端 `DateTime.parse` 直用)。

---

### Task 1: presence 服务层(touch / 批量查询)

**Files:**
- Create: `chatapp/users/presence.py`
- Test: `chatapp/users/tests.py`(文件末尾追加 `PresenceServiceTests`;顶部已 import 的 `time`/`cache` 缺谁补谁)

**Interfaces:**
- Consumes: 无(纯 Django cache)
- Produces(后续任务依赖的确切签名):
  - `users.presence.touch(user_id: int) -> None`
  - `users.presence.get_presence(user_ids: list[int]) -> dict[int, dict]`,值形状 `{"online": bool, "last_active_at": str | None}`
  - 常量 `ONLINE_WINDOW_SECONDS = 120`、`PRESENCE_TTL_SECONDS = 7*24*3600`、`PRESENCE_MAX_IDS = 100`

- [ ] **Step 1: 写失败测试**

在 `chatapp/users/tests.py` 末尾追加(顶部若缺 `import time`、`from django.core.cache import cache` 请补上):

```python
class PresenceServiceTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_touch_then_online(self):
        presence.touch(9)
        data = presence.get_presence([9])
        self.assertTrue(data[9]["online"])
        self.assertIsNotNone(data[9]["last_active_at"])

    def test_online_window_boundary(self):
        # 119 秒内 = 在线;121 秒 = 离线但仍有最后活跃时间
        cache.set("presence:9", int(time.time()) - 119)
        cache.set("presence:10", int(time.time()) - 121)
        data = presence.get_presence([9, 10])
        self.assertTrue(data[9]["online"])
        self.assertFalse(data[10]["online"])
        self.assertIsNotNone(data[10]["last_active_at"])

    def test_unknown_user_is_unknown(self):
        self.assertEqual(presence.get_presence([404])[404],
                         {"online": False, "last_active_at": None})

    def test_iso_uses_local_timezone(self):
        cache.set("presence:9", 1757745000)
        text = presence.get_presence([9])[9]["last_active_at"]
        self.assertRegex(text, r"\+08:00$")

    @patch("users.presence.cache.get_many", side_effect=Exception("boom"))
    def test_redis_down_query_degrades(self, _):
        self.assertEqual(presence.get_presence([9])[9],
                         {"online": False, "last_active_at": None})

    @patch("users.presence.cache.set", side_effect=Exception("boom"))
    def test_redis_down_touch_is_silent(self, _):
        presence.touch(9)   # 不抛异常
```

同文件顶部加 `from . import presence`(与既有 `from .models import ...` 并列)。

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test users.tests.PresenceServiceTests -v 1`
Expected: FAIL(`ModuleNotFoundError` / `AttributeError: module 'users' has no attribute 'presence'`)

- [ ] **Step 3: 写实现**

新建 `chatapp/users/presence.py`:

```python
"""在线状态(最后活跃):Redis 时间戳,认证请求即刷新。

不依赖腾讯 IM 在线状态能力(需付费套餐,且没有「最后活跃时间」)。
"""
import logging
import time
from datetime import datetime, timezone as dt_timezone

from django.core.cache import cache
from django.utils import timezone as dj_timezone

logger = logging.getLogger(__name__)

PRESENCE_TTL_SECONDS = 7 * 24 * 3600   # 最后活跃最多记 7 天,更久视为未知
ONLINE_WINDOW_SECONDS = 120            # 最近 2 分钟内有活动 = 在线(45s 心跳 ×2 + 余量)
PRESENCE_MAX_IDS = 100                 # 单次批量查询上限


def _key(user_id: int) -> str:
    return f"presence:{user_id}"


def touch(user_id: int) -> None:
    """记一次活跃;失败只记日志 —— presence 是点缀,绝不拖累业务请求。"""
    try:
        cache.set(_key(user_id), int(time.time()), timeout=PRESENCE_TTL_SECONDS)
    except Exception:
        logger.warning("presence 写入失败 user_id=%s", user_id, exc_info=True)


def get_presence(user_ids: list[int]) -> dict[int, dict]:
    """批量查:{user_id: {"online": bool, "last_active_at": iso|None}}。

    无记录 / Redis 不可用 → online=False、last_active_at=None(前端不显示)。
    """
    now_ts = int(time.time())
    result = {uid: {"online": False, "last_active_at": None} for uid in user_ids}
    try:
        values = cache.get_many([_key(uid) for uid in user_ids])
    except Exception:
        logger.warning("presence 查询失败", exc_info=True)
        return result
    for uid in user_ids:
        ts = values.get(_key(uid))
        if ts is None:
            continue
        ts = int(ts)
        result[uid] = {
            "online": now_ts - ts <= ONLINE_WINDOW_SECONDS,
            "last_active_at": _iso(ts),
        }
    return result


def _iso(ts: int) -> str:
    """本地时区 ISO(+08:00),前端 DateTime.parse 直接可用。"""
    return dj_timezone.localtime(
        datetime.fromtimestamp(ts, tz=dt_timezone.utc)).isoformat()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test users.tests.PresenceServiceTests -v 1`
Expected: PASS(6 个用例)

- [ ] **Step 5: 提交**

```bash
git add chatapp/users/presence.py chatapp/users/tests.py
git commit -m "feat(presence): Redis 最后活跃服务层(touch/批量查询/降级)"
```

---

### Task 2: 认证钩子(每次认证请求顺手 touch)

**Files:**
- Modify: `chatapp/accounts/authentication.py`(get_user 末尾,`return user` 前)
- Test: `chatapp/accounts/tests.py`(末尾追加 `PresenceHookTests`)

**Interfaces:**
- Consumes: `users.presence.touch(user_id)`(Task 1)
- Produces: 无需显式接口 —— 效果是任何带 Bearer 的请求都会刷新 `presence:{user_id}`

- [ ] **Step 1: 写失败测试**

在 `chatapp/accounts/tests.py` 末尾追加(顶部补 `from django.core.cache import cache` 等缺失 import;`User`/`RefreshToken`/`APITestCase` 该文件已有):

```python
class PresenceHookTests(APITestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(phone="13800138000")

    def _login(self):
        refresh = RefreshToken.for_user(self.user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")

    def test_authenticated_request_touches_presence(self):
        self._login()
        resp = self.client.get("/api/v1/users/me")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(cache.get(f"presence:{self.user.id}"))

    def test_anonymous_request_does_not_touch(self):
        self.client.get("/api/v1/health")
        self.assertIsNone(cache.get(f"presence:{self.user.id}"))

    def test_rejected_stale_token_does_not_touch(self):
        # 被顶号的旧令牌(40101)不算一次「活跃」
        self._login()
        self.user.session_version += 1
        self.user.save(update_fields=["session_version"])
        resp = self.client.get("/api/v1/users/me")
        self.assertEqual(resp.status_code, 401)
        self.assertIsNone(cache.get(f"presence:{self.user.id}"))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test accounts.tests.PresenceHookTests -v 1`
Expected: FAIL(`test_authenticated_request_touches_presence` 断言失败)

- [ ] **Step 3: 写实现**

`chatapp/accounts/authentication.py` 顶部加 import,`get_user` 在版本校验通过后、`return user` 前 touch:

```python
from users.presence import touch
```

```python
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        # 兼容没有该 claim 的历史令牌(等同于初始版本);正式签发的令牌都带它
        token_version = validated_token.get("session_version", SESSION_VERSION_DEFAULT)
        if token_version != user.session_version:
            raise SingleDeviceSessionConflict()
        touch(user.id)   # 认证通过即刷新「最后活跃」;失败静默(内部兜底)
        return user
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test accounts.tests.PresenceHookTests -v 1`
Expected: PASS(3 个用例);再跑 `python manage.py test accounts` 确认该 app 无回归(既有用例的认证请求会多写一个 Redis 键,无断言冲突)。

- [ ] **Step 5: 提交**

```bash
git add chatapp/accounts/authentication.py chatapp/accounts/tests.py
git commit -m "feat(presence): 认证通过即刷新最后活跃(被顶号旧令牌不算)"
```

---

### Task 3: `GET /api/v1/presence` 接口 + 限流

**Files:**
- Create: `chatapp/users/throttles.py`
- Modify: `chatapp/users/views.py`(末尾加视图)
- Modify: `chatapp/config/api_urls.py`(顶层加路由)
- Modify: `chatapp/config/settings.py`(约 190 行常量区 + 202 行 `DEFAULT_THROTTLE_RATES`)
- Modify: `docs/superpowers/specs/2026-09-13-online-presence-design.md`(§3 省略规则补一条)
- Test: `chatapp/users/tests.py`(末尾追加 `PresenceApiTests`)

**Interfaces:**
- Consumes: `presence.get_presence`、`presence.PRESENCE_MAX_IDS`(Task 1);`moderation.services.blocked_user_ids`(已有)
- Produces: `GET /api/v1/presence?user_ids=3,5,7` → `{"results": [{"user_id", "online", "last_active_at"}, ...]}`;`PresenceThrottle`(scope `presence`)

- [ ] **Step 1: 写失败测试**

在 `chatapp/users/tests.py` 末尾追加:

```python
class PresenceApiTests(AuthMixin, APITestCase):
    def setUp(self):
        cache.clear()
        self.me = User.objects.create_user(phone="13800138000")
        self.other = User.objects.create_user(phone="13800138001")
        Profile.objects.get_or_create(user=self.other)
        self.login(self.me)
        self.url = "/api/v1/presence"

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.url, {"user_ids": "1"}).status_code, 401)

    def test_returns_online_and_last_active(self):
        presence.touch(self.other.id)
        data = self.client.get(self.url, {"user_ids": str(self.other.id)}).json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["user_id"], self.other.id)
        self.assertTrue(data["results"][0]["online"])
        self.assertRegex(data["results"][0]["last_active_at"], r"\+08:00$")

    def test_omits_blocked_both_directions(self):
        third = User.objects.create_user(phone="13800138002")
        Block.objects.create(blocker=self.me, blocked=self.other)      # 我拉黑的
        Block.objects.create(blocker=third, blocked=self.me)           # 拉黑我的
        data = self.client.get(
            self.url, {"user_ids": f"{self.other.id},{third.id}"}).json()
        self.assertEqual(data["results"], [])

    def test_omits_self_unknown_and_heavy_banned(self):
        Profile.objects.filter(user=self.other).update(status=ProfileStatus.BANNED_HEAVY)
        data = self.client.get(
            self.url,
            {"user_ids": f"{self.me.id},{self.other.id},999999"}).json()
        self.assertEqual(data["results"], [])

    def test_dedupes_and_keeps_request_order(self):
        data = self.client.get(
            self.url,
            {"user_ids": f"{self.other.id},{self.me.id},{self.other.id}"}).json()
        # 自己去重省略后,只剩 other,顺序稳定
        self.assertEqual([item["user_id"] for item in data["results"]], [self.other.id])

    def test_bad_params(self):
        self.assertEqual(self.client.get(self.url).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"user_ids": ""}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"user_ids": "abc"}).status_code, 400)
        too_many = ",".join(str(i) for i in range(1, 102))
        self.assertEqual(self.client.get(self.url, {"user_ids": too_many}).status_code, 400)

    def test_throttled(self):
        from .throttles import PresenceThrottle

        with patch.object(PresenceThrottle, "rate", "2/hour", create=True):
            for _ in range(2):
                self.assertEqual(
                    self.client.get(self.url, {"user_ids": str(self.other.id)}).status_code, 200)
            self.assertEqual(
                self.client.get(self.url, {"user_ids": str(self.other.id)}).status_code, 429)

    @patch("users.presence.cache.get_many", side_effect=Exception("boom"))
    def test_redis_down_returns_null_instead_of_500(self, _):
        resp = self.client.get(self.url, {"user_ids": str(self.other.id)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"][0]["last_active_at"], None)
```

同文件顶部补 `from . import presence`、`from .throttles import PresenceThrottle`(若放在用例内 import 则不必,按上面写法只需 `presence`;`ProfileStatus`/`Block`/`cache`/`patch` 该文件已有)。

- [ ] **Step 2: 跑测试确认失败**

Run: `python manage.py test users.tests.PresenceApiTests -v 1`
Expected: FAIL(404,路由不存在)

- [ ] **Step 3: 写实现**

新建 `chatapp/users/throttles.py`:

```python
from rest_framework.throttling import SimpleRateThrottle


class PresenceThrottle(SimpleRateThrottle):
    """按用户限流在线状态查询;额度在 settings.DEFAULT_THROTTLE_RATES["presence"]。"""

    scope = "presence"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
```

`chatapp/users/views.py`:把顶部既有的 `from rest_framework.decorators import api_view` **改成** `from rest_framework.decorators import api_view, throttle_classes`,并补:

```python
from .presence import PRESENCE_MAX_IDS, get_presence
from .throttles import PresenceThrottle
```

```python
@api_view(["GET"])
@throttle_classes([PresenceThrottle])
def presence_status(request):
    """批量查在线状态;被拉黑/不存在/自己/重封禁的人从结果里省略。"""
    raw = request.query_params.get("user_ids", "")
    parts = [part.strip() for part in raw.split(",") if part.strip()]
    if not parts:
        return Response({"code": 400, "message": "user_ids 不能为空"}, status=400)
    try:
        ids = [int(part) for part in parts]
    except ValueError:
        return Response({"code": 400, "message": "user_ids 必须是数字"}, status=400)
    seen: set[int] = set()
    ids = [uid for uid in ids if not (uid in seen or seen.add(uid))]   # 去重保序
    if len(ids) > PRESENCE_MAX_IDS:
        return Response({"code": 400, "message": f"一次最多查询 {PRESENCE_MAX_IDS} 个用户"}, status=400)

    hidden = blocked_user_ids(request.user)
    visible = [uid for uid in ids if uid != request.user.id and uid not in hidden]
    if visible:
        existing = set(User.objects.filter(id__in=visible).values_list("id", flat=True))
        banned = set(Profile.objects.filter(user_id__in=visible,
                                            status=ProfileStatus.BANNED_HEAVY)
                     .values_list("user_id", flat=True))
        visible = [uid for uid in visible if uid in existing and uid not in banned]
    data = get_presence(visible)
    return Response({"results": [{"user_id": uid, **data[uid]} for uid in visible]})
```

`chatapp/config/api_urls.py` 顶层加一行(与 `/matches` 同级):

```python
    path("presence", users_views.presence_status),
```

并在该文件顶部 import:`from users import views as users_views`。

`chatapp/config/settings.py`:常量区(约 190 行,`SMS_VERIFY_IP_RATE` 附近)加:

```python
PRESENCE_RATE = os.getenv("PRESENCE_RATE", "600/hour")
```

`DEFAULT_THROTTLE_RATES` 里加:

```python
        "presence": PRESENCE_RATE,
```

同时把 spec `docs/superpowers/specs/2026-09-13-online-presence-design.md` §3 省略规则一行改为(重封禁与资料卡 404 语义一致):

```
- 返回顺序与请求给出顺序一致;以下 id **直接从 results 省略**(不报错、不泄露关系):被拉黑(双向,复用 `moderation.services.blocked_user_ids`)、不存在、自己、重复项、被重封禁(与公开资料卡 404 语义一致)。
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python manage.py test users.tests.PresenceApiTests -v 1`
Expected: PASS(7 个用例)

- [ ] **Step 5: 提交**

```bash
git add chatapp/users/throttles.py chatapp/users/views.py chatapp/config/api_urls.py chatapp/config/settings.py chatapp/users/tests.py docs/superpowers/specs/2026-09-13-online-presence-design.md
git commit -m "feat(presence): GET /presence 批量查询接口(拉黑/重封禁省略,600/h 限流)"
```

**后端完成度检查:** 跑 `python manage.py test`,基线 310 + 新增 16 全绿。

---

### Task 4: 前端 `formatLastActive`

**Files:**
- Modify: `app/lib/core/format.dart`(文件末尾)
- Test: `app/test/core/format_test.dart`(main() 内追加)

**Interfaces:**
- Produces: `String formatLastActive(DateTime time, {DateTime? now})` → 刚刚 / x 分钟前 / x 小时前 / x 天前

- [ ] **Step 1: 写失败测试**

`app/test/core/format_test.dart` 的 `main()` 内追加:

```dart
  test('formatLastActive 按间隔返回相对时间', () {
    final now = DateTime(2026, 9, 13, 14, 0);
    expect(formatLastActive(now.subtract(const Duration(seconds: 30)), now: now), '刚刚');
    expect(formatLastActive(now.subtract(const Duration(minutes: 5)), now: now), '5 分钟前');
    expect(formatLastActive(now.subtract(const Duration(hours: 3)), now: now), '3 小时前');
    expect(formatLastActive(now.subtract(const Duration(days: 2)), now: now), '2 天前');
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run(cwd = `app/`): `../flutter/bin/flutter.bat test test/core/format_test.dart`
Expected: FAIL(`formatLastActive` 未定义)

- [ ] **Step 3: 写实现**

`app/lib/core/format.dart` 末尾追加:

```dart
/// 最后活跃:刚刚 / x 分钟前 / x 小时前 / x 天前(在线状态文案用;7 天外数据已过期)。
String formatLastActive(DateTime time, {DateTime? now}) {
  final diff = (now ?? DateTime.now()).difference(time);
  if (diff.inMinutes < 1) return '刚刚';
  if (diff.inMinutes < 60) return '${diff.inMinutes} 分钟前';
  if (diff.inHours < 24) return '${diff.inHours} 小时前';
  return '${diff.inDays} 天前';
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `../flutter/bin/flutter.bat test test/core/format_test.dart`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add app/lib/core/format.dart app/test/core/format_test.dart
git commit -m "feat(presence): formatLastActive 相对时间文案"
```

---

### Task 5: presence 模型 + repository

**Files:**
- Create: `app/lib/features/presence/models.dart`、`app/lib/features/presence/presence_repository.dart`
- Test: `app/test/features/presence/presence_repository_test.dart`

**Interfaces:**
- Consumes: `core/api_client.dart` 的 `ApiClient.get(path, {query})`、`core/providers.dart` 的 `apiClientProvider`
- Produces(后续任务依赖的确切签名):
  - `class Presence { const Presence({required bool online, DateTime? lastActiveAt}); factory Presence.fromJson(Map<String, dynamic>) }`
  - `String? presenceLabel(Presence? presence, {DateTime? now})`(在线「● 在线」;离线有最后活跃「x 分钟前在线」;未知 null)
  - `PresenceRepository.fetchPresence(List<int> userIds) -> Future<Map<int, Presence>>`
  - `presenceRepositoryProvider`

- [ ] **Step 1: 写失败测试**

新建 `app/test/features/presence/presence_repository_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/features/presence/models.dart';
import 'package:chatapp_app/features/presence/presence_repository.dart';

import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late PresenceRepository repository;

  setUp(() {
    adapter = ScriptedAdapter({});
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    repository = PresenceRepository(ApiClient(dio));
  });

  test('fetchPresence 解析 results 并按逗号拼 user_ids', () async {
    adapter.routes['GET /presence'] = (options) => ok({
          'results': [
            {'user_id': 9, 'online': true, 'last_active_at': '2026-09-13T14:30:00+08:00'},
            {'user_id': 10, 'online': false, 'last_active_at': '2026-09-13T11:02:10+08:00'},
            {'user_id': 11, 'online': false, 'last_active_at': null},
          ],
        });

    final map = await repository.fetchPresence([9, 10, 11]);

    expect(map.keys, containsAll([9, 10, 11]));
    expect(map[9]!.online, isTrue);
    expect(map[10]!.online, isFalse);
    expect(map[10]!.lastActiveAt, DateTime.parse('2026-09-13T11:02:10+08:00'));
    expect(map[11]!.lastActiveAt, isNull);
    expect(adapter.log.last.queryParameters, {'user_ids': '9,10,11'});
  });

  test('空列表不发请求', () async {
    expect(await repository.fetchPresence(const []), isEmpty);
    expect(adapter.log, isEmpty);
  });

  test('presenceLabel:在线 / 离线带时间 / 未知三种形态', () {
    final now = DateTime(2026, 9, 13, 14, 0);
    expect(
        presenceLabel(const Presence(online: true), now: now), '● 在线');
    expect(
        presenceLabel(
            Presence(online: false, lastActiveAt: now.subtract(const Duration(minutes: 5))),
            now: now),
        '5 分钟前在线');
    expect(presenceLabel(const Presence(online: false), now: now), isNull);
    expect(presenceLabel(null), isNull);
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `../flutter/bin/flutter.bat test test/features/presence/presence_repository_test.dart`
Expected: FAIL(文件/类不存在)

- [ ] **Step 3: 写实现**

新建 `app/lib/features/presence/models.dart`:

```dart
import '../../core/format.dart';

/// 一个人的在线状态:online = 最近 2 分钟内 App 有活动。
class Presence {
  const Presence({required this.online, this.lastActiveAt});

  factory Presence.fromJson(Map<String, dynamic> json) => Presence(
        online: json['online'] as bool? ?? false,
        lastActiveAt: json['last_active_at'] == null
            ? null
            : DateTime.tryParse(json['last_active_at'] as String),
      );

  final bool online;
  final DateTime? lastActiveAt;
}

/// 展示文案:在线「● 在线」;离线有最后活跃「x 分钟前在线」;未知 → null(不显示)。
String? presenceLabel(Presence? presence, {DateTime? now}) {
  if (presence == null) return null;
  if (presence.online) return '● 在线';
  final at = presence.lastActiveAt;
  if (at == null) return null;
  return '${formatLastActive(at, now: now)}在线';
}
```

新建 `app/lib/features/presence/presence_repository.dart`:

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/api_client.dart';
import '../../core/providers.dart';
import 'models.dart';

/// 在线状态批量查询的纯 IO 封装。
class PresenceRepository {
  PresenceRepository(this._api);

  final ApiClient _api;

  /// 返回 user_id → Presence;接口省略的人(拉黑/不存在)没有条目。
  Future<Map<int, Presence>> fetchPresence(List<int> userIds) async {
    if (userIds.isEmpty) return const {};
    final data = await _api.get('/presence', query: {'user_ids': userIds.join(',')})
        as Map<String, dynamic>;
    return {
      for (final item in (data['results'] as List<dynamic>).cast<Map<String, dynamic>>())
        item['user_id'] as int: Presence.fromJson(item),
    };
  }
}

final presenceRepositoryProvider = Provider<PresenceRepository>(
    (ref) => PresenceRepository(ref.watch(apiClientProvider)));
```

- [ ] **Step 4: 跑测试确认通过**

Run: `../flutter/bin/flutter.bat test test/features/presence/presence_repository_test.dart`
Expected: PASS(3 个用例)

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/presence/models.dart app/lib/features/presence/presence_repository.dart app/test/features/presence/presence_repository_test.dart
git commit -m "feat(presence): Presence 模型 + 批量查询 repository"
```

---

### Task 6: 共享 PresenceController(登记合并 / 45s 刷新 / 容错)

**Files:**
- Create: `app/lib/features/presence/presence_controller.dart`
- Modify: `app/test/support/harness.dart`(pumpApp 的 overrides 加一行,默认关周期刷新)
- Test: `app/test/features/presence/presence_controller_test.dart`

**Interfaces:**
- Consumes: `presenceRepositoryProvider`(Task 5)、`baseDioProvider`(测试 override)
- Produces:
  - `presenceRefreshIntervalProvider`(`Provider<Duration?>`,默认 45 秒;override 成 null 关周期刷新)
  - `presenceProvider`(`NotifierProvider.autoDispose<PresenceController, Map<int, Presence>>`)
  - `PresenceController.track(String owner, List<int> userIds) -> void`、`PresenceController.refresh() -> Future<void>`
  - **不变量:`track()` 绝不同步改 state**(页面会在 build 里调用;state 只在异步拉取返回后写)

- [ ] **Step 1: 写失败测试**

新建 `app/test/features/presence/presence_controller_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/presence/presence_controller.dart';

import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;

  ProviderContainer makeContainer({Duration? interval}) {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      presenceRefreshIntervalProvider.overrideWithValue(interval),
    ]);
    // autoDispose provider 没有监听者会被立刻回收;测试里挂一个空监听保持存活
    container.listen(presenceProvider, (_, _) {}, fireImmediately: true);
    addTearDown(container.dispose);
    return container;
  }

  int presenceRequests() =>
      adapter.log.where((r) => r.path == '/presence').length;

  setUp(() {
    adapter = ScriptedAdapter({
      'GET /presence': (options) => ok({
            'results': [
              {'user_id': 1, 'online': true, 'last_active_at': '2026-09-13T14:30:00+08:00'},
            ],
          }),
    });
  });

  test('多个页面登记的人合并去重成一次请求', () async {
    final container = makeContainer();
    final notifier = container.read(presenceProvider.notifier);

    notifier.track('chats', [1, 2]);
    notifier.track('chat:u3', [2, 3]);
    await Future<void>.delayed(const Duration(milliseconds: 20));   // 等合并后的那次拉取跑完

    final requests = adapter.log.where((r) => r.path == '/presence').toList();
    expect(requests, hasLength(1));
    expect((requests.single.queryParameters['user_ids'] as String).split(','),
        containsAll(['1', '2', '3']));
    expect(container.read(presenceProvider)[1]!.online, isTrue);
  });

  test('track 同集合重复调用不重复发请求', () async {
    final container = makeContainer();
    final notifier = container.read(presenceProvider.notifier);
    notifier.track('chats', [1]);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(presenceRequests(), 1);

    notifier.track('chats', [1]);   // 内容没变 → 无操作
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(presenceRequests(), 1);
  });

  test('拉取失败保留旧值', () async {
    final container = makeContainer();
    final notifier = container.read(presenceProvider.notifier);
    notifier.track('chats', [1]);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(container.read(presenceProvider)[1], isNotNull);

    adapter.routes['GET /presence'] = offline;
    await notifier.refresh();   // 失败
    expect(container.read(presenceProvider)[1], isNotNull);   // 旧值还在
  });

  test('接口省略的人会被清掉(拉黑后不再显示)', () async {
    final container = makeContainer();
    final notifier = container.read(presenceProvider.notifier);
    notifier.track('chats', [1]);
    await Future<void>.delayed(const Duration(milliseconds: 20));
    expect(container.read(presenceProvider)[1], isNotNull);

    adapter.routes['GET /presence'] = (options) => ok({'results': []});
    await notifier.refresh();
    expect(container.read(presenceProvider).containsKey(1), isFalse);
  });

  test('周期定时器按间隔自动刷新', () async {
    final container = makeContainer(interval: const Duration(milliseconds: 30));
    container.read(presenceProvider.notifier).track('chats', [1]);
    await Future<void>.delayed(const Duration(milliseconds: 110));
    expect(presenceRequests(), greaterThanOrEqualTo(3));   // 立即一次 + 周期 ≥2 次
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `../flutter/bin/flutter.bat test test/features/presence/presence_controller_test.dart`
Expected: FAIL(`presence_controller.dart` 不存在)

- [ ] **Step 3: 写实现**

新建 `app/lib/features/presence/presence_controller.dart`:

```dart
import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'models.dart';
import 'presence_repository.dart';

/// 刷新间隔;override 成 null 关闭周期刷新(测试默认关,同步长心跳)。
final presenceRefreshIntervalProvider =
    Provider<Duration?>((ref) => const Duration(seconds: 45));

/// 共享在线状态缓存:各页面在自己的 build 里 `track(owner, ids)` 登记关心的人,
/// 合并去重后统一拉取。autoDispose:没有页面 watch 时定时器随之取消。
class PresenceController extends Notifier<Map<int, Presence>> {
  final Map<String, List<int>> _owners = {};
  Timer? _timer;
  bool _fetchScheduled = false;

  @override
  Map<int, Presence> build() {
    ref.onDispose(() => _timer?.cancel());
    return const {};
  }

  /// 登记某个页面(owner)关心的 userIds。只更新内部集合、**不在这里同步改 state**
  /// —— 它会被页面在 build 里调用,同步改 provider 会触发 Riverpod 断言;
  /// state 只在异步拉取返回后写。
  void track(String owner, List<int> userIds) {
    final current = _owners[owner];
    if (current != null &&
        current.length == userIds.length &&
        userIds.every(current.contains)) {
      return;
    }
    _owners[owner] = List.of(userIds);
    _startTimer();
    _scheduleFetch();
  }

  void _startTimer() {
    if (_timer != null) return;
    final interval = ref.read(presenceRefreshIntervalProvider);
    if (interval == null || interval <= Duration.zero) return;
    _timer = Timer.periodic(interval, (_) => refresh());
  }

  /// 同帧多次 track 合并成一次请求。
  void _scheduleFetch() {
    if (_fetchScheduled) return;
    _fetchScheduled = true;
    Future.microtask(() async {
      _fetchScheduled = false;
      await refresh();
    });
  }

  /// 拉一轮;失败保留旧值、下个周期再试(点缀信息,不弹提示)。
  Future<void> refresh() async {
    final ids = <int>{for (final list in _owners.values) ...list}.toList();
    if (ids.isEmpty) return;
    try {
      final fresh = await ref.read(presenceRepositoryProvider).fetchPresence(ids);
      final next = Map<int, Presence>.from(state)
        ..removeWhere((id, _) => ids.contains(id));
      next.addAll(fresh);
      state = next;
    } catch (_) {
      // 网络抖动:保持旧数据,别打扰用户
    }
  }
}

final presenceProvider =
    NotifierProvider.autoDispose<PresenceController, Map<int, Presence>>(
        PresenceController.new);
```

`app/test/support/harness.dart`:在 `pumpApp` 的 overrides 里、心跳那行下面加(import 补 `package:chatapp_app/features/presence/presence_controller.dart`):

```dart
      // 同样默认关掉在线状态的周期刷新;需要测定时的用例自己 override
      presenceRefreshIntervalProvider.overrideWithValue(null),
```

- [ ] **Step 4: 跑测试确认通过 + 全量前端回归**

Run: `../flutter/bin/flutter.bat test test/features/presence/`
Expected: PASS(5 个用例)
Run: `../flutter/bin/flutter.bat test`
Expected: 基线 170 全部仍绿(pumpApp 改了默认 overrides,若有用例断言请求条数需检查;已知纪律:断言用 `lastWhere((r) => r.method == 'POST')`,不受影响)

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/presence/presence_controller.dart app/test/features/presence/presence_controller_test.dart app/test/support/harness.dart
git commit -m "feat(presence): 共享 PresenceController(登记合并/45s 刷新/失败保留旧值)"
```

---

### Task 7: 消息列表绿点

**Files:**
- Create: `app/lib/features/presence/online_dot.dart`
- Modify: `app/lib/features/chat/chats_page.dart`(`_Avatar` 加 online 参数;`_ConversationList` 接线;`_RecentStrip`/`_ConversationTile` 传参)
- Test: `app/test/features/chat/chats_page_test.dart`(追加用例 + 该文件 `_adapter()` 里补 `'GET /presence'` 路由)

**Interfaces:**
- Consumes: `presenceProvider`、`Presence`(Task 5/6);`matchCacheProvider` 的 `MatchEntry.userId`(已有)
- Produces: `class OnlineDot extends StatelessWidget { const OnlineDot({super.key, this.size = 12}) }`(测试用 `find.byType(OnlineDot)` 断言)

- [ ] **Step 1: 写失败测试**

`app/test/features/chat/chats_page_test.dart` 的 `_adapter()` 路由表里加(默认离线,个别用例覆盖):

```dart
      'GET /presence': (options) => ok({'results': []}),
```

文件顶部 import 加 `package:chatapp_app/features/presence/online_dot.dart`。`main()` 内追加:

```dart
  testWidgets('在线的人头像带绿点;离线与系统通知没有', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation(), _systemConversation()];
    final adapter = _adapter();
    adapter.routes['GET /presence'] = (options) => ok({
          'results': [
            {'user_id': 9, 'online': true, 'last_active_at': '2026-09-13T14:30:00+08:00'},
          ],
        });
    await pumpApp(tester, adapter, prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    // 横滑条 + 列表行各一个绿点;系统通知(非真人)没有
    expect(find.byType(OnlineDot), findsNWidgets(2));
  });

  testWidgets('离线不显示绿点', (tester) async {
    final fake = FakeImClient()..conversations = [_conversation()];
    final adapter = _adapter();   // 默认 'GET /presence' 返回空
    await pumpApp(tester, adapter, prefs: _loggedIn, imClient: fake);
    await tester.pumpAndSettle();
    await tester.tap(navTab('消息'));
    await tester.pumpAndSettle();

    expect(find.byType(OnlineDot), findsNothing);
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `../flutter/bin/flutter.bat test test/features/chat/chats_page_test.dart`
Expected: FAIL(`OnlineDot` 不存在)

- [ ] **Step 3: 写实现**

新建 `app/lib/features/presence/online_dot.dart`:

```dart
import 'package:flutter/material.dart';

/// 头像右下角的在线绿点(白描边);离线时由调用方决定不渲染。
class OnlineDot extends StatelessWidget {
  const OnlineDot({super.key, this.size = 12});

  final double size;

  @override
  Widget build(BuildContext context) => Container(
        width: size,
        height: size,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: const Color(0xFF34C759),
          border: Border.all(color: Colors.white, width: 2),
        ),
      );
}
```

`app/lib/features/chat/chats_page.dart`:

1) import 加:
```dart
import '../presence/models.dart';
import '../presence/online_dot.dart';
import '../presence/presence_controller.dart';
```

2) `_Avatar` 加 `online` 参数并叠加绿点:

```dart
class _Avatar extends StatelessWidget {
  const _Avatar({required this.name, this.url, this.size = 48, this.online = false});

  final String name;
  final String? url;
  final double size;
  final bool online;
```

build 整体改为(先算 avatar,再决定叠不叠绿点):

```dart
  @override
  Widget build(BuildContext context) {
    final radius = size / 2;
    final Widget avatar = (url != null && url!.isNotEmpty)
        ? CircleAvatar(
            radius: radius,
            backgroundImage: NetworkImage(url!),
            onBackgroundImageError: (error, stack) {},
          )
        : CircleAvatar(
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
    if (!online) return avatar;
    return Stack(
      clipBehavior: Clip.none,
      children: [
        avatar,
        Positioned(right: 0, bottom: 0, child: OnlineDot(size: size * 0.28)),
      ],
    );
  }
```

3) `_ConversationList`:watch presence、登记 ids、把 map 传下去:

```dart
    final conversations = ref.watch(conversationsProvider);
    final cache = ref.watch(matchCacheProvider).value ?? const <String, MatchEntry>{};
    final presenceById = ref.watch(presenceProvider);
```

`data: (items) {` 里、拆出 `system`/`others` 之后:

```dart
        final ids = <int>[];
        for (final item in others) {
          final entry = cache[item.peerId];
          if (entry != null) ids.add(entry.userId);
        }
        ref.read(presenceProvider.notifier).track('chats', ids);
```

传参改为:`_RecentStrip(friends: others, cache: cache, presenceById: presenceById)`、
`_ConversationTile(conversation: others[i], cache: cache, presenceById: presenceById)`。

4) `_RecentStrip` / `_ConversationTile` 加字段 `final Map<int, Presence> presenceById;`,计算并传给 `_Avatar`:

```dart
    final entry = cache[conversation.peerId];
    final online = entry != null && (presenceById[entry.userId]?.online ?? false);
```

`_Avatar(name: name, url: avatar, size: 48, online: online)` / `_Avatar(name: name, url: avatar, online: online)`。

- [ ] **Step 4: 跑测试确认通过**

Run: `../flutter/bin/flutter.bat test test/features/chat/chats_page_test.dart`
Expected: PASS(含既有用例)

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/presence/online_dot.dart app/lib/features/chat/chats_page.dart app/test/features/chat/chats_page_test.dart
git commit -m "feat(presence): 消息列表头像在线绿点(横滑条+会话行)"
```

---

### Task 8: 聊天页标题在线小字

**Files:**
- Modify: `app/lib/features/chat/chat_page.dart`(build 内接线 + AppBar title)
- Test: `app/test/features/chat/chat_page_test.dart`(追加用例 + 该文件 setUp 的 adapter 路由表补 `'GET /presence'`)

**Interfaces:**
- Consumes: `presenceProvider`、`presenceLabel()`(Task 5/6);`matchCacheProvider` 的 `MatchEntry.userId`
- Produces: 无新接口

- [ ] **Step 1: 写失败测试**

`app/test/features/chat/chat_page_test.dart` 的 setUp adapter 路由表里加:

```dart
      'GET /presence': (options) => ok({'results': []}),
```

`main()` 内追加(顶部 import 补 `package:chatapp_app/features/presence/presence_controller.dart` 不需要,测试只铺路由):

```dart
  testWidgets('对方在线 → 标题下「● 在线」', (tester) async {
    adapter.routes['GET /presence'] = (options) => ok({
          'results': [
            {'user_id': 9, 'online': true, 'last_active_at': '2026-09-13T14:30:00+08:00'},
          ],
        });
    await pumpChat(tester);

    expect(find.text('● 在线'), findsOneWidget);
  });

  testWidgets('对方离线 → 「x 分钟前在线」', (tester) async {
    final fiveMinAgo = DateTime.now().subtract(const Duration(minutes: 5));
    adapter.routes['GET /presence'] = (options) => ok({
          'results': [
            {'user_id': 9, 'online': false, 'last_active_at': fiveMinAgo.toIso8601String()},
          ],
        });
    await pumpChat(tester);

    expect(find.text('5 分钟前在线'), findsOneWidget);
  });

  testWidgets('拿不到状态 → 不显示小字', (tester) async {
    await pumpChat(tester);   // 默认返回空 results

    expect(find.text('● 在线'), findsNothing);
    expect(find.textContaining('分钟前在线'), findsNothing);
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `../flutter/bin/flutter.bat test test/features/chat/chat_page_test.dart`
Expected: FAIL(`● 在线` 找不到)

- [ ] **Step 3: 写实现**

`app/lib/features/chat/chat_page.dart`:import 加:

```dart
import '../presence/models.dart';
import '../presence/presence_controller.dart';
```

`build` 里、`final peerName = ...` 之后:

```dart
    final presenceById = ref.watch(presenceProvider);
    final peerUserId = cache[widget.peerId]?.userId;
    if (peerUserId != null) {
      ref.read(presenceProvider.notifier).track('chat:${widget.peerId}', [peerUserId]);
    }
    final peerPresence = peerUserId == null ? null : presenceById[peerUserId];
    final peerStatusLabel = presenceLabel(peerPresence);
```

AppBar `title` 改为:

```dart
        title: InkWell(
          key: const Key('chat.title'),
          onTap: () => _openProfile(context, cache),
          child: peerStatusLabel == null
              ? Text(peerName)
              : Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(peerName),
                    Text(
                      peerStatusLabel,
                      style: TextStyle(
                        fontSize: 11,
                        color: peerPresence!.online
                            ? const Color(0xFF34C759)
                            : const Color(0xFF8A8F98),
                      ),
                    ),
                  ],
                ),
        ),
```

- [ ] **Step 4: 跑测试确认通过**

Run: `../flutter/bin/flutter.bat test test/features/chat/chat_page_test.dart`
Expected: PASS(含既有用例)

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/chat/chat_page.dart app/test/features/chat/chat_page_test.dart
git commit -m "feat(presence): 聊天页标题下在线小字(● 在线 / x 分钟前在线)"
```

---

### Task 9: 发现卡在线标识

**Files:**
- Modify: `app/lib/features/discovery/widgets/profile_card.dart`(加 `presence` 参数 + 昵称行渲染)
- Modify: `app/lib/features/discovery/widgets/swipe_deck.dart`(加 `presenceById` 参数并透传)
- Modify: `app/lib/features/discovery/discovery_page.dart`(`_DeckView` 接线)
- Test: `app/test/features/discovery/profile_card_test.dart`(追加用例;`_wrap` 加可选 presence 参数)

**Interfaces:**
- Consumes: `Presence`/`presenceLabel`(Task 5)、`presenceProvider`(Task 6)
- Produces: `ProfileCard({required Candidate candidate, Presence? presence})`、`SwipeDeck({required List<Candidate> candidates, required DecideCallback onDecide, Map<int, Presence> presenceById = const {}})`

- [ ] **Step 1: 写失败测试**

`app/test/features/discovery/profile_card_test.dart`:顶部 import 加
`package:chatapp_app/features/presence/models.dart`;`_wrap` 改为:

```dart
Widget _wrap(Candidate candidate, {Presence? presence}) => MaterialApp(
      home: Scaffold(
        body: Center(
          child: SizedBox(
              width: 360, height: 560,
              child: ProfileCard(candidate: candidate, presence: presence)),
        ),
      ),
    );
```

`main()` 内追加:

```dart
  testWidgets('在线 → 昵称旁「● 在线」', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(nickname: '小红', age: 25));
    await tester.pumpWidget(
        _wrap(candidate, presence: const Presence(online: true)));
    await tester.pump();

    expect(find.text('● 在线'), findsOneWidget);
  });

  testWidgets('离线 → 「x 分钟前在线」;未知 → 不显示', (tester) async {
    final candidate = Candidate.fromJson(candidateJson(nickname: '小红', age: 25));
    final now = DateTime.now();
    await tester.pumpWidget(_wrap(candidate,
        presence: Presence(
            online: false, lastActiveAt: now.subtract(const Duration(minutes: 5)))));
    await tester.pump();
    expect(find.text('5 分钟前在线'), findsOneWidget);

    await tester.pumpWidget(_wrap(candidate));
    await tester.pump();
    expect(find.textContaining('在线'), findsNothing);
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `../flutter/bin/flutter.bat test test/features/discovery/profile_card_test.dart`
Expected: FAIL(`presence` 参数不存在 / 文案找不到)

- [ ] **Step 3: 写实现**

`profile_card.dart`:import 加 `../../presence/models.dart`;构造函数加参数:

```dart
  const ProfileCard({super.key, required this.candidate, this.presence});

  final Candidate candidate;
  final Presence? presence;
```

build 里 `final photo = ...` 附近加:

```dart
    final statusLabel = presenceLabel(presence);
```

把昵称 Text 替换为 Row(在资料区 Column 的第一个 child 位置):

```dart
                  Row(
                    children: [
                      Flexible(
                        child: Text(
                          candidate.age == null
                              ? candidate.nickname
                              : '${candidate.nickname},${candidate.age}',
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(
                              color: Colors.white, fontSize: 22, fontWeight: FontWeight.bold),
                        ),
                      ),
                      if (statusLabel != null) ...[
                        const SizedBox(width: 8),
                        Text(
                          statusLabel,
                          style: TextStyle(
                            fontSize: 13,
                            color: (presence?.online ?? false)
                                ? const Color(0xFF4CD964)
                                : Colors.white70,
                          ),
                        ),
                      ],
                    ],
                  ),
```

`swipe_deck.dart`:import 加 `../../presence/models.dart`;构造加参数:

```dart
  const SwipeDeck({super.key, required this.candidates, required this.onDecide,
      this.presenceById = const {}});

  final Map<int, Presence> presenceById;
```

两处 `ProfileCard(...)` 改为传 presence:

```dart
                  Transform.scale(scale: 0.95,
                      child: ProfileCard(candidate: second,
                          presence: widget.presenceById[second.userId])),
```

```dart
                      child: ProfileCard(candidate: top,
                          presence: widget.presenceById[top.userId]),
```

`discovery_page.dart`:`_DeckView.build` 里 `final deck = ref.watch(discoveryProvider);` 后加:

```dart
    final presenceById = ref.watch(presenceProvider);
```

`data: (candidates) {` 的 `=>` 分支改为块体(SwipeDeck 调用前登记):

```dart
      data: (candidates) {
        ref.read(presenceProvider.notifier).track(
            'discovery', [for (final candidate in candidates) candidate.userId]);
        return candidates.isEmpty
            ? _EmptyView(
                onRefresh: () => ref.read(discoveryProvider.notifier).reload())
            : SwipeDeck(
                candidates: candidates,
                presenceById: presenceById,
                onDecide: (candidate, {required like}) =>
                    _decide(context, ref, candidate, like: like),
              );
      },
```

import 加 `../presence/presence_controller.dart`。

- [ ] **Step 4: 跑测试确认通过**

Run: `../flutter/bin/flutter.bat test test/features/discovery/`
Expected: PASS(含既有用例)

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/discovery/widgets/profile_card.dart app/lib/features/discovery/widgets/swipe_deck.dart app/lib/features/discovery/discovery_page.dart app/test/features/discovery/profile_card_test.dart
git commit -m "feat(presence): 发现卡昵称旁在线标识"
```

---

### Task 10: 全量回归 + CLAUDE.md + 手测

**Files:**
- Modify: `CLAUDE.md`(新增「在线状态(最后活跃)」一节)
- Modify: `docs/superpowers/plans/2026-09-13-online-presence.md`(本文件,勾选已完成项)

**Interfaces:**
- Consumes: 全部前序任务
- Produces: 交付记录

- [ ] **Step 1: 双端全量回归**

```bash
cd chatapp && python manage.py test          # 期望 310 + 16 = 326 全绿
cd ../app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test
```

Expected: 后端 326 绿;`flutter analyze` 零告警;前端 170 + 16 = 186 绿。
若前端有别处用例因页面调了 `track` 而发 `/presence` 请求、又没铺该路由导致失败(404 兜底只影响断言请求数的用例),给对应测试文件补一行 `'GET /presence': (options) => ok({'results': []}),`。

- [ ] **Step 2: 手测(双模拟器 + 后端已起)**

前置:Redis 容器、runserver(:8000)、Celery worker 都在跑;两台模拟器(5554/5556)各登录一个账号(可用 `python manage.py seed_fake_users` 造的号;各自完善资料)。

1. A 端打开 App(保持前台)→ B 端刷新消息列表:A 头像右下角绿点;进聊天页标题下「● 在线」;发现页滑到 A 的卡:「● 在线」。
2. A 杀 App(adb shell am force-stop chatapp_app)→ 等 ≤2 分钟 + 一个 B 端刷新周期:B 端绿点消失,聊天页变「x 分钟前在线」。
3. A 重开 App → B 端 ≤45 秒绿点回来。
4. B 拉黑 A(或反向)→ B 端 A 的绿点/文案消失(接口省略)。
5. 双设备登同一账号(顶号)→ 被顶端退登录页;另一端查看该账号 ≤2 分钟转离线。

- [ ] **Step 3: 更新 CLAUDE.md**

在「## 广场页(动态流)(2026-09-12 新增)」之后新增一节(内容按交付实际情况微调):

```markdown
## 在线状态(最后活跃)(2026-09-13 新增)

- **自建路线**:Redis 键 `presence:{user_id}` = 最后活跃 Unix 秒(TTL 7 天);写入点唯一 —— `accounts/authentication.py::SessionJwtAuthentication.get_user()` 校验通过后 `users/presence.py::touch()`(被顶号旧令牌 401 时**不写**)。**前端零上报**:45 秒登录态心跳 + 日常请求天然就是"我在线"信号。没走腾讯 IM 在线状态(需付费套餐 + 控制台开关,且没有「最后活跃时间」)。
- **「在线」判据**:最近 120 秒内有认证请求(`ONLINE_WINDOW_SECONDS`,45s 心跳 ×2 + 余量)。App 被杀/后台被冻结 → ≤2 分钟转离线并显示「x 分钟前在线」。
- **接口**:`GET /api/v1/presence?user_ids=3,5,7`(逗号分隔,去重后 ≤100);省略规则:被拉黑(双向)/不存在/自己/重封禁;Redis 挂 → 全部 null 不 500;限流 scope `presence`(env `PRESENCE_RATE`,默认 600/hour)。
- **前端**:`features/presence/`(模型 + repo + 共享 autoDispose `PresenceController`)。页面在 build 里 `track('owner', ids)` 登记,多页面**合并去重后一次请求**,45 秒周期刷新;`track()` 不同步改 state(页面在 build 里调);失败保留旧值不弹提示。间隔 `presenceRefreshIntervalProvider`(测试在 pumpApp 里 override 成 null)。
- **三处展示**:消息列表头像右下角绿点(`OnlineDot`,`find.byType` 断言)、聊天页标题下小字、发现卡昵称旁;文案 `presenceLabel()`:在线「● 在线」/ 离线「x 分钟前在线」(`formatLastActive`:刚刚 / x 分钟前 / x 小时前 / x 天前)。
- 测试:后端 +16(服务层/钩子/接口);前端 +16(repo/controller/三处 UI);手测:杀 App ≤2 分钟转离线、拉黑后不可见、顶号转离线。
```

- [ ] **Step 4: 勾选本计划并提交**

```bash
git add CLAUDE.md docs/superpowers/plans/2026-09-13-online-presence.md
git commit -m "docs: 在线状态交付记录(CLAUDE.md + 计划勾选)"
```
