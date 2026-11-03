# 「谁看过我」访客记录 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户能看到「谁看过我的资料页」——App 与 Web 双端入口 + 列表页 + 「隐身浏览」开关，后端在现有资料页访问链路上落库并按 30 分钟窗口去重。

**Architecture:** 新表 `users.ProfileVisit`（viewer/owner 唯一，每人一行）由 `users.services.record_profile_view` 在 `GET /users/{id}` 时顺带写入；列表口径集中在 `discovery.services.visits_received_queryset`，两个新读接口 `/discovery/visits` 与 `/discovery/visits/count` 与 `/discovery/likes` 完全同构；隐身开关复用 `GET/PATCH /users/me` 的 `visits_hidden` 字段。

**Tech Stack:** Django 5.2 + DRF（MySQL 8 / Redis）· Flutter 3.47（Riverpod / go_router）· Vue 3 + Pinia + TypeScript（vitest + MSW）

## Global Constraints

- 设计文档：`docs/superpowers/archive/specs/2026-11-01-profile-visits-design.md`（实现与它冲突时以文档为准，先改文档再改代码）
- **注释规范**：新增/修改任何 `.py` 文件，同一次改动内补齐模块 docstring 与函数/类 docstring（`test_*`、`setUp`、`Meta` 豁免），公开函数带参数必须写 `Args:`；`CommentCoverageTests` 会拦
- **接口文档**：动任何 `/api/v1` 接口必须在同一次改动内更新 `docs/api/`；`ApiDocsCoverageTests` 会双向比对
- **错误契约**：失败一律 `{"code": <HTTP状态码>, "message": "<中文>", "request_id": ...}`；业务码 = 前 3 位 HTTP + 2 位序号
- **响应路径禁止第三方网络调用**；跨系统副作用走 Celery
- **UI 规则**：App 端一切视觉走 `app/lib/core/theme/*` 的 token，禁止裸 hex / 裸字号 / 裸间距；图标用 `*_rounded`
- **测试纪律**：后端 `python manage.py test` 全绿（前置 Redis）；App `flutter analyze` 零告警 + `flutter test` 全绿；Web `type-check` / `lint --max-warnings 0` / `test:run` 全绿
- 后端测试前置：`docker compose -f docker-compose.dev.yml up -d`（Redis）
- 版本号三处同改（App `pubspec.yaml` + `app_info.dart` + 关于页测试期望；Web `package.json`）——本计划**不**改版本号，发版时按老规矩单独处理
- 本次范围：App + Web + 后端 + 文档；不做推送、不做未读角标、不做次数统计

---

### Task 1: `ProfileVisit` 模型与迁移

**Files:**
- Modify: `chatapp/users/models.py`（文件末尾追加 `ProfileVisit`；`Profile` 类内加 `visits_hidden`）
- Create: `chatapp/users/migrations/00xx_profilevisit.py`（由 `makemigrations` 生成）
- Test: `chatapp/users/tests.py`（新增 `ProfileVisitModelTests`）

**Interfaces:**
- Produces: `users.models.ProfileVisit`（字段 `viewer` / `owner` / `first_at` / `last_at`，唯一约束 `uniq_visit_viewer_owner`）、`Profile.visits_hidden: bool`（默认 `False`）

- [ ] **Step 1: 写失败的模型测试**

在 `chatapp/users/tests.py` 末尾追加（文件已 import `User` / `Profile` / `ProfileStatus`，需要补 `ProfileVisit`）：

```python
class ProfileVisitModelTests(TestCase):
    """访客记录模型:默认值、唯一约束、按最近访问排序。"""

    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_visits_hidden_defaults_to_false(self):
        profile = Profile.objects.create(user=self.a, nickname="小明")
        self.assertFalse(profile.visits_hidden)

    def test_unique_viewer_owner_pair(self):
        ProfileVisit.objects.create(viewer=self.a, owner=self.b, last_at=timezone.now())
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProfileVisit.objects.create(viewer=self.a, owner=self.b, last_at=timezone.now())

    def test_ordered_by_last_at_desc(self):
        ProfileVisit.objects.create(viewer=self.a, owner=self.b, last_at=timezone.now())
        ProfileVisit.objects.create(viewer=self.b, owner=self.a, last_at=timezone.now())
        first = ProfileVisit.objects.first()
        self.assertEqual(first.viewer_id, self.b.id)
```

文件头需要补的 import（若尚未存在）：`from django.db import IntegrityError, transaction`、`from django.utils import timezone`、`from users.models import ProfileVisit`（本文件已用 `from users.models import ...` 形式，追加即可）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test users.tests.ProfileVisitModelTests -v 2`
Expected: FAIL —— `ImportError: cannot import name 'ProfileVisit'`

- [ ] **Step 3: 加模型字段与表**

`chatapp/users/models.py` 的 `Profile` 类里，`shuffle_key` 之后加：

```python
    # 隐身浏览:开启后自己的访问不写进任何人的访客列表(见 services.record_profile_view)
    visits_hidden = models.BooleanField("隐身浏览", default=False)
```

文件末尾追加：

```python
class ProfileVisit(models.Model):
    """一次「谁看过我」的访问记录。

    设计要点:
        1. **每人一行**:``(viewer, owner)`` 唯一,重复访问只刷新 ``last_at``,
           列表因此天然不会出现同一个人的多行;
        2. 写入按 30 分钟窗口节流(见 ``services.record_profile_view``),所以
           ``last_at`` 的精度是 30 分钟,不是「最后一次点击」的精确时刻;
        3. 保留期 90 天,由 ``manage.py purge_profile_visits`` 清理。

    Attributes:
        last_at: 最近一次访问时间;列表按它倒序。
    """

    viewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="visits_made")
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="visits_received")
    first_at = models.DateTimeField("首次访问", auto_now_add=True)
    last_at = models.DateTimeField("最近访问", db_index=True)

    class Meta:
        ordering = ["-last_at"]
        constraints = [
            models.UniqueConstraint(fields=["viewer", "owner"], name="uniq_visit_viewer_owner"),
        ]
        indexes = [
            models.Index(fields=["owner", "-last_at"], name="idx_visit_owner_last"),
        ]

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``visit(浏览者 id -> 被访问者 id)``。
        """
        return f"visit({self.viewer_id}->{self.owner_id})"
```

- [ ] **Step 4: 生成迁移**

Run: `cd chatapp && python manage.py makemigrations users`
Expected: `Create model ProfileVisit` + `Add field visits_hidden to profile`

- [ ] **Step 5: 跑测试确认通过**

Run: `cd chatapp && python manage.py test users.tests.ProfileVisitModelTests -v 2`
Expected: PASS（3 tests）

- [ ] **Step 6: 提交**

```bash
git add chatapp/users/models.py chatapp/users/migrations chatapp/users/tests.py
git commit -m "feat(visits): ProfileVisit 模型与 Profile.visits_hidden"
```

---

### Task 2: 写入路径（隐身 + 30 分钟去重 + 失败不影响响应）

**Files:**
- Modify: `chatapp/users/services.py`（`record_profile_view` 末尾追加落库；新增私有 `_record_visit`）
- Test: `chatapp/users/tests.py`（新增 `ProfileVisitWriteTests`）

**Interfaces:**
- Consumes: `users.models.ProfileVisit`、`Profile.visits_hidden`（Task 1）
- Produces: `record_profile_view(viewer_id: int, target_id: int) -> None` 语义不变（永不抛异常），副作用多一条落库；模块常量 `PROFILE_VISIT_TTL_SECONDS = 1800`、`PROFILE_VISIT_RETENTION_DAYS = 90`

- [ ] **Step 1: 写失败的测试**

`chatapp/users/tests.py` 追加（需要 `from unittest.mock import patch`，本文件已 import）：

```python
class ProfileVisitWriteTests(TestCase):
    """落库口径:30 分钟窗口、隐身、自看、异常兜底。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.viewer = User.objects.create_user(phone="13800138000")
        self.owner = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.viewer, nickname="小明")
        Profile.objects.create(user=self.owner, nickname="小红")

    def test_first_visit_creates_row(self):
        services.record_profile_view(self.viewer.id, self.owner.id)
        visit = ProfileVisit.objects.get(viewer=self.viewer, owner=self.owner)
        self.assertEqual(visit.first_at, visit.last_at)

    def test_second_visit_within_window_keeps_one_row(self):
        services.record_profile_view(self.viewer.id, self.owner.id)
        before = ProfileVisit.objects.get(viewer=self.viewer, owner=self.owner).last_at
        services.record_profile_view(self.viewer.id, self.owner.id)
        self.assertEqual(ProfileVisit.objects.count(), 1)
        after = ProfileVisit.objects.get(viewer=self.viewer, owner=self.owner).last_at
        self.assertEqual(before, after)

    def test_visit_after_window_updates_last_at(self):
        services.record_profile_view(self.viewer.id, self.owner.id)
        before = ProfileVisit.objects.get(viewer=self.viewer, owner=self.owner).last_at
        cache.delete(f"visit:{self.viewer.id}:{self.owner.id}")   # 模拟 30 分钟窗口过期
        services.record_profile_view(self.viewer.id, self.owner.id)
        self.assertEqual(ProfileVisit.objects.count(), 1)
        after = ProfileVisit.objects.get(viewer=self.viewer, owner=self.owner).last_at
        self.assertGreater(after, before)

    def test_incognito_viewer_is_not_recorded(self):
        profile = self.viewer.profile
        profile.visits_hidden = True
        profile.save(update_fields=["visits_hidden"])
        services.record_profile_view(self.viewer.id, self.owner.id)
        self.assertEqual(ProfileVisit.objects.count(), 0)

    def test_self_view_is_not_recorded(self):
        services.record_profile_view(self.viewer.id, self.viewer.id)
        self.assertEqual(ProfileVisit.objects.count(), 0)

    def test_write_failure_is_swallowed(self):
        with patch("users.services.ProfileVisit.objects.update_or_create",
                   side_effect=RuntimeError("db down")):
            services.record_profile_view(self.viewer.id, self.owner.id)   # 不抛即通过

    def test_missing_profile_is_treated_as_not_hidden(self):
        stranger = User.objects.create_user(phone="13900139002")   # 没有 Profile
        services.record_profile_view(stranger.id, self.owner.id)
        self.assertTrue(ProfileVisit.objects.filter(viewer=stranger).exists())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test users.tests.ProfileVisitWriteTests -v 2`
Expected: FAIL —— `ProfileVisit` 表存在但没有任何行被写入（`DoesNotExist` / `count() == 0` 断言失败）

- [ ] **Step 3: 实现落库**

`chatapp/users/services.py`：

顶部 import 区补 `from django.db import IntegrityError, transaction`（`transaction` 已有则只补 `IntegrityError`），模型 import 补 `ProfileVisit`：

```python
from .models import PhotoStatus, Preference, Profile, ProfileVisit
```

常量区补：

```python
# 访客记录:同一对 (viewer, owner) 30 分钟内只写一次,避免下拉刷新造成写放大。
PROFILE_VISIT_TTL_SECONDS = 1800
# 访客记录保留期:超过这个天数的行由 purge_profile_visits 清理。
PROFILE_VISIT_RETENTION_DAYS = 90
```

`record_profile_view` 的 docstring 末尾补一句，并在函数体最后追加调用（原有 Redis 监控逻辑保持不变）：

```python
    try:
        _record_visit(viewer_id, target_id)
    except Exception:
        logger.debug("访客记录失败(不影响响应)", exc_info=True)
```

在 `record_profile_view` 之后新增：

```python
def _record_visit(viewer_id: int, target_id: int) -> None:
    """把一次资料页访问写进 ``ProfileVisit``(每人一行,30 分钟窗口内只写一次)。

    隐身判断取 ``Profile.visits_hidden``:资料是懒创建的,取不到 profile 视为「未隐身」。
    写库放在内层 ``atomic()`` 里,失败只回滚到保存点,不会毒化外层事务
    (``GET /users/{id}`` 本身没有外层事务,但测试与嵌套调用有)。

    Args:
        viewer_id: 浏览者账号 id。
        target_id: 被浏览者账号 id。

    Returns:
        None。
    """
    if viewer_id == target_id:      # 自己看自己不算
        return
    hidden = (Profile.objects.filter(user_id=viewer_id)
              .values_list("visits_hidden", flat=True).first())
    if hidden:
        return
    if not cache.add(f"visit:{viewer_id}:{target_id}", 1, timeout=PROFILE_VISIT_TTL_SECONDS):
        return
    now = timezone.now()
    try:
        with transaction.atomic():
            ProfileVisit.objects.update_or_create(
                viewer_id=viewer_id, owner_id=target_id, defaults={"last_at": now})
    except IntegrityError:      # 并发插入撞唯一约束:退化成一次更新
        ProfileVisit.objects.filter(viewer_id=viewer_id, owner_id=target_id).update(last_at=now)
```

- [ ] **Step 4: 跑本类测试 + 既有抓取监控测试**

Run: `cd chatapp && python manage.py test users.tests.ProfileVisitWriteTests users.tests.ProfileScrapeMonitorTests users.tests.ProfileScrapeApiTests -v 2`
Expected: PASS（既有测试必须仍绿——它们用不存在的用户 id 调 `record_profile_view`，靠内层 savepoint 吞掉 FK 错误）

- [ ] **Step 5: 提交**

```bash
git add chatapp/users/services.py chatapp/users/tests.py
git commit -m "feat(visits): 资料页访问落库(30 分钟去重 + 隐身 + 失败兜底)"
```

---

### Task 3: 隐身开关（`GET/PATCH /users/me` 暴露 `visits_hidden`）

**Files:**
- Modify: `chatapp/users/serializers.py`（`ProfileSerializer.Meta.fields` + `ProfileUpdateSerializer` 字段）
- Test: `chatapp/users/tests.py`（`ProfileUpdateTests` 内加两个用例，`PublicProfileTests` 内加一个）

**Interfaces:**
- Produces: `GET /users/me` 响应含 `visits_hidden: bool`；`PATCH /users/me {"visits_hidden": true}` 可写；`GET /users/{id}` **不含**该字段

- [ ] **Step 1: 写失败的测试**

`ProfileUpdateTests` 内追加：

```python
    def test_toggle_visits_hidden(self):
        resp = self.client.patch("/api/v1/users/me", {"visits_hidden": True}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["visits_hidden"])
        self.me.profile.refresh_from_db()
        self.assertTrue(self.me.profile.visits_hidden)

    def test_visits_hidden_defaults_false_in_me(self):
        self.assertFalse(self.client.get("/api/v1/users/me").json()["visits_hidden"])
```

`PublicProfileTests` 内追加：

```python
    def test_public_profile_hides_visits_hidden(self):
        self.other.profile.visits_hidden = True
        self.other.profile.save(update_fields=["visits_hidden"])
        item = self.client.get(f"/api/v1/users/{self.other.id}").json()
        self.assertNotIn("visits_hidden", item)
```

（若 `PublicProfileTests` 里没有 `self.other`，用该类现有的造人方式，保持与相邻用例一致。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test users.tests.ProfileUpdateTests users.tests.PublicProfileTests -v 2`
Expected: FAIL —— `KeyError: 'visits_hidden'` / PATCH 后字段仍为 False

- [ ] **Step 3: 改两个序列化器**

`ProfileSerializer.Meta.fields` 末尾加 `"visits_hidden"`：

```python
        fields = ["id", "user_id", "phone", "nickname", "gender", "birthday", "age", "city", "bio",
                  "status", "ban_reason", "missing_fields", "tags", "photos", "preference",
                  "visits_hidden"]
```

`ProfileUpdateSerializer` 的字段区加：

```python
    visits_hidden = serializers.BooleanField(required=False)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test users.tests.ProfileUpdateTests users.tests.PublicProfileTests -v 2`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add chatapp/users/serializers.py chatapp/users/tests.py
git commit -m "feat(visits): /users/me 读写 visits_hidden,公开资料不泄漏"
```

---

### Task 4: 列表口径 + 序列化器 + 两个读接口

**Files:**
- Modify: `chatapp/discovery/services.py`（新增 `visits_received_queryset`）
- Modify: `chatapp/discovery/serializers.py`（新增 `VisitSerializer`）
- Modify: `chatapp/discovery/views.py`（新增 `visits` / `visits_count`）
- Modify: `chatapp/discovery/urls.py`（两条 path）
- Test: `chatapp/discovery/tests.py`（新增 `VisitsReceivedTests`）

**Interfaces:**
- Consumes: `users.models.ProfileVisit`（Task 1）、`record_profile_view`（Task 2）
- Produces:
  - `discovery.services.visits_received_queryset(me) -> QuerySet[ProfileVisit]`
  - `discovery.serializers.VisitSerializer`（`ModelSerializer` on `ProfileVisit`）
  - `GET /api/v1/discovery/visits`、`GET /api/v1/discovery/visits/count`

- [ ] **Step 1: 写失败的测试**

`chatapp/discovery/tests.py` 追加（顶部 import 补 `from users.models import ProfileVisit`）：

```python
class VisitsReceivedTests(APITestCase):
    """谁看过我:口径、排序、分页、计数、字段脱敏与权限。"""

    URL = "/api/v1/discovery/visits"
    COUNT_URL = "/api/v1/discovery/visits/count"

    def setUp(self):
        self.me = self._make_user("13800138000", gender="male")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, complete=True, photo=True, status=None):
        """造一个用户;默认资料完善并带一张已过审照片。

        Args:
            phone: 手机号,同时用作昵称。
            complete: 是否把资料置为完善。
            photo: 是否加一张已过审照片。
            status: 显式指定资料状态(用于封禁场景)。

        Returns:
            新建的用户实例。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(
            user=user, nickname=phone, gender="female", birthday="2000-01-01", city="上海",
            bio="你好",
            status=status or (ProfileStatus.COMPLETE if complete else ProfileStatus.INCOMPLETE),
        )
        if photo:
            Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def _visit(self, viewer, minutes_ago=0):
        """让 viewer 访问我一次。

        Args:
            viewer: 访客。
            minutes_ago: 访问发生在多少分钟前(用于排序断言)。

        Returns:
            写入的记录。
        """
        return ProfileVisit.objects.create(
            viewer=viewer, owner=self.me,
            last_at=timezone.now() - timedelta(minutes=minutes_ago))

    def _ids(self, resp):
        """取出列表响应里的 ``user_id``。

        Args:
            resp: 接口响应。

        Returns:
            user_id 列表,保持响应顺序。
        """
        return [item["user_id"] for item in resp.json()["results"]]

    def test_lists_visitors(self):
        a = self._make_user("13900139000")
        self._visit(a)
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), [a.id])

    def test_excludes_people_i_already_swiped(self):
        a = self._make_user("13900139000")
        self._visit(a)
        Swipe.objects.create(swiper=self.me, target=a, action=SwipeAction.PASS)
        self.assertEqual(self._ids(self.client.get(self.URL)), [])

    def test_excludes_matched_people(self):
        a = self._make_user("13900139000")
        self._visit(a)
        Swipe.objects.create(swiper=self.me, target=a, action=SwipeAction.LIKE)
        Swipe.objects.create(swiper=a, target=self.me, action=SwipeAction.LIKE)
        Match.objects.create(**Match.pair_kwargs(self.me, a))
        self.assertEqual(self._ids(self.client.get(self.URL)), [])

    def test_excludes_blocked_both_ways(self):
        a = self._make_user("13900139000")
        b = self._make_user("13900139001")
        self._visit(a)
        self._visit(b)
        Block.objects.create(blocker=self.me, blocked=a)
        Block.objects.create(blocker=b, blocked=self.me)
        self.assertEqual(self._ids(self.client.get(self.URL)), [])

    def test_excludes_incomplete_no_photo_and_banned(self):
        users = [
            self._make_user("13900139000", complete=False),
            self._make_user("13900139001", photo=False),
            self._make_user("13900139002", status=ProfileStatus.BANNED_LIGHT),
            self._make_user("13900139003", status=ProfileStatus.BANNED_HEAVY),
        ]
        for user in users:
            self._visit(user)
        self.assertEqual(self._ids(self.client.get(self.URL)), [])

    def test_newest_visit_first(self):
        a = self._make_user("13900139000")
        b = self._make_user("13900139001")
        self._visit(a, minutes_ago=30)
        self._visit(b, minutes_ago=1)
        self.assertEqual(self._ids(self.client.get(self.URL)), [b.id, a.id])

    def test_pagination(self):
        users = [self._make_user(f"1390013900{i}") for i in range(3)]
        for user in users:
            self._visit(user)
        first = self.client.get(self.URL, {"limit": 2})
        self.assertEqual(first.json()["count"], 3)
        self.assertEqual(len(first.json()["results"]), 2)
        self.assertIsNotNone(first.json()["next"])
        second = self.client.get(self.URL, {"limit": 2, "offset": 2})
        self.assertEqual(len(second.json()["results"]), 1)

    def test_count_uses_same_rules(self):
        a = self._make_user("13900139000")
        b = self._make_user("13900139001")
        self._visit(a)
        self._visit(b)
        Block.objects.create(blocker=self.me, blocked=b)
        self.assertEqual(self.client.get(self.COUNT_URL).json(), {"count": 1})
        self.assertEqual(self.client.get(self.URL).json()["count"], 1)

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.URL).status_code, 401)

    def test_heavy_banned_forbidden(self):
        self.me.profile.status = ProfileStatus.BANNED_HEAVY
        self.me.profile.save(update_fields=["status"])
        self.assertEqual(self.client.get(self.URL).status_code, 403)

    def test_light_banned_can_read(self):
        self.me.profile.status = ProfileStatus.BANNED_LIGHT
        self.me.profile.save(update_fields=["status"])
        self.assertEqual(self.client.get(self.URL).status_code, 200)

    def test_serializer_hides_private_fields_and_filters_photos(self):
        a = self._make_user("13900139000")
        Photo.objects.create(user=a, file="photos/pending.png", status=PhotoStatus.PENDING)
        self._visit(a)
        item = self.client.get(self.URL).json()["results"][0]
        self.assertEqual(item["im_user_id"], f"u{a.id}")
        self.assertIn("visited_at", item)
        for hidden in ("phone", "birthday", "ban_reason", "missing_fields", "visits_hidden"):
            self.assertNotIn(hidden, item)
        self.assertEqual([photo["status"] for photo in item["photos"]], ["approved"])

    def test_end_to_end_via_public_profile(self):
        a = self._make_user("13900139000")
        self.client.get(f"/api/v1/users/{a.id}")      # 我看他 → 他那边才该有记录
        self.assertEqual(self._ids(self.client.get(self.URL)), [])
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(a).access_token}")
        self.assertEqual(self._ids(self.client.get(self.URL)), [self.me.id])
```

文件头需要补的 import：`from datetime import timedelta`、`from django.utils import timezone`（若尚未存在）。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test discovery.tests.VisitsReceivedTests -v 2`
Expected: FAIL —— `404`（路由不存在）

- [ ] **Step 3: 加服务函数**

`chatapp/discovery/services.py` 顶部模型 import 补 `ProfileVisit`：

```python
from users.models import Photo, PhotoStatus, ProfileStatus, ProfileVisit
```

文件末尾追加：

```python
def visits_received_queryset(me):
    """谁看过我:与「喜欢我的人」同口径,排除我已划过 / 双向拉黑 / 资料不全。

    已配对的人不需要单独过滤:配对的前提是双方都划过对方,「排除我已划过」已天然覆盖。

    Args:
        me: 当前用户。

    Returns:
        以 ``ProfileVisit`` 为行的查询集,按最近访问时间倒序;列表与计数必须共用它。
    """
    swiped = Swipe.objects.filter(swiper=me).values("target_id")
    with_photos = Photo.objects.filter(status=PhotoStatus.APPROVED).values("user_id")
    return (ProfileVisit.objects
            .filter(owner=me)
            .exclude(viewer_id=me.id)
            .exclude(viewer_id__in=swiped)
            .exclude(viewer_id__in=blocked_user_ids(me))
            .filter(viewer__profile__status=ProfileStatus.COMPLETE)
            .filter(viewer_id__in=with_photos)
            .select_related("viewer__profile")
            .prefetch_related("viewer__photos", "viewer__profile__tags")
            .order_by("-last_at", "-id"))
```

- [ ] **Step 4: 加序列化器**

`chatapp/discovery/serializers.py` 顶部 import 补 `from users.models import PhotoStatus, Profile, ProfileVisit`，文件末尾追加：

```python
class VisitSerializer(serializers.ModelSerializer):
    """「谁看过我」列表项:对方公开资料 + 最近访问时间。"""

    user_id = serializers.IntegerField(source="viewer.id", read_only=True)
    im_user_id = serializers.CharField(source="viewer.im_user_id", read_only=True)
    nickname = serializers.CharField(source="viewer.profile.nickname", read_only=True)
    gender = serializers.CharField(source="viewer.profile.gender", read_only=True)
    age = serializers.IntegerField(source="viewer.profile.age", read_only=True, allow_null=True)
    city = serializers.CharField(source="viewer.profile.city", read_only=True)
    bio = serializers.CharField(source="viewer.profile.bio", read_only=True)
    tags = TagSerializer(source="viewer.profile.tags", many=True, read_only=True)
    photos = serializers.SerializerMethodField()
    visited_at = serializers.DateTimeField(source="last_at", read_only=True)

    class Meta:
        model = ProfileVisit
        fields = ["user_id", "im_user_id", "nickname", "gender", "age", "city", "bio",
                  "tags", "photos", "visited_at"]

    def get_photos(self, visit):
        """只返回已过审照片。

        Args:
            visit: 一条访客记录。

        Returns:
            已过审照片的序列化数据。
        """
        approved = [p for p in visit.viewer.photos.all() if p.status == PhotoStatus.APPROVED]
        return PhotoSerializer(approved, many=True, context=self.context).data
```

- [ ] **Step 5: 加视图与路由**

`chatapp/discovery/views.py` 顶部：`from .services import likes_received_queryset, notify_match, visits_received_queryset`，序列化器 import 补 `VisitSerializer`。文件末尾追加：

```python
@api_view(["GET"])
def visits(request):
    """谁看过我(GET /api/v1/discovery/visits)。

    Args:
        request: DRF 请求对象,支持 ``limit`` / ``offset``。

    Returns:
        分页后的访客列表,字段见 ``VisitSerializer``。
    """
    qs = visits_received_queryset(request.user)
    paginator = DefaultLimitOffsetPagination()
    page = paginator.paginate_queryset(qs, request)
    return paginator.get_paginated_response(
        VisitSerializer(page, many=True, context={"request": request}).data)


@api_view(["GET"])
def visits_count(request):
    """访客人数(GET /api/v1/discovery/visits/count)。

    Args:
        request: DRF 请求对象。

    Returns:
        ``{"count": N}``,与列表同口径,供入口角标使用。
    """
    return Response({"count": visits_received_queryset(request.user).count()})
```

`chatapp/discovery/urls.py` 在 `likes/count` 之后加两行：

```python
    path("visits", views.visits),
    path("visits/count", views.visits_count),
```

- [ ] **Step 6: 跑测试确认通过**

Run: `cd chatapp && python manage.py test discovery.tests.VisitsReceivedTests discovery.tests.LikesReceivedTests -v 2`
Expected: PASS（14 + 既有 likes 用例全绿）

- [ ] **Step 7: 提交**

```bash
git add chatapp/discovery
git commit -m "feat(visits): /discovery/visits 与 /visits/count 接口"
```

---

### Task 5: 保留期清理命令

**Files:**
- Create: `chatapp/users/management/commands/purge_profile_visits.py`
- Test: `chatapp/users/tests.py`（新增 `PurgeProfileVisitsCommandTests`）

**Interfaces:**
- Consumes: `users.services.PROFILE_VISIT_RETENTION_DAYS`（Task 2）、`ProfileVisit`（Task 1）
- Produces: `python manage.py purge_profile_visits [--apply] [--days N]`

- [ ] **Step 1: 写失败的测试**

`chatapp/users/tests.py` 追加（`from io import StringIO` 与 `from django.core.management import call_command`，若未 import 则补）：

```python
class PurgeProfileVisitsCommandTests(TestCase):
    """保留期清理:dry-run 不删、--apply 只删过期行、边界不误删。"""

    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")
        self.old = ProfileVisit.objects.create(
            viewer=self.a, owner=self.b,
            last_at=timezone.now() - timedelta(days=91))
        self.fresh = ProfileVisit.objects.create(
            viewer=self.b, owner=self.a,
            last_at=timezone.now() - timedelta(days=89))

    def test_dry_run_keeps_rows(self):
        call_command("purge_profile_visits", stdout=StringIO())
        self.assertEqual(ProfileVisit.objects.count(), 2)

    def test_apply_deletes_only_expired(self):
        call_command("purge_profile_visits", "--apply", stdout=StringIO())
        self.assertFalse(ProfileVisit.objects.filter(id=self.old.id).exists())
        self.assertTrue(ProfileVisit.objects.filter(id=self.fresh.id).exists())

    def test_custom_days(self):
        call_command("purge_profile_visits", "--apply", "--days", "1", stdout=StringIO())
        self.assertEqual(ProfileVisit.objects.count(), 0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test users.tests.PurgeProfileVisitsCommandTests -v 2`
Expected: FAIL —— `CommandError: Unknown command: 'purge_profile_visits'`

- [ ] **Step 3: 写命令**

```python
"""删除超过保留期的资料页访问记录(默认 dry-run,``--apply`` 才真删)。

访客记录属于个人信息,按「最小必要」原则保留 90 天(见
``users.services.PROFILE_VISIT_RETENTION_DAYS``)。建议挂每天低峰的计划任务。
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from users.models import ProfileVisit
from users.services import PROFILE_VISIT_RETENTION_DAYS


class Command(BaseCommand):
    """清理过期访客记录(默认 dry-run)。"""

    help = "删除超过保留期的资料页访问记录(默认 dry-run,--apply 才删)"

    def add_arguments(self, parser):
        """注册命令行参数。

        Args:
            parser: argparse 解析器。
        """
        parser.add_argument("--apply", action="store_true", help="真正删除;默认只打印")
        parser.add_argument("--days", type=int, default=PROFILE_VISIT_RETENTION_DAYS,
                            help=f"保留天数,默认 {PROFILE_VISIT_RETENTION_DAYS}")

    def handle(self, *args, **options):
        """按保留期删除(或列出)过期记录。

        Args:
            *args: 位置参数(未使用)。
            **options: 命令行选项。

        Returns:
            None。
        """
        days = int(options["days"])
        cutoff = timezone.now() - timedelta(days=days)
        expired = ProfileVisit.objects.filter(last_at__lt=cutoff)
        total = expired.count()
        if not options["apply"]:
            oldest = expired.order_by("last_at").values_list("last_at", flat=True).first()
            self.stdout.write(f"[dry-run] 将删除 {total} 条(早于 {cutoff:%Y-%m-%d %H:%M}),"
                              f"最早一条 {oldest}")
            return
        deleted, _ = expired.delete()
        self.stdout.write(f"已删除 {deleted} 条(早于 {cutoff:%Y-%m-%d %H:%M})")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && python manage.py test users.tests.PurgeProfileVisitsCommandTests -v 2`
Expected: PASS（3 tests）

- [ ] **Step 5: 提交**

```bash
git add chatapp/users/management/commands/purge_profile_visits.py chatapp/users/tests.py
git commit -m "feat(visits): purge_profile_visits 保留期清理命令"
```

---

### Task 6: 接口文档三处

**Files:**
- Modify: `docs/api/discovery.md`（追加 §3.7 / §3.8）
- Modify: `docs/api/users.md`（`/users/me` 的响应与入参字段表）
- Modify: `docs/api/README.md`（接口总数 43 → 45）
- Test: `python manage.py test api_docs`（门禁用例，实际类名见 `ApiDocsCoverageTests`）

**Interfaces:**
- Consumes: Task 4 的两个接口、Task 3 的 `visits_hidden` 字段

- [ ] **Step 1: 先跑门禁，确认它确实会红**

Run: `cd chatapp && python manage.py test -k ApiDocsCoverage 2>&1 | Select-Object -Last 20`
Expected: FAIL —— 提示 `discovery.md` 缺少 `/discovery/visits` 等条目

- [ ] **Step 2: 补 `docs/api/discovery.md`**

在 §3.6 之后追加（沿用 §3.4 的排版：接口描述 / 请求参数 / 响应参数 / 示例 / 错误码）：

```markdown
### 3.7 谁看过我

> `GET` `/api/v1/discovery/visits` · 需要鉴权 · 无额外限流

**接口描述**

分页查询「谁看过我的资料页」。口径与「喜欢我的人」一致:

- 打开我的资料页(`GET /users/{id}`)即记一次访问,同一人 30 分钟内重复访问只刷新最近时间;
- 排除**我已经划过的人**(不论 like/pass)、双向拉黑的人;
- 只含资料完善(`status = complete`)且至少有 1 张已过审照片的人;
- 按最近访问时间倒序。已配对的人因「我已划过」自然不在列表内。

开启「隐身浏览」后,你的访问不会写进任何人的列表。

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| limit | 否 | Integer | 每页条数,默认 20,上限 100 |
| offset | 否 | Integer | 偏移量,默认 0 |

**响应参数**

分页对象(见 [conventions.md §分页约定](../../../api/conventions.md#分页约定)),`results[]` 字段:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| user_id | Integer | 访客账号 ID |
| im_user_id | String | 访客 IM 账号,格式 `u{user_id}` |
| nickname | String | 昵称 |
| gender | String | `male` / `female` |
| age | Integer / null | 周岁;未填生日时为 `null` |
| city | String | 城市 |
| bio | String | 简介 |
| tags | Object[] | 标签,结构见 [users.md §2.1](../../../api/users.md) |
| photos | Object[] | **只含已过审**的照片 |
| visited_at | String | 最近一次访问时间(UTC,ISO 8601,精度 30 分钟) |

**请求示例**

```bash
curl "http://<域名>/api/v1/discovery/visits?limit=20&offset=0" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{
  "count": 1,
  "next": null,
  "previous": null,
  "results": [
    {
      "user_id": 30,
      "im_user_id": "u30",
      "nickname": "多多30",
      "gender": "female",
      "age": 25,
      "city": "南京",
      "bio": "咖啡续命,手冲入门中",
      "tags": [{ "id": 7, "name": "游戏", "icon": "game" }],
      "photos": [
        { "id": 41, "url": "http://<域名>/media/photos/2026/09/seed_30_0.jpg", "status": "approved", "order": 0 }
      ],
      "visited_at": "2026-11-01T04:30:00.000000Z"
    }
  ]
}
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号已被封禁(重封禁) | 提示用户账号受限 |

---

### 3.8 访客人数

> `GET` `/api/v1/discovery/visits/count` · 需要鉴权 · 无额外限流

**接口描述**

返回「谁看过我」的去重人数,口径与 §3.7 完全一致,仅用于客户端入口角标。

**请求参数**

无。

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| count | Integer | 访客人数(已套用 §3.7 的全部排除规则) |

**请求示例**

```bash
curl "http://<域名>/api/v1/discovery/visits/count" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```json
{ "count": 12 }
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号已被封禁(重封禁) | 提示用户账号受限 |
```

- [ ] **Step 3: 补 `docs/api/users.md`**

在 `GET /users/me` 的响应字段表里加一行：

```markdown
| visits_hidden | Boolean | 是否开启「隐身浏览」;开启后自己的访问不写进他人访客列表 |
```

在 `PATCH /users/me` 的请求参数表里加一行：

```markdown
| visits_hidden | 否 | Boolean | 隐身浏览开关;不传表示不改 |
```

- [ ] **Step 4: 补 `docs/api/README.md`**

把 `共 **43** 个接口(按「方法 + 路径」计)。` 改成 `共 **45** 个接口(按「方法 + 路径」计)。`，并在发现与配对分册的条目计数处同步 +2（若 README 里有分册明细表）。

- [ ] **Step 5: 跑门禁确认通过**

Run: `cd chatapp && python manage.py test -k ApiDocsCoverage 2>&1 | Select-Object -Last 10`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add docs/api
git commit -m "docs(api): 补 /discovery/visits 两节与 users/me 的 visits_hidden"
```

---

### Task 7: App 数据层（模型 / 仓库 / 控制器）

**Files:**
- Modify: `app/lib/features/discovery/models.dart`（新增 `Visit`）
- Modify: `app/lib/features/discovery/discovery_repository.dart`（两个方法）
- Create: `app/lib/features/discovery/visits_controller.dart`
- Test: `app/test/features/discovery/visits_controller_test.dart`

**Interfaces:**
- Produces:
  - `Visit({required Candidate candidate, required DateTime visitedAt})` + `Visit.fromJson`
  - `DiscoveryRepository.fetchVisits({int limit = 20, int offset = 0}) -> ({List<Visit> items, int count})`
  - `DiscoveryRepository.fetchVisitsCount() -> Future<int>`
  - `visitsProvider`（`AsyncNotifierProvider<VisitsController, VisitsState>`）、`visitsCountProvider`（`FutureProvider<int>`）
  - `VisitsState({items, count, hasMore, busyUserId})` + `VisitsController.accept(Visit) -> Future<Candidate?>`

- [ ] **Step 1: 写失败的测试**

新建 `app/test/features/discovery/visits_controller_test.dart`：

```dart
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/discovery/discovery_repository.dart';
import 'package:chatapp_app/features/discovery/visits_controller.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late ProviderContainer container;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
    ]);
    addTearDown(container.dispose);
  });

  test('拉取访客列表与总数', () async {
    adapter.routes['GET /discovery/visits'] = (options) => ok(pageJson([
          visitJson(userId: 9, nickname: '小红'),
        ]));
    final state = await container.read(visitsProvider.future);
    expect(state.items.single.candidate.nickname, '小红');
    expect(state.count, 1);
    expect(state.hasMore, isFalse);
  });

  test('回喜欢 → 行移除、计数 -1、返回候选人', () async {
    adapter.routes['GET /discovery/visits'] = (options) => ok(pageJson([
          visitJson(userId: 9, nickname: '小红'),
          visitJson(userId: 10, nickname: '小刚'),
        ]));
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': true});
    await container.read(visitsProvider.future);

    final matched = await container.read(visitsProvider.notifier).accept(
          container.read(visitsProvider).value!.items.first,
        );

    expect(matched?.userId, 9);
    final state = container.read(visitsProvider).value!;
    expect(state.items.single.candidate.userId, 10);
    expect(state.count, 1);
    final request = adapter.log.lastWhere((item) => item.method == 'POST');
    expect(request.data, {'target_user_id': 9, 'action': 'like'});
  });

  test('角标只查数量', () async {
    adapter.routes['GET /discovery/visits/count'] = (options) => ok({'count': 7});
    expect(await container.read(visitsCountProvider.future), 7);
  });
}
```

同时在 `app/test/support/sample_data.dart` 末尾加一个造数函数：

```dart
/// 造一份 GET /discovery/visits 里的一条。
Map<String, dynamic> visitJson({
  int userId = 9,
  String nickname = '小红',
  int? age = 25,
  String city = '上海',
  List<Map<String, dynamic>> tags = const [],
  String visitedAt = '2026-11-01T12:30:00+08:00',
}) =>
    {
      ...candidateJson(userId: userId, nickname: nickname, age: age, city: city, tags: tags),
      'visited_at': visitedAt,
    };
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/visits_controller_test.dart`
Expected: FAIL —— `Error: Couldn't resolve the package 'chatapp_app' ... visits_controller.dart`（文件不存在）

- [ ] **Step 3: 加模型与仓库方法**

`app/lib/features/discovery/models.dart` 末尾追加：

```dart
/// 一次访客记录;字段与 GET /discovery/visits 的单项一一对应。
class Visit {
  const Visit({required this.candidate, required this.visitedAt});

  factory Visit.fromJson(Map<String, dynamic> json) => Visit(
        candidate: Candidate.fromJson(json),
        visitedAt: DateTime.parse(json['visited_at'] as String),
      );

  final Candidate candidate;
  final DateTime visitedAt;
}
```

`app/lib/features/discovery/discovery_repository.dart` 在 `fetchLikesReceivedCount` 之后追加：

```dart
  /// 谁看过我(分页);返回本页条目与后端总数。
  Future<({List<Visit> items, int count})> fetchVisits(
      {int limit = 20, int offset = 0}) async {
    final data = await _api.get('/discovery/visits',
        query: {'limit': limit, 'offset': offset}) as Map<String, dynamic>;
    final items = (data['results'] as List<dynamic>)
        .map((item) => Visit.fromJson(item as Map<String, dynamic>))
        .toList();
    return (items: items, count: data['count'] as int);
  }

  /// 访客入口角标:只查数量。
  Future<int> fetchVisitsCount() async {
    final data = await _api.get('/discovery/visits/count') as Map<String, dynamic>;
    return data['count'] as int;
  }
```

- [ ] **Step 4: 写控制器**

新建 `app/lib/features/discovery/visits_controller.dart`（与 `likes_received_controller.dart` 同构）：

```dart
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../chat/match_cache.dart';
import 'discovery_repository.dart';
import 'models.dart';

const _pageSize = 20;

/// 「谁看过我」页面状态。
class VisitsState {
  const VisitsState({
    required this.items,
    required this.count,
    this.hasMore = false,
    this.busyUserId,
  });

  final List<Visit> items;
  final int count;
  final bool hasMore;
  final int? busyUserId;

  VisitsState copyWith({
    List<Visit>? items,
    int? count,
    bool? hasMore,
    int? busyUserId,
    bool clearBusy = false,
  }) =>
      VisitsState(
        items: items ?? this.items,
        count: count ?? this.count,
        hasMore: hasMore ?? this.hasMore,
        busyUserId: clearBusy ? null : (busyUserId ?? this.busyUserId),
      );
}

/// 分页拉取 + 回喜欢编排(移除行、计数、配对缓存、角标)。
class VisitsController extends AsyncNotifier<VisitsState> {
  bool _loadingMore = false;

  @override
  Future<VisitsState> build() => _fetch(reset: true);

  Future<VisitsState> _fetch({required bool reset, int offset = 0}) async {
    final page = await ref
        .read(discoveryRepositoryProvider)
        .fetchVisits(limit: _pageSize, offset: offset);
    final items = reset
        ? page.items
        : [...(state.value?.items ?? const <Visit>[]), ...page.items];
    return VisitsState(items: items, count: page.count, hasMore: items.length < page.count);
  }

  Future<void> reload() async {
    state = const AsyncValue.loading();
    state = await AsyncValue.guard(() => _fetch(reset: true));
  }

  Future<void> loadMore() async {
    final current = state.value;
    if (current == null || !current.hasMore || _loadingMore) return;
    _loadingMore = true;
    try {
      final page = await ref
          .read(discoveryRepositoryProvider)
          .fetchVisits(limit: _pageSize, offset: current.items.length);
      state = AsyncValue.data(current.copyWith(
        items: [...current.items, ...page.items],
        count: page.count,
        hasMore: current.items.length + page.items.length < page.count,
      ));
    } finally {
      _loadingMore = false;
    }
  }

  /// 回喜欢;需要弹配对动效时返回被喜欢的人,未配对返回 null。
  Future<Candidate?> accept(Visit item) async {
    final current = state.value;
    if (current == null || current.busyUserId != null) return null;
    state = AsyncValue.data(current.copyWith(busyUserId: item.candidate.userId));
    try {
      final matched = await ref
          .read(discoveryRepositoryProvider)
          .swipe(targetUserId: item.candidate.userId, like: true);
      final now = state.value ?? current;
      final items = now.items
          .where((entry) => entry.candidate.userId != item.candidate.userId)
          .toList();
      final newCount = now.count > 0 ? now.count - 1 : 0;
      state = AsyncValue.data(now.copyWith(
        items: items,
        count: newCount,
        hasMore: items.length < newCount,
        clearBusy: true,
      ));
      ref.invalidate(matchCacheProvider);
      ref.invalidate(visitsCountProvider);
      return matched ? item.candidate : null;
    } catch (_) {
      final now = state.value ?? current;
      state = AsyncValue.data(now.copyWith(clearBusy: true));
      await reload();
      rethrow;
    }
  }
}

final visitsProvider = AsyncNotifierProvider<VisitsController, VisitsState>(
  VisitsController.new,
  retry: (retryCount, error) => null,
);

/// 入口角标:只查数量,不拉整页。
final visitsCountProvider = FutureProvider<int>(
    (ref) async => ref.watch(discoveryRepositoryProvider).fetchVisitsCount());
```

- [ ] **Step 4b: 跑测试**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/visits_controller_test.dart`
Expected: PASS（3 tests）

- [ ] **Step 5: analyze**

Run: `cd app && ../flutter/bin/flutter.bat analyze`
Expected: `No issues found!`

- [ ] **Step 6: 提交**

```bash
git add app/lib/features/discovery app/test/features/discovery app/test/support/sample_data.dart
git commit -m "feat(visits): App 访客数据层(模型/仓库/控制器)"
```

---

### Task 8: App 访客列表页 + 路由 + 骨架组件提升

**Files:**
- Create: `app/lib/core/widgets/app_list_skeleton.dart`
- Delete: `app/lib/features/discovery/widgets/likes_skeleton.dart`
- Modify: `app/lib/features/discovery/likes_received_page.dart`（改用 `AppListSkeleton`）
- Create: `app/lib/features/discovery/visits_page.dart`
- Modify: `app/lib/router.dart`（`/visits`）
- Test: `app/test/features/discovery/visits_page_test.dart`

**Interfaces:**
- Consumes: `visitsProvider` / `VisitsController.accept`（Task 7）
- Produces: `AppListSkeleton({Key? key, int rowCount = 6})`；路由 `/visits`

- [ ] **Step 1: 写失败的页面测试**

新建 `app/test/features/discovery/visits_page_test.dart`（照 `likes_received_page_test.dart` 的结构）：

```dart
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/discovery/visits_page.dart';

import '../../support/harness.dart';
import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
  });

  Future<void> pumpPage(WidgetTester tester) async {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final container = ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(dio),
    ]);
    addTearDown(container.dispose);
    await tester.pumpWidget(UncontrolledProviderScope(
      container: container,
      child: const MaterialApp(home: VisitsPage()),
    ));
    await pumpFrames(tester);
  }

  testWidgets('空态', (tester) async {
    adapter.routes['GET /discovery/visits'] = (options) => ok(pageJson([]));
    await pumpPage(tester);
    expect(find.byKey(const Key('visits.empty')), findsOneWidget);
    expect(find.text('还没有人看过你'), findsOneWidget);
  });

  testWidgets('列表渲染昵称/年龄/城市/访问时间', (tester) async {
    adapter.routes['GET /discovery/visits'] = (options) => ok(pageJson([
          visitJson(userId: 9, nickname: '小红', tags: [tagJson(1, '旅行')]),
        ]));
    await pumpPage(tester);
    expect(find.text('小红'), findsOneWidget);
    expect(find.textContaining('25 岁'), findsOneWidget);
    expect(find.textContaining('旅行'), findsOneWidget);
    expect(find.byKey(const Key('visits.accept.9')), findsOneWidget);
  });

  testWidgets('点「喜欢」→ 行移除并弹配对动效', (tester) async {
    adapter.routes['GET /discovery/visits'] = (options) => ok(pageJson([
          visitJson(userId: 9, nickname: '小红'),
          visitJson(userId: 10, nickname: '小刚'),
        ]));
    adapter.routes['GET /users/me'] = (options) => ok(profileJson());
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': true});
    await pumpPage(tester);

    await tester.tap(find.byKey(const Key('visits.accept.9')));
    await tester.pumpAndSettle();

    expect(find.text('你们已互相喜欢'), findsOneWidget);
    expect(find.byKey(const Key('visits.row.9')), findsNothing);
    final request = adapter.log.lastWhere((item) => item.method == 'POST');
    expect(request.data, {'target_user_id': 9, 'action': 'like'});
  });

  testWidgets('加载失败 → 错误态,重试成功', (tester) async {
    adapter.routes['GET /discovery/visits'] = offline;
    await pumpPage(tester);
    expect(find.byKey(const Key('visits.retry')), findsOneWidget);

    adapter.routes['GET /discovery/visits'] =
        (options) => ok(pageJson([visitJson(userId: 9, nickname: '小红')]));
    await tester.tap(find.byKey(const Key('visits.retry')));
    await pumpFrames(tester);
    expect(find.text('小红'), findsOneWidget);
  });
}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/visits_page_test.dart`
Expected: FAIL —— `visits_page.dart` 不存在

- [ ] **Step 3: 提升骨架组件**

新建 `app/lib/core/widgets/app_list_skeleton.dart`：

```dart
import 'package:flutter/material.dart';

import '../theme/app_radius.dart';
import '../theme/app_spacing.dart';
import 'app_skeleton.dart';

/// 列表页通用加载骨架:圆头像 + 两条文字条。
/// 含无限呼吸动画 —— 可见它的用例只用有限 pump。
class AppListSkeleton extends StatelessWidget {
  const AppListSkeleton({super.key, this.rowCount = 6});

  final int rowCount;

  @override
  Widget build(BuildContext context) => Column(
        children: [
          for (var i = 0; i < rowCount; i++)
            const Padding(
              padding: EdgeInsets.symmetric(
                horizontal: AppSpacing.lg,
                vertical: AppSpacing.md,
              ),
              child: Row(
                children: [
                  AppSkeleton(width: 44, height: 44, radius: AppRadius.full),
                  SizedBox(width: AppSpacing.md),
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      AppSkeleton(width: 120, height: 14),
                      SizedBox(height: AppSpacing.xs),
                      AppSkeleton(width: 160, height: 12),
                    ],
                  ),
                ],
              ),
            ),
        ],
      );
}
```

删除 `app/lib/features/discovery/widgets/likes_skeleton.dart`，并把 `likes_received_page.dart` 里：

```dart
import 'widgets/likes_skeleton.dart';
```
改成
```dart
import '../../core/widgets/app_list_skeleton.dart';
```

把 `loading: () => const LikesSkeleton(),` 改成：

```dart
                loading: () => const AppListSkeleton(key: Key('likes.skeleton')),
```

- [ ] **Step 4: 写访客页**

新建 `app/lib/features/discovery/visits_page.dart`（与 `likes_received_page.dart` 同构，去掉「去完善资料」之外的额外分支）：

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../core/api_exception.dart';
import '../../core/format.dart';
import '../../core/theme/app_colors.dart';
import '../../core/theme/app_spacing.dart';
import '../../core/widgets/app_avatar.dart';
import '../../core/widgets/app_button.dart';
import '../../core/widgets/app_empty_state.dart';
import '../../core/widgets/app_error_view.dart';
import '../../core/widgets/app_list_row.dart';
import '../../core/widgets/app_list_skeleton.dart';
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_toast.dart';
import '../../core/widgets/heart_ripple.dart';
import '../profile/profile_controller.dart';
import 'models.dart';
import 'visits_controller.dart';
import 'widgets/match_overlay.dart';

/// 「谁看过我」二级页:列表 + 回喜欢 + 四态。
class VisitsPage extends ConsumerWidget {
  const VisitsPage({super.key});

  Future<void> _accept(BuildContext context, WidgetRef ref, Visit item) async {
    try {
      final matched = await ref.read(visitsProvider.notifier).accept(item);
      if (!context.mounted) return;
      if (matched == null) {
        AppToast.show(context, '已喜欢');
        return;
      }
      final me = ref.read(profileProvider).value;
      await showMatchOverlay(
        context,
        candidate: item.candidate,
        myAvatarUrl: me?.avatar?.url,
        onGoChat: () => context.push('/chat/u${item.candidate.userId}'),
      );
    } on ApiException catch (error) {
      if (context.mounted) AppToast.show(context, error.message);
    }
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final visits = ref.watch(visitsProvider);
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const AppSubPageBar(title: '谁看过我'),
            Expanded(
              child: visits.when(
                loading: () => const AppListSkeleton(key: Key('visits.skeleton')),
                error: (error, _) => AppErrorView(
                  message: error is ApiException ? error.message : '加载失败,请重试',
                  retryKey: const Key('visits.retry'),
                  onRetry: () => ref.read(visitsProvider.notifier).reload(),
                ),
                data: (data) => data.items.isEmpty
                    ? Center(
                        child: AppEmptyState(
                          key: const Key('visits.empty'),
                          mark: const HeartRipple(),
                          title: '还没有人看过你',
                          description: '完善资料、多发动态,被看到的机会更多',
                          action: AppButton(
                            key: const Key('visits.goOnboarding'),
                            label: '去完善资料',
                            onPressed: () => context.go('/onboarding'),
                          ),
                        ),
                      )
                    : NotificationListener<ScrollNotification>(
                        onNotification: (notification) {
                          if (notification.metrics.pixels >=
                              notification.metrics.maxScrollExtent - 120) {
                            ref.read(visitsProvider.notifier).loadMore();
                          }
                          return false;
                        },
                        child: RefreshIndicator(
                          onRefresh: () => ref.read(visitsProvider.notifier).reload(),
                          child: ListView.separated(
                            physics: const AlwaysScrollableScrollPhysics(),
                            padding:
                                const EdgeInsets.symmetric(vertical: AppSpacing.sm),
                            itemCount: data.items.length,
                            separatorBuilder: (_, _) => const Divider(
                              height: 1,
                              indent: 72,
                              color: AppColors.divider,
                            ),
                            itemBuilder: (context, index) {
                              final item = data.items[index];
                              return AppListRow(
                                key: Key('visits.row.${item.candidate.userId}'),
                                avatar: AppAvatar(
                                  size: 44,
                                  imageUrl: item.candidate.photos.isEmpty
                                      ? null
                                      : item.candidate.photos.first.url,
                                  fallbackText: item.candidate.nickname,
                                ),
                                title: item.candidate.nickname,
                                subtitle: _subtitle(item),
                                onTap: () =>
                                    context.push('/users/${item.candidate.userId}'),
                                trailing: AppTextAction(
                                  key: Key('visits.accept.${item.candidate.userId}'),
                                  label: data.busyUserId == item.candidate.userId
                                      ? '喜欢中'
                                      : '喜欢',
                                  onPressed: data.busyUserId == item.candidate.userId
                                      ? null
                                      : () => _accept(context, ref, item),
                                ),
                              );
                            },
                          ),
                        ),
                      ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

String _subtitle(Visit item) {
  final candidate = item.candidate;
  final parts = [
    if (candidate.age != null) '${candidate.age} 岁',
    if (candidate.city.isNotEmpty) candidate.city,
    ...candidate.tags.take(3).map((tag) => tag.name),
    formatPostTime(item.visitedAt),
  ];
  return parts.join(' · ');
}
```

- [ ] **Step 5: 加路由**

`app/lib/router.dart`：import 区加 `import 'features/discovery/visits_page.dart';`，在 `/likes` 那行之后加：

```dart
      GoRoute(path: '/visits', builder: (context, state) => const VisitsPage()),
```

- [ ] **Step 6: 跑测试 + analyze**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/visits_page_test.dart test/features/discovery/likes_received_page_test.dart`
Expected: PASS（4 + 4）

Run: `cd app && ../flutter/bin/flutter.bat analyze`
Expected: `No issues found!`

- [ ] **Step 7: 提交**

```bash
git add app/lib app/test
git commit -m "feat(visits): App 访客列表页 + 通用列表骨架"
```

---

### Task 9: App 发现页两枚入口

**Files:**
- Modify: `app/lib/features/discovery/discovery_page.dart`（`_LikesEntry` → `_TopEntry`，并排两枚）
- Test: `app/test/features/discovery/discovery_page_test.dart`（新增一条用例）

**Interfaces:**
- Consumes: `visitsCountProvider`（Task 7）、路由 `/visits`（Task 8）
- Produces: `Key('discovery.visits')`、`Key('discovery.likes')` 两个入口

- [ ] **Step 1: 写失败的测试**

`app/test/features/discovery/discovery_page_test.dart` 末尾追加：

```dart
  testWidgets('发现页显示访客数,点入口进访客列表', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /discovery/candidates': (options) => ok([candidateJson(userId: 9)]),
      'GET /discovery/likes/count': (options) => ok({'count': 0}),
      'GET /discovery/visits/count': (options) => ok({'count': 4}),
      'GET /discovery/visits': (options) => ok(pageJson([
            visitJson(userId: 10, nickname: '小刚'),
          ])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('discovery.visits')), findsOneWidget);
    expect(find.text('4'), findsOneWidget);

    await tester.tap(find.byKey(const Key('discovery.visits')));
    await tester.pumpAndSettle();

    expect(find.text('谁看过我'), findsWidgets);
    expect(find.text('小刚'), findsOneWidget);
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/discovery_page_test.dart`
Expected: FAIL —— `discovery.visits` 找不到

- [ ] **Step 3: 改造入口**

`app/lib/features/discovery/discovery_page.dart`：

import 区加 `import 'visits_controller.dart';`。

标题行改为：

```dart
                  Text('发现', style: AppText.display.copyWith(color: AppColors.text1)),
                  Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      _TopEntry(
                        entryKey: const Key('discovery.likes'),
                        icon: Icons.favorite_rounded,
                        iconColor: AppColors.brand,
                        label: '喜欢我的人',
                        count: ref.watch(likesReceivedCountProvider).value ?? 0,
                        onTap: () => context.push('/likes'),
                      ),
                      const SizedBox(width: AppSpacing.xs),
                      _TopEntry(
                        entryKey: const Key('discovery.visits'),
                        icon: Icons.visibility_rounded,
                        iconColor: AppColors.text2,
                        label: '谁看过我',
                        count: ref.watch(visitsCountProvider).value ?? 0,
                        onTap: () => context.push('/visits'),
                      ),
                    ],
                  ),
```

把 `_LikesEntry` 整个类替换为：

```dart
/// 发现页右上角入口:图标 + 文案 + 角标;窄屏(<360dp)只留图标,靠 Semantics 读屏。
class _TopEntry extends StatelessWidget {
  const _TopEntry({
    required this.entryKey,
    required this.icon,
    required this.iconColor,
    required this.label,
    required this.count,
    required this.onTap,
  });

  final Key entryKey;
  final IconData icon;
  final Color iconColor;
  final String label;
  final int count;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final showLabel = MediaQuery.sizeOf(context).width >= 360;
    final semantic = count > 0 ? '$label,$count 人' : label;
    return Semantics(
      button: true,
      label: semantic,
      child: InkWell(
        key: entryKey,
        borderRadius: BorderRadius.circular(AppRadius.full),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.xs, vertical: AppSpacing.xs),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(icon, size: 20, color: iconColor),
              if (showLabel) ...[
                const SizedBox(width: AppSpacing.xs),
                Text(label, style: AppText.caption.copyWith(color: AppColors.text2)),
              ],
              if (count > 0) ...[
                const SizedBox(width: AppSpacing.xs),
                AppBadge(count: count),
              ],
            ],
          ),
        ),
      ),
    );
  }
}
```

- [ ] **Step 4: 跑测试 + analyze**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/discovery/discovery_page_test.dart`
Expected: PASS（含既有「喜欢我的人」用例）

Run: `cd app && ../flutter/bin/flutter.bat analyze`
Expected: `No issues found!`

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/discovery/discovery_page.dart app/test/features/discovery/discovery_page_test.dart
git commit -m "feat(visits): 发现页并排两枚入口(喜欢我的人 / 谁看过我)"
```

---

### Task 10: App 设置页「隐身浏览」开关

**Files:**
- Modify: `app/lib/features/profile/models.dart`（`Profile.visitsHidden`）
- Create: `app/lib/features/settings/widgets/visits_hidden_row.dart`
- Modify: `app/lib/features/settings/settings_page.dart`（第一张行分组插入该行）
- Test: `app/test/features/settings/settings_page_test.dart`（新增两条用例）
- Test helper: `app/test/support/sample_data.dart`（`profileJson` 加 `visitsHidden` 参数）

**Interfaces:**
- Consumes: `PATCH /users/me {"visits_hidden": bool}`（Task 3）、`ProfileRepository.update`（已存在）
- Produces: `Profile.visitsHidden: bool`；`Key('settings.row.visitsHidden')`

- [ ] **Step 1: 写失败的测试**

`app/test/support/sample_data.dart` 的 `profileJson` 加参数与字段：

```dart
  bool visitsHidden = false,
```
（参数列表里）
```dart
      'visits_hidden': visitsHidden,
```
（返回值里，`'preference': ...` 之后）

`app/test/features/settings/settings_page_test.dart` 追加（照现有「退出登录」用例的进页方式）：

```dart
  testWidgets('隐身浏览开关 → PATCH visits_hidden', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'PATCH /users/me': (options) => ok(profileJson(visitsHidden: true)),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('my.row.settings')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('my.row.settings')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('settings.row.visitsHidden')));
    await tester.pumpAndSettle();

    final request = adapter.log.lastWhere((item) => item.method == 'PATCH');
    expect(request.data, {'visits_hidden': true});
  });

  testWidgets('隐身浏览开关失败 → 回滚并提示', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'PATCH /users/me': (options) => jsonError(500, '服务器开小差了'),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    await tester.tap(navTab('我的'));
    await tester.pumpAndSettle();
    await tester.ensureVisible(find.byKey(const Key('my.row.settings')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('my.row.settings')));
    await tester.pumpAndSettle();

    await tester.tap(find.byKey(const Key('settings.row.visitsHidden')));
    await tester.pumpAndSettle();
    await drainToast(tester);

    expect(find.text('服务器开小差了'), findsOneWidget);
  });
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/settings/settings_page_test.dart`
Expected: FAIL —— `settings.row.visitsHidden` 找不到

- [ ] **Step 3: 加模型字段**

`app/lib/features/profile/models.dart`：`Profile` 构造参数加 `this.visitsHidden = false,`，字段区加 `final bool visitsHidden;`，`fromJson` 里加：

```dart
        visitsHidden: (json['visits_hidden'] ?? false) as bool,
```

- [ ] **Step 4: 写开关行组件**

新建 `app/lib/features/settings/widgets/visits_hidden_row.dart`：

```dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../../core/api_exception.dart';
import '../../../core/widgets/app_list_row.dart';
import '../../../core/widgets/app_toast.dart';
import '../../profile/profile_controller.dart';
import '../../profile/profile_repository.dart';

/// 「隐身浏览」开关行:乐观更新,失败回滚并提示。
class VisitsHiddenRow extends ConsumerStatefulWidget {
  const VisitsHiddenRow({super.key});

  @override
  ConsumerState<VisitsHiddenRow> createState() => _VisitsHiddenRowState();
}

class _VisitsHiddenRowState extends ConsumerState<VisitsHiddenRow> {
  bool? _optimistic;
  bool _busy = false;

  Future<void> _toggle(bool next) async {
    if (_busy) return;
    setState(() {
      _busy = true;
      _optimistic = next;
    });
    try {
      await ref.read(profileRepositoryProvider).update({'visits_hidden': next});
      ref.invalidate(profileProvider);
      if (mounted) setState(() => _optimistic = null);
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() => _optimistic = null);
      AppToast.show(context, error.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final value = _optimistic ?? ref.watch(profileProvider).value?.visitsHidden ?? false;
    return AppListRow(
      key: const Key('settings.row.visitsHidden'),
      icon: Icons.visibility_off_rounded,
      title: '隐身浏览',
      subtitle: '开启后,你看过的人不会看到你的访问记录',
      onTap: () => _toggle(!value),
      trailing: Switch.adaptive(
        value: value,
        onChanged: _busy ? null : _toggle,
      ),
    );
  }
}
```

`app/lib/features/settings/settings_page.dart`：import 加 `import 'widgets/visits_hidden_row.dart';`，第一张 `AppRowGroup` 的 `children` 里、`settings.row.blocks` 之前插入：

```dart
                        const VisitsHiddenRow(),
```

- [ ] **Step 5: 跑测试 + analyze**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/settings/settings_page_test.dart`
Expected: PASS（既有 3 条 + 新增 2 条）

Run: `cd app && ../flutter/bin/flutter.bat analyze`
Expected: `No issues found!`

- [ ] **Step 6: 提交**

```bash
git add app/lib/features/profile/models.dart app/lib/features/settings app/test
git commit -m "feat(visits): App 设置页隐身浏览开关(乐观更新+回滚)"
```

---

### Task 11: Web 数据层（类型 / API / store）

**Files:**
- Modify: `web/src/api/types.ts`（`Profile.visits_hidden`、`ProfileVisit`）
- Modify: `web/src/api/discovery.ts`（两个函数）
- Create: `web/src/stores/visits.ts`
- Test: `web/tests/unit/visits-store.spec.ts`

**Interfaces:**
- Produces:
  - `Profile.visits_hidden: boolean`
  - `ProfileVisit extends Candidate { visited_at: string }`
  - `fetchVisits(limit = 20, offset = 0): Promise<Page<ProfileVisit>>`、`fetchVisitsCount(): Promise<number>`
  - `useVisitsStore()`（`items` / `count` / `offset` / `loading` / `error` / `busyUserId` / `matched` / `load` / `loadCount` / `accept` / `dismissMatched`）

- [ ] **Step 1: 写失败的 store 测试**

新建 `web/tests/unit/visits-store.spec.ts`：

```ts
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { useVisitsStore } from '@/stores/visits'
import { server } from '../support/server'

const page = (results: unknown[], count = results.length) => ({
  count,
  next: null,
  previous: null,
  results,
})

const visit = (id: number) => ({
  user_id: id,
  im_user_id: `u${id}`,
  nickname: `用户${id}`,
  gender: 'female',
  age: 25,
  city: '上海',
  bio: '',
  tags: [],
  photos: [],
  visited_at: '2026-11-01T04:30:00Z',
})

describe('visits store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('拉取访客列表', async () => {
    server.use(mswHttp.get('/api/v1/discovery/visits', () => HttpResponse.json(page([visit(1)]))))
    const store = useVisitsStore()

    await store.load(true)

    expect(store.items).toHaveLength(1)
    expect(store.count).toBe(1)
  })

  it('accept → 调 like、移除该行、计数 -1', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/visits', () => HttpResponse.json(page([visit(1), visit(2)]))),
      mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: true })),
    )
    const store = useVisitsStore()
    await store.load(true)

    await store.accept(1)

    expect(store.items.map((item) => item.user_id)).toEqual([2])
    expect(store.count).toBe(1)
    expect(store.matched?.user_id).toBe(1)
  })

  it('accept 失败 → 列表保留、错误上抛', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/visits', () => HttpResponse.json(page([visit(1)]))),
      mswHttp.post('/api/v1/discovery/swipe', () =>
        HttpResponse.json({ code: 429, message: '操作太快了', request_id: 'r' }, { status: 429 }),
      ),
    )
    const store = useVisitsStore()
    await store.load(true)

    await expect(store.accept(1)).rejects.toThrow()

    expect(store.items.map((item) => item.user_id)).toEqual([1])
    expect(store.busyUserId).toBeNull()
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test:run -- tests/unit/visits-store.spec.ts`
Expected: FAIL —— `Failed to resolve import "@/stores/visits"`

- [ ] **Step 3: 加类型与 API**

`web/src/api/types.ts`：

```ts
export interface Profile {
  // ...既有字段...
  /** 隐身浏览:开启后自己的访问不写进他人访客列表 */
  visits_hidden: boolean
}
```

```ts
/** 「谁看过我」列表项:公开资料 + 最近访问时间(discovery.md §3.7)。 */
export interface ProfileVisit extends Candidate {
  /** ISO 8601,精度 30 分钟 */
  visited_at: string
}
```

`web/src/api/discovery.ts` 末尾追加（import 行补 `ProfileVisit`）：

```ts
export async function fetchVisits(limit = 20, offset = 0): Promise<Page<ProfileVisit>> {
  const { data } = await http.get('/discovery/visits', { params: { limit, offset } })
  return data as Page<ProfileVisit>
}

export async function fetchVisitsCount(): Promise<number> {
  const { data } = await http.get('/discovery/visits/count')
  return Number(data.count)
}
```

- [ ] **Step 4: 写 store**

新建 `web/src/stores/visits.ts`（照 `stores/likes.ts`）：

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as discoveryApi from '@/api/discovery'
import { parseApiError } from '@/api/error'
import type { Candidate, ProfileVisit } from '@/api/types'

const PAGE_SIZE = 20

export const useVisitsStore = defineStore('visits', () => {
  const items = ref<ProfileVisit[]>([])
  const count = ref(0)
  const offset = ref(0)
  const loading = ref(false)
  const error = ref('')
  const busyUserId = ref<number | null>(null)
  const matched = ref<Candidate | null>(null)

  async function load(reset = false): Promise<void> {
    if (reset) {
      items.value = []
      offset.value = 0
    }
    loading.value = true
    error.value = ''
    try {
      const page = await discoveryApi.fetchVisits(PAGE_SIZE, offset.value)
      items.value = [...items.value, ...page.results]
      count.value = page.count
      offset.value += page.results.length
    } catch (e) {
      error.value = parseApiError(e).message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function loadCount(): Promise<void> {
    count.value = await discoveryApi.fetchVisitsCount()
  }

  async function accept(userId: number): Promise<void> {
    const target = items.value.find((item) => item.user_id === userId)
    busyUserId.value = userId
    error.value = ''
    try {
      const result = await discoveryApi.swipe(userId, 'like')
      items.value = items.value.filter((item) => item.user_id !== userId)
      count.value = Math.max(0, count.value - 1)
      if (result.matched && target) matched.value = target
    } catch (e) {
      error.value = parseApiError(e).message
      throw e
    } finally {
      busyUserId.value = null
    }
  }

  function dismissMatched(): void {
    matched.value = null
  }

  return {
    items,
    count,
    offset,
    loading,
    error,
    busyUserId,
    matched,
    load,
    loadCount,
    accept,
    dismissMatched,
  }
})
```

- [ ] **Step 5: 跑测试**

Run: `cd web && npm run test:run -- tests/unit/visits-store.spec.ts`
Expected: PASS（3 tests）

- [ ] **Step 6: 类型检查**

Run: `cd web && npm run type-check`
Expected: 无错误（`Profile.visits_hidden` 必填后，任何构造 `Profile` 的测试夹具若缺字段会报错——按报错逐个补 `visits_hidden: false`）

- [ ] **Step 7: 提交**

```bash
git add web/src/api web/src/stores web/tests/unit/visits-store.spec.ts
git commit -m "feat(visits): Web 访客数据层(类型/API/store)"
```

---

### Task 12: Web 入口泛化 + 访客页 + 路由

**Files:**
- Create: `web/src/features/discovery/TopEntry.vue`
- Delete: `web/src/features/discovery/LikesEntry.vue`
- Create: `web/src/features/discovery/VisitsEntry.vue`
- Create: `web/src/features/discovery/VisitsPage.vue`
- Modify: `web/src/features/discovery/DiscoveryPage.vue`（换成两枚 `TopEntry`）
- Modify: `web/src/router/routes.ts`（`/visits`）
- Test: `web/tests/component/visits-page.spec.ts`

**Interfaces:**
- Consumes: `useVisitsStore`（Task 11）
- Produces: 路由 `visits`；`TopEntry` 组件（props `icon` / `label` / `to` / `count`）

- [ ] **Step 1: 写失败的页面测试**

新建 `web/tests/component/visits-page.spec.ts`：

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import VisitsPage from '@/features/discovery/VisitsPage.vue'
import { server } from '../support/server'

const visit = (id: number) => ({
  user_id: id,
  im_user_id: `u${id}`,
  nickname: `用户${id}`,
  gender: 'female',
  age: 25,
  city: '上海',
  bio: '',
  tags: [],
  photos: [],
  visited_at: '2026-11-01T04:30:00Z',
})

const page = (results: unknown[]) => ({
  count: results.length,
  next: null,
  previous: null,
  results,
})

function mountPage() {
  return mount(VisitsPage, {
    global: {
      plugins: [createPinia()],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
}

describe('VisitsPage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('空态', async () => {
    server.use(mswHttp.get('/api/v1/discovery/visits', () => HttpResponse.json(page([]))))
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-empty').exists()).toBe(true)
    expect(w.text()).toContain('还没有人看过你')
  })

  it('渲染列表并回喜欢', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/visits', () => HttpResponse.json(page([visit(1), visit(2)]))),
      mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: true })),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(page([]))),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('用户1')
    await w.find('.visits__accept').trigger('click')
    await flushPromises()

    expect(w.find('.match-moment').exists()).toBe(true)
    expect(w.findAll('.visits__row')).toHaveLength(1)
    expect(w.text()).toContain('用户2')
  })

  it('加载失败展示错误并可重试', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/discovery/visits', () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json(
              { code: 50002, message: '服务器开小差了', request_id: 'r' },
              { status: 500 },
            )
          : HttpResponse.json(page([visit(1)]))
      }),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-error').exists()).toBe(true)
    await w.find('.app-error button').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('用户1')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test:run -- tests/component/visits-page.spec.ts`
Expected: FAIL —— 组件不存在

- [ ] **Step 3: 泛化入口组件**

新建 `web/src/features/discovery/TopEntry.vue`：

```vue
<script setup lang="ts">
import AppBadge from '@/components/AppBadge.vue'

defineProps<{
  icon: string
  label: string
  to: string
  count: number
}>()
</script>

<template>
  <RouterLink class="top-entry" :to="to">
    <span class="top-entry__icon" aria-hidden="true">{{ icon }}</span>
    <span class="top-entry__label">{{ label }}</span>
    <AppBadge v-if="count > 0" :count="count" />
  </RouterLink>
</template>

<style scoped>
.top-entry {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
  align-self: flex-start;
  padding: var(--space-xs) var(--space-md);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-decoration: none;
}
.top-entry__icon {
  color: var(--color-brand);
  font-size: var(--text-body);
  line-height: 1;
}
.top-entry--muted .top-entry__icon {
  color: var(--color-text2);
}
</style>
```

新建 `web/src/features/discovery/VisitsEntry.vue`（挂载时拉一次数量）：

```vue
<script setup lang="ts">
import { onMounted } from 'vue'
import { useVisitsStore } from '@/stores/visits'
import TopEntry from './TopEntry.vue'

const store = useVisitsStore()

onMounted(() => {
  store.loadCount().catch(() => {})
})
</script>

<template>
  <TopEntry icon="👁" label="谁看过我" :to="{ name: 'visits' }" :count="store.count" />
</template>
```

`web/src/features/discovery/LikesEntry.vue` 改为薄包装（保留文件名，避免改 DiscoveryPage 之外的引用）：

```vue
<script setup lang="ts">
import { onMounted } from 'vue'
import { useLikesStore } from '@/stores/likes'
import TopEntry from './TopEntry.vue'

const store = useLikesStore()

onMounted(() => {
  store.loadCount().catch(() => {})
})
</script>

<template>
  <TopEntry icon="♥" label="喜欢我的人" :to="{ name: 'likes' }" :count="store.count" />
</template>
```

- [ ] **Step 4: 写访客页**

新建 `web/src/features/discovery/VisitsPage.vue`（照 `LikesPage.vue`，class 前缀换成 `visits`）：

```vue
<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import { useDiscoveryStore } from '@/stores/discovery'
import { useVisitsStore } from '@/stores/visits'
import type { ProfileVisit } from '@/api/types'
import MatchMoment from './MatchMoment.vue'

const store = useVisitsStore()
const discovery = useDiscoveryStore()
const router = useRouter()
const hasMore = computed(() => store.items.length < store.count)

onMounted(() => {
  reload()
})

function reload() {
  store.load(true).catch(() => {})
}

async function loadMore() {
  try {
    await store.load()
  } catch {
    /* store.error 已展示 */
  }
}

async function onAccept(item: ProfileVisit) {
  try {
    await store.accept(item.user_id)
    if (store.matched) await discovery.loadMatches(true)
  } catch {
    /* store.error 已展示 */
  }
}

function onChat() {
  const target = store.matched
  store.dismissMatched()
  if (target) router.push({ name: 'chat', params: { peerId: `u${target.user_id}` } })
}

function subtitle(item: ProfileVisit): string {
  const parts = [
    item.age === null ? '' : `${item.age} 岁`,
    item.city,
    ...item.tags.slice(0, 3).map((tag) => tag.name),
    formatVisitedAt(item.visited_at),
  ]
  return parts.filter(Boolean).join(' · ')
}

function formatVisitedAt(iso: string): string {
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}
</script>

<template>
  <section class="visits">
    <header class="visits__header">
      <RouterLink class="visits__back" :to="{ name: 'discovery' }">← 返回</RouterLink>
      <h1 class="visits__title">谁看过我</h1>
    </header>

    <p v-if="store.error && store.items.length > 0" class="visits__error">{{ store.error }}</p>

    <div v-if="store.loading && store.items.length === 0" class="visits__skeleton">
      <AppSkeleton v-for="i in 3" :key="i" height="64px" />
    </div>
    <AppErrorView
      v-else-if="store.error && store.items.length === 0"
      :message="store.error"
      @retry="reload"
    />
    <AppEmpty
      v-else-if="!store.loading && store.items.length === 0"
      emoji="👀"
      title="还没有人看过你"
      description="完善资料、多发动态,被看到的机会更多"
    />

    <ul v-else class="visits__list">
      <li v-for="item in store.items" :key="item.user_id" class="visits__row">
        <RouterLink
          class="visits__person"
          :to="{ name: 'user-profile', params: { id: item.user_id } }"
        >
          <AppAvatar :src="item.photos[0]?.url" :name="item.nickname" :size="44" />
          <span class="visits__meta">
            <span class="visits__name">{{ item.nickname || `用户${item.user_id}` }}</span>
            <span class="visits__sub">{{ subtitle(item) }}</span>
          </span>
        </RouterLink>
        <AppButton
          class="visits__accept"
          variant="ghost"
          :loading="store.busyUserId === item.user_id"
          @click="onAccept(item)"
        >
          喜欢
        </AppButton>
      </li>
    </ul>

    <AppButton v-if="hasMore" class="visits__more" variant="ghost" block @click="loadMore">
      加载更多
    </AppButton>

    <MatchMoment
      v-if="store.matched"
      :candidate="store.matched"
      @close="store.dismissMatched()"
      @chat="onChat"
    />
  </section>
</template>

<style scoped>
.visits {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  max-width: var(--form-card-max);
  margin: 0 auto;
  padding: var(--space-xl) var(--space-section-gap);
}
.visits__header {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.visits__back {
  align-self: flex-start;
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-decoration: none;
}
.visits__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.visits__error {
  margin: 0;
  color: var(--color-danger);
  font-size: var(--text-caption);
}
.visits__skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.visits__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  margin: 0;
  padding: 0;
  list-style: none;
}
.visits__row {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
}
.visits__person {
  display: flex;
  flex: 1;
  align-items: center;
  gap: var(--space-md);
  min-width: 0;
  color: inherit;
  text-decoration: none;
}
.visits__meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.visits__name {
  overflow: hidden;
  color: var(--color-text1);
  font-size: var(--text-subtitle);
  font-weight: var(--weight-semibold);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.visits__sub {
  overflow: hidden;
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.visits__more {
  align-self: center;
}
</style>
```

- [ ] **Step 5: 加路由 + 改发现页**

`web/src/router/routes.ts` 在 `likes` 之后加：

```ts
  {
    path: '/visits',
    name: 'visits',
    component: () => import('@/features/discovery/VisitsPage.vue'),
  },
```

`web/src/features/discovery/DiscoveryPage.vue`：import 加 `import VisitsEntry from './VisitsEntry.vue'`，把 `<LikesEntry />` 那行改成：

```vue
    <div class="discovery__entries">
      <LikesEntry />
      <VisitsEntry />
    </div>
```

样式里加：

```css
.discovery__entries {
  display: flex;
  gap: var(--space-xs);
}
```

- [ ] **Step 6: 跑测试 + 类型检查 + lint**

Run: `cd web && npm run test:run -- tests/component/visits-page.spec.ts tests/component/likes-page.spec.ts tests/component/discovery-page.spec.ts`
Expected: PASS

Run: `cd web && npm run type-check && npm run lint`
Expected: 无错误、零告警

- [ ] **Step 7: 提交**

```bash
git add web/src web/tests
git commit -m "feat(visits): Web 访客页、TopEntry 泛化与 /visits 路由"
```

---

### Task 13: Web 设置页开关 + 隐私文案 + 协议版本

**Files:**
- Modify: `web/src/features/settings/SettingsPage.vue`
- Modify: `web/src/features/legal/privacy.ts`
- Modify: `web/src/features/legal/agreed.ts`（`LEGAL_VERSION = 3`）
- Test: `web/tests/component/settings-page.spec.ts`（新增一条）

**Interfaces:**
- Consumes: `useProfileStore.save({ visits_hidden })`、`Profile.visits_hidden`（Task 11）
- Produces: `.settings__switch`（`role="switch"`）

- [ ] **Step 1: 写失败的测试**

`web/tests/component/settings-page.spec.ts` 追加：

```ts
  it('隐身浏览开关 → PATCH visits_hidden', async () => {
    stubIm()
    server.use(
      mswHttp.get('/api/v1/users/me', () =>
        HttpResponse.json({
          id: 7,
          user_id: 7,
          phone: '13800138000',
          nickname: '小明',
          gender: 'male',
          birthday: '2000-01-01',
          age: 26,
          city: '上海',
          bio: '你好',
          status: 'complete',
          ban_reason: '',
          missing_fields: [],
          tags: [],
          photos: [],
          preference: { target_gender: null, age_min: 18, age_max: 99, city: '' },
          visits_hidden: false,
        }),
      ),
      mswHttp.patch('/api/v1/users/me', async ({ request }) => {
        const body = (await request.json()) as { visits_hidden?: boolean }
        expect(body).toEqual({ visits_hidden: true })
        return HttpResponse.json({ visits_hidden: true })
      }),
    )

    const { w } = await mountPage()
    await w.find('.settings__switch').trigger('click')
    await flushPromises()

    expect(w.find('.settings__switch').attributes('aria-checked')).toBe('true')
  })
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test:run -- tests/component/settings-page.spec.ts`
Expected: FAIL —— `.settings__switch` 不存在

- [ ] **Step 3: 加开关行**

`web/src/features/settings/SettingsPage.vue`：

script 里补：

```ts
import { computed, ref } from 'vue'
import { parseApiError } from '@/api/error'
import { useProfileStore } from '@/stores/profile'

const profile = useProfileStore()
const visitsHidden = computed(() => profile.profile?.visits_hidden ?? false)
const togglingVisits = ref(false)

onMounted(() => {
  if (!profile.profile) profile.load()
})

async function toggleVisitsHidden() {
  if (togglingVisits.value) return
  togglingVisits.value = true
  const next = !visitsHidden.value
  try {
    await profile.save({ visits_hidden: next })
  } catch (e) {
    deleteError.value = parseApiError(e).message
  } finally {
    togglingVisits.value = false
  }
}
```

模板里「账号与隐私」组之后、`AppCard` 闭合之前加一行（用 `v-if` 保证只在该组出现）：

```vue
      <div v-if="group.title === '账号与隐私'" class="settings__toggle">
        <span class="settings__toggle-label">隐身浏览</span>
        <button
          class="settings__switch"
          type="button"
          role="switch"
          :aria-checked="visitsHidden"
          :disabled="togglingVisits"
          @click="toggleVisitsHidden"
        >
          <span class="settings__switch-knob" />
        </button>
      </div>
```

样式追加：

```css
.settings__toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  padding: var(--space-sm) 0;
}
.settings__switch {
  position: relative;
  width: 44px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-divider);
  cursor: pointer;
  transition: background var(--motion-fast);
}
.settings__switch[aria-checked='true'] {
  background: var(--color-brand);
}
.settings__switch-knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 20px;
  height: 20px;
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  transition: transform var(--motion-fast);
}
.settings__switch[aria-checked='true'] .settings__switch-knob {
  transform: translateX(18px);
}
```

（`--motion-fast` = 150ms，与 App 的 `AppMotion.fast` 对齐；token 定义在 `web/src/styles/tokens.css`。）

- [ ] **Step 4: 补隐私文案与版本**

`web/src/features/legal/privacy.ts`：在「我们收集的信息」列表里追加一条：

```
4. 访问记录:为展示「谁看过我」,我们会记录访问你资料页的账号与最近访问时间;你可以在「设置-隐身浏览」中关闭记录,开启后你的访问不会被对方看到。访问记录保留 90 天。
```

`web/src/features/legal/agreed.ts`：`export const LEGAL_VERSION = 3`。

- [ ] **Step 5: 跑测试 + 类型检查 + lint + 全量 Web 测试**

Run: `cd web && npm run test:run -- tests/component/settings-page.spec.ts tests/component/legal-gate.spec.ts tests/component/legal-page.spec.ts`
Expected: PASS

Run: `cd web && npm run type-check && npm run lint && npm run test:run`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add web/src web/tests
git commit -m "feat(visits): Web 设置页隐身开关 + 隐私政策补访问记录(协议版本 3)"
```

---

### Task 14: App 隐私文案与协议版本

**Files:**
- Modify: `app/lib/features/legal/legal_texts.dart`（隐私政策补条款 + `legalVersion = 3`）
- Test: `app/test/features/legal/`（若有用例断言版本号则同步；否则新增一条断言文案含「访问记录」）

**Interfaces:**
- Consumes: 无
- Produces: `legalVersion = 3`（App 与 Web 同步）

- [ ] **Step 1: 写失败的测试**

在 `app/test/features/legal/` 下新建 `legal_texts_test.dart`：

```dart
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/legal/legal_texts.dart';

void main() {
  test('隐私政策包含访问记录条款', () {
    expect(privacyText, contains('访问记录'));
    expect(privacyText, contains('隐身浏览'));
  });

  test('协议版本已升到 3', () {
    expect(legalVersion, 3);
  });
}
```

（若 `legal_texts.dart` 里隐私文案变量名不是 `privacyText`，按实际名字改。）

- [ ] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/legal/legal_texts_test.dart`
Expected: FAIL

- [ ] **Step 3: 改文案与版本**

`app/lib/features/legal/legal_texts.dart`：`const int legalVersion = 3;`，隐私政策正文里在信息收集列表末尾追加：

```
4. 访问记录:为展示「谁看过我」,我们会记录访问你资料页的账号与最近访问时间;你可以在「设置-隐身浏览」中关闭记录,开启后你的访问不会被对方看到。访问记录保留 90 天。
```

- [ ] **Step 4: 跑测试 + 全量 App 测试**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/legal`
Expected: PASS

Run: `cd app && ../flutter/bin/flutter.bat test`
Expected: 全绿（协议版本变化会影响 `pumpApp` 的默认 prefs，但它用的是 `legalVersion` 常量，自动跟随）

- [ ] **Step 5: 提交**

```bash
git add app/lib/features/legal app/test/features/legal
git commit -m "feat(legal): App 隐私政策补访问记录,协议版本升到 3"
```

---

### Task 15: 全量验证与交付清单

**Files:**
- Modify: `docs/pitfalls/backend.md`（补一条「GET 带写副作用 + 30 分钟去重」的取舍）
- Modify: `docs/superpowers/archive/specs/2026-11-01-profile-visits-design.md`（§12 上线清单补「计划任务」具体行）
- 不改代码

- [ ] **Step 1: 后端全量**

Run: `cd chatapp && python manage.py test`
Expected: 全绿（含 `ApiDocsCoverageTests`、`CommentCoverageTests`）

- [ ] **Step 2: App 全量**

Run: `cd app && ../flutter/bin/flutter.bat analyze`
Expected: `No issues found!`

Run: `cd app && ../flutter/bin/flutter.bat test`
Expected: 全绿

- [ ] **Step 3: Web 全量**

Run: `cd web && npm run type-check && npm run lint && npm run test:coverage`
Expected: 全绿且覆盖率达门槛（70/60/70/70）

- [ ] **Step 4: 补踩坑记录**

`docs/pitfalls/backend.md` 追加一节：

```markdown
## 资料页访问记录:GET 带写副作用

`GET /users/{id}` 会顺手写 `ProfileVisit`（见 `users.services.record_profile_view`）。三条约束:

1. **必须 30 分钟去重**（Redis `visit:{viewer}:{owner}`，TTL 1800）：否则用户下拉刷新一次就写一次，2C2G 上写放大明显；
2. **写库必须包在内层 `transaction.atomic()`**：`update_or_create` 撞唯一约束或 FK 失败时，若不回滚到保存点，会毒化外层事务（测试里表现为后续查询抛 `TransactionManagementError`）；
3. **异常必须吞掉**：资料页是主流程，访客记录是附加信息，失败只写 debug 日志。

若将来给该接口加 CDN/代理缓存，必须改为「前端显式上报」，否则缓存命中会漏记。
```

- [ ] **Step 5: 提交**

```bash
git add docs
git commit -m "docs(pitfalls): 资料页访问记录的 GET 写副作用与去重取舍"
```

- [ ] **Step 6: 汇总交付（不自动发版）**

向用户报告并列出需要人工执行的发版动作：

1. `cd chatapp && python manage.py migrate`
2. 计划任务：每天 03:40 `python manage.py purge_profile_visits --apply`
3. App 版本号三处同改 + 重打签名 APK + 上传
4. Web `npm run build` 并部署 `dist`
5. `.env` 的 `MIN_APP_VERSION` / `LATEST_APP_VERSION` / `APP_DOWNLOAD_URL`
6. 双账号手测：A 看 B 资料 → B 的访客列表出现 A；B 开隐身后 A 再访问不出现

---

## Self-Review

**1. Spec coverage**

| Spec 章节 | 覆盖任务 |
|---|---|
| §3.1 `ProfileVisit` 表 | Task 1 |
| §3.2 `Profile.visits_hidden` | Task 1 |
| §4 写入路径（隐身/30 分钟/savepoint/异常） | Task 2 |
| §5 列表口径 | Task 4 |
| §6.1 / §6.2 两个接口 | Task 4 |
| §6.3 隐身开关读写 | Task 3 |
| §7.1 发现页两入口 | Task 9 |
| §7.2 访客列表页 | Task 7 + Task 8 |
| §7.3 设置页开关 | Task 10 |
| §7.4 骨架提升 | Task 8 |
| §8 Web 全部 | Task 11 + 12 + 13 |
| §9 合规与 `legalVersion` 3 | Task 13（Web）+ Task 14（App） |
| §10 保留期与命令 | Task 5 |
| §11 测试计划 | 分散在各任务的 Step 1/Step 4 |
| §12 上线清单 | Task 15 |
| §13 风险（并发 IntegrityError） | Task 2 的 `except IntegrityError` |
| 接口文档门禁 | Task 6 |

**2. Placeholder scan**：无 TBD / TODO；每个代码步骤都给了完整代码；测试断言都是具体值。

**3. Type consistency**：
- 后端：`ProfileVisit(viewer, owner, first_at, last_at)` 在 Task 1 定义，Task 2/4/5 使用一致；
  `visits_received_queryset` 返回 `QuerySet[ProfileVisit]`，`VisitSerializer` 的 `source` 前缀是
  `viewer.*`，与模型一致。
- App：`Visit(candidate, visitedAt)`；`VisitsState(items, count, hasMore, busyUserId)`；
  `visitsProvider` / `visitsCountProvider` 在 Task 7 定义，Task 8/9 引用一致。
- Web：`ProfileVisit extends Candidate + visited_at`；store 方法名 `load/loadCount/accept/dismissMatched`
  与 likes store 一致；`TopEntry` props 为 `icon/label/to/count`，`VisitsEntry` 与 `LikesEntry` 调用一致。
