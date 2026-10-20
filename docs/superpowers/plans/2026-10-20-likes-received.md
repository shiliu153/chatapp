# 喜欢我的人 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. 本项目全局约定:superpowers 类任务一律内联执行,不派发子 agent。

**Goal:** 让「收到的喜欢」在 App 与 Web 双端可见、可回喜欢、可直接转化为配对,并保持与候选池完全一致的数据口径。

**Architecture:** 后端新增一个共享 queryset helper + 两个只读接口(列表 / 计数);「回喜欢」复用现有 `POST /discovery/swipe`,不新增 accept 接口。App 用 Riverpod controller 管分页与接受编排;Web 用 Pinia store。两端复用现有列表行 / 空态 / 错误态 / 骨架 / 配对动效组件。

**Tech Stack:** Django 5.2 + DRF / Flutter 3.47 + Riverpod + go_router / Vue 3 + TypeScript + Pinia + Vitest + MSW。

## Global Constraints

- 后端错误一律走现有 DRF 异常契约,不手搓 `Response({"code": ...})`。
- 新增/修改 `.py` 文件必须补模块 docstring 与函数/类 docstring;公开函数带参数必须写 `Args:`(门禁 `CommentCoverageTests`)。
- 新增 `/api/v1` 接口必须在同一次改动内更新 `docs/api/`,否则 `ApiDocsCoverageTests` 红。
- App 端 UI 一律走「心跳」token,禁止裸 hex / 裸字号 / 裸间距。
- 视觉 token 不改,本批不涉及 `tokens.css` 与 Dart theme 的双份同步。
- 回喜欢必须复用 `POST /discovery/swipe`;不得新增「接受喜欢」接口复制配对副作用。
- 每个 Task 结束跑对应测试并提交;全部完成后再跑全量门禁。
- 分支:`feat/likes-received`(已从 master 切出)。

---

### Task 1: 后端口径 helper + 列表/计数接口(TDD)

**Files:**
- Modify: `chatapp/discovery/services.py`
- Modify: `chatapp/discovery/serializers.py`
- Modify: `chatapp/discovery/views.py`
- Modify: `chatapp/discovery/urls.py`
- Test: `chatapp/discovery/tests.py`

**Interfaces:**
- Produces: `likes_received_queryset(me) -> QuerySet[Swipe]`
- Produces: `LikeReceivedSerializer`(字段 `user_id` / `im_user_id` / `nickname` / `gender` / `age` / `city` / `bio` / `tags` / `photos` / `liked_at`)
- Produces: `GET /api/v1/discovery/likes`(分页)、`GET /api/v1/discovery/likes/count`(`{"count": N}`)

- [x] **Step 1: 写失败测试**

在 `chatapp/discovery/tests.py` 顶部导入 `Block`:

```python
from moderation.models import Block
```

在文件末尾追加:

```python
class LikesReceivedTests(APITestCase):
    """喜欢我的人:口径、排序、分页、计数、权限与字段脱敏。"""

    URL = "/api/v1/discovery/likes"
    COUNT_URL = "/api/v1/discovery/likes/count"

    def setUp(self):
        self.me = self._make_user("13800138000", gender="male")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, gender="female", birthday="2000-01-01",
                   city="上海", complete=True, photo=True, status=None):
        """造一个用户;默认资料完善并带一张已过审照片。

        Args:
            phone: 手机号,同时用作昵称。
            gender: 性别。
            birthday: 生日;``None`` 表示未填。
            city: 城市。
            complete: 是否把资料置为完善。
            photo: 是否加一张已过审照片。
            status: 显式指定资料状态(用于封禁场景)。

        Returns:
            新建的用户实例。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(
            user=user, nickname=phone, gender=gender, birthday=birthday, city=city,
            bio="你好",
            status=status or (ProfileStatus.COMPLETE if complete else ProfileStatus.INCOMPLETE),
        )
        if photo:
            Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def _like_me(self, user):
        """让对方喜欢我。

        Args:
            user: 发起喜欢的用户。
        """
        Swipe.objects.create(swiper=user, target=self.me, action=SwipeAction.LIKE)

    def _ids(self, resp):
        """取出列表响应里的 ``user_id``。

        Args:
            resp: 接口响应。

        Returns:
            user_id 列表,保持响应顺序。
        """
        return [item["user_id"] for item in resp.json()["results"]]

    def test_lists_only_incoming_likes(self):
        a = self._make_user("13900139000")
        b = self._make_user("13900139001")
        self._like_me(a)
        Swipe.objects.create(swiper=b, target=self.me, action=SwipeAction.PASS)
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), [a.id])

    def test_excludes_people_i_already_swiped(self):
        a = self._make_user("13900139000")
        self._like_me(a)
        Swipe.objects.create(swiper=self.me, target=a, action=SwipeAction.PASS)
        self.assertEqual(self._ids(self.client.get(self.URL)), [])

    def test_matched_people_disappear(self):
        a = self._make_user("13900139000")
        self._like_me(a)
        self.assertEqual(self._ids(self.client.get(self.URL)), [a.id])
        self.client.post("/api/v1/discovery/swipe",
                         {"target_user_id": a.id, "action": "like"}, format="json")
        self.assertTrue(Match.objects.filter(**Match.pair_kwargs(self.me, a)).exists())
        self.assertEqual(self._ids(self.client.get(self.URL)), [])

    def test_excludes_blocked_both_ways(self):
        a = self._make_user("13900139000")
        b = self._make_user("13900139001")
        self._like_me(a)
        self._like_me(b)
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
            self._like_me(user)
        self.assertEqual(self._ids(self.client.get(self.URL)), [])

    def test_newest_like_first(self):
        a = self._make_user("13900139000")
        b = self._make_user("13900139001")
        self._like_me(a)
        self._like_me(b)
        self.assertEqual(self._ids(self.client.get(self.URL)), [b.id, a.id])

    def test_pagination(self):
        users = [self._make_user(f"1390013900{i}") for i in range(3)]
        for user in users:
            self._like_me(user)
        first = self.client.get(self.URL, {"limit": 2})
        self.assertEqual(first.json()["count"], 3)
        self.assertEqual(len(first.json()["results"]), 2)
        self.assertIsNotNone(first.json()["next"])
        second = self.client.get(self.URL, {"limit": 2, "offset": 2})
        self.assertEqual(len(second.json()["results"]), 1)

    def test_count_uses_same_rules(self):
        a = self._make_user("13900139000")
        b = self._make_user("13900139001")
        self._like_me(a)
        self._like_me(b)
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
        self._like_me(a)
        item = self.client.get(self.URL).json()["results"][0]
        self.assertEqual(item["im_user_id"], f"u{a.id}")
        self.assertIn("liked_at", item)
        for hidden in ("phone", "birthday", "ban_reason", "missing_fields"):
            self.assertNotIn(hidden, item)
        self.assertEqual([photo["status"] for photo in item["photos"]], ["approved"])

    def test_age_is_null_when_birthday_missing(self):
        a = self._make_user("13900139000", birthday=None)
        self._like_me(a)
        self.assertIsNone(self.client.get(self.URL).json()["results"][0]["age"])
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd chatapp
python manage.py test discovery.tests.LikesReceivedTests
```

Expected: FAIL(`404` 或 `likes_received_queryset` 不存在)。

- [x] **Step 3: 实现 queryset helper**

在 `chatapp/discovery/services.py` 顶部补导入,并在文件末尾追加:

```python
from moderation.services import blocked_user_ids
from users.models import Photo, PhotoStatus, ProfileStatus

from .models import Swipe, SwipeAction


def likes_received_queryset(me):
    """收到的喜欢:与候选池同口径,排除我已划过 / 双向拉黑 / 资料不全的人。

    Args:
        me: 当前用户。

    Returns:
        以 ``Swipe`` 为行的查询集,按喜欢时间倒序;列表与计数必须共用它。
    """
    swiped = Swipe.objects.filter(swiper=me).values("target_id")
    with_photos = Photo.objects.filter(status=PhotoStatus.APPROVED).values("user_id")
    return (Swipe.objects
            .filter(target=me, action=SwipeAction.LIKE)
            .exclude(swiper_id=me.id)
            .exclude(swiper_id__in=swiped)
            .exclude(swiper_id__in=blocked_user_ids(me))
            .filter(swiper__profile__status=ProfileStatus.COMPLETE)
            .filter(swiper_id__in=with_photos)
            .select_related("swiper__profile")
            .prefetch_related("swiper__photos", "swiper__profile__tags")
            .order_by("-created_at", "-id"))
```

- [x] **Step 4: 实现序列化器**

在 `chatapp/discovery/serializers.py` 中:

```python
from users.models import PhotoStatus, Profile
from users.serializers import PhotoSerializer, TagSerializer

from .models import Swipe, SwipeAction
```

文件末尾追加:

```python
class LikeReceivedSerializer(serializers.ModelSerializer):
    """「喜欢我的人」列表项:对方公开资料 + 喜欢时间。"""

    user_id = serializers.IntegerField(source="swiper.id", read_only=True)
    im_user_id = serializers.CharField(source="swiper.im_user_id", read_only=True)
    nickname = serializers.CharField(source="swiper.profile.nickname", read_only=True)
    gender = serializers.CharField(source="swiper.profile.gender", read_only=True)
    age = serializers.IntegerField(source="swiper.profile.age", read_only=True, allow_null=True)
    city = serializers.CharField(source="swiper.profile.city", read_only=True)
    bio = serializers.CharField(source="swiper.profile.bio", read_only=True)
    tags = TagSerializer(source="swiper.profile.tags", many=True, read_only=True)
    photos = serializers.SerializerMethodField()
    liked_at = serializers.DateTimeField(source="created_at", read_only=True)

    class Meta:
        model = Swipe
        fields = ["user_id", "im_user_id", "nickname", "gender", "age", "city", "bio",
                  "tags", "photos", "liked_at"]

    def get_photos(self, swipe):
        """只返回已过审照片。

        Args:
            swipe: 一条「对方喜欢我」的记录。

        Returns:
            已过审照片的序列化数据。
        """
        approved = [p for p in swipe.swiper.photos.all() if p.status == PhotoStatus.APPROVED]
        return PhotoSerializer(approved, many=True, context=self.context).data
```

- [x] **Step 5: 实现视图与路由**

在 `chatapp/discovery/views.py` 中把 `.services` 的导入改为:

```python
from .services import likes_received_queryset, notify_match
```

文件末尾追加:

```python
@api_view(["GET"])
def likes_received(request):
    """喜欢我的人列表(GET /api/v1/discovery/likes)。

    Args:
        request: DRF 请求对象,支持 ``limit`` / ``offset``。

    Returns:
        分页后的「喜欢我的人」列表,字段见 ``LikeReceivedSerializer``。
    """
    qs = likes_received_queryset(request.user)
    paginator = DefaultLimitOffsetPagination()
    page = paginator.paginate_queryset(qs, request)
    return paginator.get_paginated_response(
        LikeReceivedSerializer(page, many=True, context={"request": request}).data)


@api_view(["GET"])
def likes_received_count(request):
    """喜欢我的人数(GET /api/v1/discovery/likes/count)。

    Args:
        request: DRF 请求对象。

    Returns:
        ``{"count": N}``,与列表同口径,供入口角标使用。
    """
    return Response({"count": likes_received_queryset(request.user).count()})
```

在 `chatapp/discovery/urls.py` 中追加:

```python
    path("likes", views.likes_received),
    path("likes/count", views.likes_received_count),
```

并在 `views.py` 的导入里补 `LikeReceivedSerializer`:

```python
from .serializers import CandidateSerializer, LikeReceivedSerializer, SwipeSerializer
```

- [x] **Step 6: 跑测试确认通过**

```bash
cd chatapp
python manage.py test discovery
```

Expected: PASS(全部 discovery 用例)。

- [x] **Step 7: 提交**

```bash
git add chatapp/discovery/services.py chatapp/discovery/serializers.py chatapp/discovery/views.py chatapp/discovery/urls.py chatapp/discovery/tests.py
git commit -m "feat(discovery): 喜欢我的人列表与计数接口"
```

---

### Task 2: 接口文档同步

**Files:**
- Modify: `docs/api/discovery.md`
- Modify: `docs/api/README.md`

**Interfaces:**
- Consumes: Task 1 的两个接口。

- [x] **Step 1: 在 `docs/api/discovery.md` 末尾追加两节**

```markdown
---

### 3.4 喜欢我的人列表

> `GET` `/api/v1/discovery/likes` · 需要鉴权 · 无额外限流

**接口描述**

分页查询「喜欢我的人」。口径与候选池完全一致:

- 只含 `action = like` 的记录(对方喜欢我);
- 排除**我已经划过的人**(不论 like/pass)、双向拉黑的人;
- 只含资料完善(`status = complete`)且**至少有 1 张已过审照片**的人;
- 按对方喜欢我的时间倒序。

互喜后我已划过对方,因此该用户会立即从本列表消失。轻封禁可读;重封禁返回 `403`。

**请求参数**(Query)

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| limit | 否 | Integer | 每页条数,默认 20,上限 100 |
| offset | 否 | Integer | 偏移量,默认 0 |

**响应参数**

分页对象(见 [conventions.md §分页约定](conventions.md#分页约定)),`results[]` 字段:

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| user_id | Integer | 对方账号 ID |
| im_user_id | String | 对方 IM 账号,格式 `u{user_id}` |
| nickname | String | 昵称 |
| gender | String | `male` / `female` |
| age | Integer / null | 周岁;未填生日时为 `null` |
| city | String | 城市 |
| bio | String | 简介 |
| tags | Object[] | 标签,结构见 [users.md §2.1](users.md) |
| photos | Object[] | **只含已过审**的照片 |
| liked_at | String | 对方喜欢我的时间(UTC,ISO 8601) |

**请求示例**

```bash
curl "http://<域名>/api/v1/discovery/likes?limit=20&offset=0" \
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
      "tags": [
        { "id": 7, "name": "游戏", "icon": "game" }
      ],
      "photos": [
        { "id": 41, "url": "http://<域名>/media/photos/2026/09/seed_30_0.jpg", "status": "approved", "order": 0 }
      ],
      "liked_at": "2026-10-20T02:30:00.000000Z"
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

### 3.5 喜欢我的人数

> `GET` `/api/v1/discovery/likes/count` · 需要鉴权 · 无额外限流

**接口描述**

返回「喜欢我的人」总数,口径与 §3.4 完全一致,仅用于客户端入口角标。

**请求参数**

无。

**响应参数**

| 参数名称 | 类型 | 描述 |
|----------|------|------|
| count | Integer | 喜欢我的人数(已套用 §3.4 的全部排除规则) |

**请求示例**

```bash
curl "http://<域名>/api/v1/discovery/likes/count" \
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

- [x] **Step 2: 更新 `docs/api/README.md`**

把「共 **32** 个接口」改为「共 **34** 个接口」,并在接口一览表 `discovery/swipe` 行后插入:

```markdown
| GET | `/api/v1/discovery/likes` | 喜欢我的人列表(分页) | [discovery](discovery.md) |
| GET | `/api/v1/discovery/likes/count` | 喜欢我的人数 | [discovery](discovery.md) |
```

- [x] **Step 3: 跑文档门禁**

```bash
cd chatapp
python manage.py test config.tests.ApiDocsCoverageTests
```

Expected: PASS。

- [x] **Step 4: 提交**

```bash
git add docs/api/discovery.md docs/api/README.md
git commit -m "docs(api): 补喜欢我的人列表与计数接口"
```

---

### Task 3: App 数据层(model / repository / controller)

**Files:**
- Modify: `app/lib/features/discovery/models.dart`
- Modify: `app/lib/features/discovery/discovery_repository.dart`
- Create: `app/lib/features/discovery/likes_received_controller.dart`
- Test: `app/test/features/discovery/likes_received_repository_test.dart`
- Test: `app/test/features/discovery/likes_received_controller_test.dart`
- Test helper: `app/test/support/sample_data.dart`(追加 `likeReceivedJson`)

**Interfaces:**
- Produces: `LikeReceived { Candidate candidate; DateTime likedAt; }`
- Produces: `DiscoveryRepository.fetchLikesReceived({int limit, int offset}) -> ({List<LikeReceived> items, int count})`
- Produces: `DiscoveryRepository.fetchLikesReceivedCount() -> Future<int>`
- Produces: `LikesReceivedState { List<LikeReceived> items; int count; bool hasMore; int? busyUserId; }`
- Produces: `likesReceivedProvider`(`AsyncNotifierProvider<LikesReceivedController, LikesReceivedState>`)
- Produces: `likesReceivedCountProvider`(`FutureProvider<int>`)
- Produces: `LikesReceivedController.accept(LikeReceived) -> Future<Candidate?>`

- [x] **Step 1: 写失败测试**

在 `app/test/support/sample_data.dart` 末尾追加:

```dart
/// 造一份 GET /discovery/likes 里的一条。
Map<String, dynamic> likeReceivedJson({
  int userId = 9,
  String nickname = '小红',
  int? age = 25,
  String city = '上海',
  List<Map<String, dynamic>> tags = const [],
  String likedAt = '2026-10-20T10:00:00+08:00',
}) =>
    {
      ...candidateJson(userId: userId, nickname: nickname, age: age, city: city, tags: tags),
      'liked_at': likedAt,
    };
```

新建 `app/test/features/discovery/likes_received_repository_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/api_client.dart';
import 'package:chatapp_app/features/discovery/discovery_repository.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;
  late DiscoveryRepository repository;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    repository = DiscoveryRepository(ApiClient(dio));
  });

  test('fetchLikesReceived 解析分页、liked_at 并带上 limit/offset', () async {
    adapter.routes['GET /discovery/likes'] = (options) => ok(pageJson([
          likeReceivedJson(userId: 9, nickname: '小红'),
          likeReceivedJson(userId: 10, nickname: '小刚'),
        ]));

    final page = await repository.fetchLikesReceived(limit: 20, offset: 0);

    expect(page.count, 2);
    expect(page.items.map((item) => item.candidate.nickname), ['小红', '小刚']);
    expect(page.items.first.likedAt.year, 2026);
    expect(adapter.log.last.queryParameters, {'limit': 20, 'offset': 0});
  });

  test('fetchLikesReceivedCount 解析 count', () async {
    adapter.routes['GET /discovery/likes/count'] = (options) => ok({'count': 7});

    expect(await repository.fetchLikesReceivedCount(), 7);
  });
}
```

新建 `app/test/features/discovery/likes_received_controller_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/api_exception.dart';
import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/discovery/likes_received_controller.dart';

import '../../support/sample_data.dart';
import '../../support/scripted_adapter.dart';

void main() {
  late ScriptedAdapter adapter;

  ProviderContainer makeContainer() {
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final refreshDio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    return ProviderContainer(overrides: [
      baseDioProvider.overrideWithValue(dio),
      refreshDioProvider.overrideWithValue(refreshDio),
    ]);
  }

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    adapter = ScriptedAdapter({});
  });

  test('build 拉第一页并带分页参数', () async {
    adapter.routes['GET /discovery/likes'] = (options) =>
        ok(pageJson([likeReceivedJson(userId: 9), likeReceivedJson(userId: 10)]));
    final container = makeContainer();
    addTearDown(container.dispose);

    final state = await container.read(likesReceivedProvider.future);

    expect(state.items.map((item) => item.candidate.userId), [9, 10]);
    expect(state.count, 2);
    expect(state.hasMore, isFalse);
    expect(adapter.log.last.queryParameters, {'limit': 20, 'offset': 0});
  });

  test('accept → like 请求、移除该行、计数 -1、返回候选人', () async {
    adapter.routes['GET /discovery/likes'] = (options) =>
        ok(pageJson([likeReceivedJson(userId: 9), likeReceivedJson(userId: 10)]));
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': true});
    final container = makeContainer();
    addTearDown(container.dispose);
    final state = await container.read(likesReceivedProvider.future);

    final matched = await container
        .read(likesReceivedProvider.notifier)
        .accept(state.items.first);

    expect(matched?.userId, 9);
    final after = container.read(likesReceivedProvider).value!;
    expect(after.items.map((item) => item.candidate.userId), [10]);
    expect(after.count, 1);
    final request = adapter.log.lastWhere((item) => item.method == 'POST');
    expect(request.data, {'target_user_id': 9, 'action': 'like'});
  });

  test('accept 失败 → 行保留、抛 ApiException、重新拉取', () async {
    adapter.routes['GET /discovery/likes'] = (options) =>
        ok(pageJson([likeReceivedJson(userId: 9)]));
    adapter.routes['POST /discovery/swipe'] =
        (options) => jsonError(429, '操作太快了,休息一下吧');
    final container = makeContainer();
    addTearDown(container.dispose);
    final state = await container.read(likesReceivedProvider.future);

    await expectLater(
      container.read(likesReceivedProvider.notifier).accept(state.items.first),
      throwsA(isA<ApiException>()),
    );

    final after = container.read(likesReceivedProvider).value!;
    expect(after.items.map((item) => item.candidate.userId), [9]);
    expect(after.busyUserId, isNull);
  });

  test('loadMore 追加下一页', () async {
    var calls = 0;
    adapter.routes['GET /discovery/likes'] = (options) {
      calls += 1;
      return calls == 1
          ? ok({...pageJson([likeReceivedJson(userId: 9)]), 'count': 2})
          : ok({...pageJson([likeReceivedJson(userId: 10)]), 'count': 2});
    };
    final container = makeContainer();
    addTearDown(container.dispose);
    final state = await container.read(likesReceivedProvider.future);

    await container.read(likesReceivedProvider.notifier).loadMore();

    final after = container.read(likesReceivedProvider).value!;
    expect(after.items.map((item) => item.candidate.userId), [9, 10]);
    expect(adapter.log.last.queryParameters, {'limit': 20, 'offset': 1});
  });
}
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/discovery/likes_received_repository_test.dart test/features/discovery/likes_received_controller_test.dart
```

Expected: FAIL(`LikeReceived` / `likesReceivedProvider` 未定义)。

- [x] **Step 3: 实现 model 与 repository**

在 `app/lib/features/discovery/models.dart` 末尾追加:

```dart
/// 收到的一次喜欢;字段与 GET /discovery/likes 的单项一一对应。
class LikeReceived {
  const LikeReceived({required this.candidate, required this.likedAt});

  factory LikeReceived.fromJson(Map<String, dynamic> json) => LikeReceived(
        candidate: Candidate.fromJson(json),
        likedAt: DateTime.parse(json['liked_at'] as String),
      );

  final Candidate candidate;
  final DateTime likedAt;
}
```

在 `app/lib/features/discovery/discovery_repository.dart` 的 `DiscoveryRepository` 内追加:

```dart
  /// 喜欢我的人(分页);返回本页条目与后端总数。
  Future<({List<LikeReceived> items, int count})> fetchLikesReceived(
      {int limit = 20, int offset = 0}) async {
    final data = await _api.get('/discovery/likes',
        query: {'limit': limit, 'offset': offset}) as Map<String, dynamic>;
    final items = (data['results'] as List<dynamic>)
        .map((item) => LikeReceived.fromJson(item as Map<String, dynamic>))
        .toList();
    return (items: items, count: data['count'] as int);
  }

  /// 入口角标:只查数量。
  Future<int> fetchLikesReceivedCount() async {
    final data = await _api.get('/discovery/likes/count') as Map<String, dynamic>;
    return data['count'] as int;
  }
```

- [x] **Step 4: 实现 controller**

新建 `app/lib/features/discovery/likes_received_controller.dart`:

```dart
import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../chat/match_cache.dart';
import 'discovery_repository.dart';
import 'models.dart';

const _pageSize = 20;

/// 「喜欢我的人」页面状态。
class LikesReceivedState {
  const LikesReceivedState({
    required this.items,
    required this.count,
    this.hasMore = false,
    this.busyUserId,
  });

  final List<LikeReceived> items;
  final int count;
  final bool hasMore;
  final int? busyUserId;

  LikesReceivedState copyWith({
    List<LikeReceived>? items,
    int? count,
    bool? hasMore,
    int? busyUserId,
    bool clearBusy = false,
  }) =>
      LikesReceivedState(
        items: items ?? this.items,
        count: count ?? this.count,
        hasMore: hasMore ?? this.hasMore,
        busyUserId: clearBusy ? null : (busyUserId ?? this.busyUserId),
      );
}

/// 分页拉取 + 回喜欢编排(移除行、计数、配对缓存、角标)。
class LikesReceivedController extends AsyncNotifier<LikesReceivedState> {
  bool _loadingMore = false;

  @override
  Future<LikesReceivedState> build() => _fetch(reset: true);

  Future<LikesReceivedState> _fetch({required bool reset, int offset = 0}) async {
    final page = await ref
        .read(discoveryRepositoryProvider)
        .fetchLikesReceived(limit: _pageSize, offset: offset);
    final items = reset ? page.items : [...(state.value?.items ?? const []), ...page.items];
    return LikesReceivedState(
      items: items,
      count: page.count,
      hasMore: items.length < page.count,
    );
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
          .fetchLikesReceived(limit: _pageSize, offset: current.items.length);
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
  Future<Candidate?> accept(LikeReceived item) async {
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
      ref.invalidate(likesReceivedCountProvider);
      return matched ? item.candidate : null;
    } catch (_) {
      final now = state.value ?? current;
      state = AsyncValue.data(now.copyWith(clearBusy: true));
      await reload();
      rethrow;
    }
  }
}

final likesReceivedProvider =
    AsyncNotifierProvider<LikesReceivedController, LikesReceivedState>(
  LikesReceivedController.new,
  retry: (retryCount, error) => null,
);

/// 入口角标:只查数量,不拉整页。
final likesReceivedCountProvider = FutureProvider<int>((ref) async =>
    ref.watch(discoveryRepositoryProvider).fetchLikesReceivedCount());
```

- [x] **Step 5: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/discovery/likes_received_repository_test.dart test/features/discovery/likes_received_controller_test.dart
```

Expected: PASS。

- [x] **Step 6: 提交**

```bash
git add app/lib/features/discovery/models.dart app/lib/features/discovery/discovery_repository.dart app/lib/features/discovery/likes_received_controller.dart app/test/support/sample_data.dart app/test/features/discovery/likes_received_repository_test.dart app/test/features/discovery/likes_received_controller_test.dart
git commit -m "feat(app): 喜欢我的人数据层(分页 + 回喜欢编排)"
```

---

### Task 4: App 页面 / 入口 / 路由

**Files:**
- Create: `app/lib/features/discovery/widgets/likes_skeleton.dart`
- Create: `app/lib/features/discovery/likes_received_page.dart`
- Modify: `app/lib/features/discovery/discovery_page.dart`
- Modify: `app/lib/router.dart`
- Test: `app/test/features/discovery/likes_received_page_test.dart`
- Test: `app/test/features/discovery/discovery_page_test.dart`(追加入口用例)

**Interfaces:**
- Consumes: Task 3 的 `likesReceivedProvider` / `likesReceivedCountProvider` / `LikeReceived`。
- Produces: 路由 `/likes`;发现页入口 key `discovery.likes`;页面 key `likes.empty` / `likes.retry` / `likes.row.{id}` / `likes.accept.{id}`。

- [x] **Step 1: 写失败测试**

新建 `app/test/features/discovery/likes_received_page_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/features/discovery/likes_received_page.dart';

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
      child: const MaterialApp(home: LikesReceivedPage()),
    ));
    await pumpFrames(tester);   // 骨架/空态涟漪都是无限动画,不能 pumpAndSettle
  }

  testWidgets('空态', (tester) async {
    adapter.routes['GET /discovery/likes'] = (options) => ok(pageJson([]));
    await pumpPage(tester);
    expect(find.byKey(const Key('likes.empty')), findsOneWidget);
    expect(find.text('还没有人喜欢你'), findsOneWidget);
  });

  testWidgets('列表渲染昵称/年龄/城市/标签/时间', (tester) async {
    adapter.routes['GET /discovery/likes'] = (options) => ok(pageJson([
          likeReceivedJson(userId: 9, nickname: '小红', tags: [tagJson(1, '旅行')]),
        ]));
    await pumpPage(tester);
    expect(find.text('小红'), findsOneWidget);
    expect(find.textContaining('25 岁'), findsOneWidget);
    expect(find.textContaining('旅行'), findsOneWidget);
    expect(find.byKey(const Key('likes.accept.9')), findsOneWidget);
  });

  testWidgets('回喜欢 → 行移除并弹配对动效', (tester) async {
    adapter.routes['GET /discovery/likes'] = (options) => ok(pageJson([
          likeReceivedJson(userId: 9, nickname: '小红'),
          likeReceivedJson(userId: 10, nickname: '小刚'),
        ]));
    adapter.routes['GET /users/me'] = (options) => ok(profileJson());
    adapter.routes['POST /discovery/swipe'] = (options) => ok({'matched': true});
    await pumpPage(tester);

    await tester.tap(find.byKey(const Key('likes.accept.9')));
    await tester.pumpAndSettle();

    expect(find.text('你们已互相喜欢'), findsOneWidget);
    expect(find.byKey(const Key('likes.row.9')), findsNothing);
    final request = adapter.log.lastWhere((item) => item.method == 'POST');
    expect(request.data, {'target_user_id': 9, 'action': 'like'});
  });

  testWidgets('加载失败 → 错误态,重试成功', (tester) async {
    adapter.routes['GET /discovery/likes'] = offline;
    await pumpPage(tester);
    expect(find.byKey(const Key('likes.retry')), findsOneWidget);

    adapter.routes['GET /discovery/likes'] =
        (options) => ok(pageJson([likeReceivedJson(userId: 9, nickname: '小红')]));
    await tester.tap(find.byKey(const Key('likes.retry')));
    await tester.pumpAndSettle();
    expect(find.text('小红'), findsOneWidget);
  });
}
```

在 `app/test/features/discovery/discovery_page_test.dart` 追加:

```dart
  testWidgets('发现页显示喜欢我的人数,点入口进列表', (tester) async {
    final adapter = ScriptedAdapter({
      'POST /auth/token/refresh': (options) => ok({'access': 'a2', 'refresh': 'r2'}),
      'GET /users/me': (options) => ok(profileJson()),
      'GET /discovery/candidates': (options) => ok([candidateJson(userId: 9)]),
      'GET /discovery/likes/count': (options) => ok({'count': 3}),
      'GET /discovery/likes': (options) => ok(pageJson([
            likeReceivedJson(userId: 10, nickname: '小刚'),
          ])),
    });
    await pumpApp(tester, adapter, prefs: _loggedIn);
    await tester.pumpAndSettle();

    expect(find.text('3'), findsOneWidget);

    await tester.tap(find.byKey(const Key('discovery.likes')));
    await tester.pumpAndSettle();

    expect(find.text('喜欢我的人'), findsWidgets);
    expect(find.text('小刚'), findsOneWidget);
  });
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd app
../flutter/bin/flutter.bat test test/features/discovery/likes_received_page_test.dart
```

Expected: FAIL(`LikesReceivedPage` 未定义 / 路由不存在)。

- [x] **Step 3: 实现骨架与页面**

新建 `app/lib/features/discovery/widgets/likes_skeleton.dart`:

```dart
import 'package:flutter/material.dart';

import '../../../core/theme/app_radius.dart';
import '../../../core/theme/app_spacing.dart';
import '../../../core/widgets/app_skeleton.dart';

/// 「喜欢我的人」加载骨架:6 行圆头像 + 两条文字条。
class LikesSkeleton extends StatelessWidget {
  const LikesSkeleton({super.key});

  @override
  Widget build(BuildContext context) => Column(
        key: const Key('likes.skeleton'),
        children: [
          for (var i = 0; i < 6; i++)
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

新建 `app/lib/features/discovery/likes_received_page.dart`:

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
import '../../core/widgets/app_sub_page_bar.dart';
import '../../core/widgets/app_text_action.dart';
import '../../core/widgets/app_toast.dart';
import '../../core/widgets/heart_ripple.dart';
import '../profile/profile_controller.dart';
import 'likes_received_controller.dart';
import 'models.dart';
import 'widgets/likes_skeleton.dart';
import 'widgets/match_overlay.dart';

/// 「喜欢我的人」二级页:列表 + 回喜欢 + 四态。
class LikesReceivedPage extends ConsumerWidget {
  const LikesReceivedPage({super.key});

  Future<void> _accept(BuildContext context, WidgetRef ref, LikeReceived item) async {
    try {
      final matched = await ref.read(likesReceivedProvider.notifier).accept(item);
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
    final likes = ref.watch(likesReceivedProvider);
    return Scaffold(
      backgroundColor: AppColors.bgPage,
      body: SafeArea(
        bottom: false,
        child: Column(
          children: [
            const AppSubPageBar(title: '喜欢我的人'),
            Expanded(
              child: likes.when(
                loading: () => const LikesSkeleton(),
                error: (error, _) => AppErrorView(
                  message: error is ApiException ? error.message : '加载失败,请重试',
                  retryKey: const Key('likes.retry'),
                  onRetry: () => ref.read(likesReceivedProvider.notifier).reload(),
                ),
                data: (data) => data.items.isEmpty
                    ? Center(
                        child: AppEmptyState(
                          key: const Key('likes.empty'),
                          mark: const HeartRipple(),
                          title: '还没有人喜欢你',
                          description: '把资料完善一点,多滑几张卡,缘分快到了',
                          action: AppButton(
                            key: const Key('likes.goOnboarding'),
                            label: '去完善资料',
                            onPressed: () => context.go('/onboarding'),
                          ),
                        ),
                      )
                    : NotificationListener<ScrollNotification>(
                        onNotification: (notification) {
                          if (notification.metrics.pixels >=
                              notification.metrics.maxScrollExtent - 120) {
                            ref.read(likesReceivedProvider.notifier).loadMore();
                          }
                          return false;
                        },
                        child: RefreshIndicator(
                          onRefresh: () =>
                              ref.read(likesReceivedProvider.notifier).reload(),
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
                                key: Key('likes.row.${item.candidate.userId}'),
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
                                  key: Key('likes.accept.${item.candidate.userId}'),
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

String _subtitle(LikeReceived item) {
  final candidate = item.candidate;
  final parts = [
    if (candidate.age != null) '${candidate.age} 岁',
    if (candidate.city.isNotEmpty) candidate.city,
    ...candidate.tags.take(3).map((tag) => tag.name),
    formatPostTime(item.likedAt),
  ];
  return parts.join(' · ');
}
```

- [x] **Step 4: 接入发现页入口与路由**

`app/lib/router.dart`:

```dart
import 'features/discovery/likes_received_page.dart';
```

路由表追加:

```dart
      GoRoute(path: '/likes', builder: (context, state) => const LikesReceivedPage()),
```

`app/lib/features/discovery/discovery_page.dart`:

```dart
import '../../core/widgets/app_badge.dart';
import 'likes_received_controller.dart';
```

把标题的 `Padding` 改为:

```dart
            Padding(
              padding: const EdgeInsets.fromLTRB(
                  AppSpacing.pageH, AppSpacing.lg, AppSpacing.pageH, AppSpacing.md),
              child: Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  Text('发现', style: AppText.display.copyWith(color: AppColors.text1)),
                  _LikesEntry(count: ref.watch(likesReceivedCountProvider).value ?? 0),
                ],
              ),
            ),
```

文件末尾追加:

```dart
/// 发现页右上角入口:心形 + 收到喜欢的数量。
class _LikesEntry extends StatelessWidget {
  const _LikesEntry({required this.count});

  final int count;

  @override
  Widget build(BuildContext context) => InkWell(
        key: const Key('discovery.likes'),
        borderRadius: BorderRadius.circular(AppRadius.full),
        onTap: () => context.push('/likes'),
        child: Padding(
          padding: const EdgeInsets.symmetric(
              horizontal: AppSpacing.sm, vertical: AppSpacing.xs),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.favorite_rounded, size: 20, color: AppColors.brand),
              const SizedBox(width: AppSpacing.xs),
              Text('喜欢我的人',
                  style: AppText.caption.copyWith(color: AppColors.text2)),
              if (count > 0) ...[
                const SizedBox(width: AppSpacing.xs),
                AppBadge(count: count),
              ],
            ],
          ),
        ),
      );
}
```

补 `AppRadius` 导入:

```dart
import '../../core/theme/app_radius.dart';
```

- [x] **Step 5: 跑测试确认通过**

```bash
cd app
../flutter/bin/flutter.bat test test/features/discovery/likes_received_page_test.dart test/features/discovery/discovery_page_test.dart
```

Expected: PASS。

- [x] **Step 6: 提交**

```bash
git add app/lib/features/discovery/widgets/likes_skeleton.dart app/lib/features/discovery/likes_received_page.dart app/lib/features/discovery/discovery_page.dart app/lib/router.dart app/test/features/discovery/likes_received_page_test.dart app/test/features/discovery/discovery_page_test.dart
git commit -m "feat(app): 喜欢我的人页面与发现页入口"
```

---

### Task 5: Web 数据层(types / api / store)

**Files:**
- Modify: `web/src/api/types.ts`
- Modify: `web/src/api/discovery.ts`
- Create: `web/src/stores/likes.ts`
- Test: `web/tests/unit/likes-store.spec.ts`

**Interfaces:**
- Produces: `LikeReceived extends Candidate { liked_at: string }`
- Produces: `fetchLikesReceived(limit, offset) -> Promise<Page<LikeReceived>>`
- Produces: `fetchLikesReceivedCount() -> Promise<number>`
- Produces: `useLikesStore()`:`items` / `count` / `loading` / `error` / `busyUserId` / `matched` / `load(reset)` / `loadCount()` / `accept(userId)` / `dismissMatched()`

- [x] **Step 1: 写失败测试**

新建 `web/tests/unit/likes-store.spec.ts`:

```ts
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { useLikesStore } from '@/stores/likes'
import { server } from '../support/server'

const page = (results: unknown[], count = results.length) => ({
  count,
  next: null,
  previous: null,
  results,
})

const like = (id: number) => ({
  user_id: id,
  im_user_id: `u${id}`,
  nickname: `用户${id}`,
  gender: 'female',
  age: 25,
  city: '上海',
  bio: '',
  tags: [],
  photos: [],
  liked_at: '2026-10-20T02:30:00Z',
})

describe('likes store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('拉取喜欢我的人', async () => {
    server.use(mswHttp.get('/api/v1/discovery/likes', () => HttpResponse.json(page([like(1)]))))
    const store = useLikesStore()

    await store.load(true)

    expect(store.items).toHaveLength(1)
    expect(store.count).toBe(1)
  })

  it('accept → 调 like、移除该行、计数 -1', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/likes', () =>
        HttpResponse.json(page([like(1), like(2)])),
      ),
      mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: true })),
    )
    const store = useLikesStore()
    await store.load(true)

    await store.accept(1)

    expect(store.items.map((item) => item.user_id)).toEqual([2])
    expect(store.count).toBe(1)
    expect(store.matched?.user_id).toBe(1)
  })

  it('accept 失败 → 列表保留、错误上抛', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/likes', () => HttpResponse.json(page([like(1)]))),
      mswHttp.post('/api/v1/discovery/swipe', () =>
        HttpResponse.json({ code: 429, message: '操作太快了', request_id: 'r' }, { status: 429 }),
      ),
    )
    const store = useLikesStore()
    await store.load(true)

    await expect(store.accept(1)).rejects.toThrow()

    expect(store.items.map((item) => item.user_id)).toEqual([1])
    expect(store.busyUserId).toBeNull()
  })
})
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd web
npm run test:run -- tests/unit/likes-store.spec.ts
```

Expected: FAIL(`@/stores/likes` 不存在)。

- [x] **Step 3: 实现 types 与 api**

在 `web/src/api/types.ts` 末尾追加:

```ts
/** 「喜欢我的人」列表项:公开资料 + 喜欢时间(discovery.md §3.4)。 */
export interface LikeReceived extends Candidate {
  /** ISO 8601 */
  liked_at: string
}
```

在 `web/src/api/discovery.ts` 中:

```ts
import type { Candidate, LikeReceived, MatchSummary, Page } from './types'
```

文件末尾追加:

```ts
export async function fetchLikesReceived(
  limit = 20,
  offset = 0,
): Promise<Page<LikeReceived>> {
  const { data } = await http.get('/discovery/likes', { params: { limit, offset } })
  return data as Page<LikeReceived>
}

export async function fetchLikesReceivedCount(): Promise<number> {
  const { data } = await http.get('/discovery/likes/count')
  return Number(data.count)
}
```

- [x] **Step 4: 实现 store**

新建 `web/src/stores/likes.ts`:

```ts
import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as discoveryApi from '@/api/discovery'
import type { Candidate, LikeReceived } from '@/api/types'

const PAGE_SIZE = 20

export const useLikesStore = defineStore('likes', () => {
  const items = ref<LikeReceived[]>([])
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
      const page = await discoveryApi.fetchLikesReceived(PAGE_SIZE, offset.value)
      items.value = [...items.value, ...page.results]
      count.value = page.count
      offset.value += page.results.length
    } catch (e) {
      error.value = e instanceof Error ? e.message : '加载失败'
      throw e
    } finally {
      loading.value = false
    }
  }

  async function loadCount(): Promise<void> {
    count.value = await discoveryApi.fetchLikesReceivedCount()
  }

  async function accept(userId: number): Promise<void> {
    const target = items.value.find((item) => item.user_id === userId)
    busyUserId.value = userId
    try {
      const result = await discoveryApi.swipe(userId, 'like')
      items.value = items.value.filter((item) => item.user_id !== userId)
      count.value = Math.max(0, count.value - 1)
      if (result.matched && target) matched.value = target
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

- [x] **Step 5: 跑测试确认通过**

```bash
cd web
npm run test:run -- tests/unit/likes-store.spec.ts
```

Expected: PASS。

- [x] **Step 6: 提交**

```bash
git add web/src/api/types.ts web/src/api/discovery.ts web/src/stores/likes.ts web/tests/unit/likes-store.spec.ts
git commit -m "feat(web): 喜欢我的人数据层(store + api)"
```

---

### Task 6: Web 入口 / 页面 / 路由

**Files:**
- Create: `web/src/features/discovery/LikesEntry.vue`
- Create: `web/src/features/discovery/LikesPage.vue`
- Modify: `web/src/features/discovery/DiscoveryPage.vue`
- Modify: `web/src/router/routes.ts`
- Test: `web/tests/component/likes-page.spec.ts`
- Test: `web/tests/component/discovery-page.spec.ts`(追加入口用例)

**Interfaces:**
- Consumes: Task 5 的 `useLikesStore`。
- Produces: 路由 `/likes`(`name: 'likes'`);入口 class `.likes-entry`。

- [x] **Step 1: 写失败测试**

新建 `web/tests/component/likes-page.spec.ts`:

```ts
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import LikesPage from '@/features/discovery/LikesPage.vue'
import { server } from '../support/server'

const like = (id: number) => ({
  user_id: id,
  im_user_id: `u${id}`,
  nickname: `用户${id}`,
  gender: 'female',
  age: 25,
  city: '上海',
  bio: '',
  tags: [],
  photos: [],
  liked_at: '2026-10-20T02:30:00Z',
})

const page = (results: unknown[]) => ({ count: results.length, next: null, previous: null, results })

function mountPage() {
  return mount(LikesPage, {
    global: {
      plugins: [createPinia()],
      stubs: {
        RouterLink: { template: '<a><slot /></a>' },
      },
    },
  })
}

describe('LikesPage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('空态', async () => {
    server.use(mswHttp.get('/api/v1/discovery/likes', () => HttpResponse.json(page([]))))
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-empty').exists()).toBe(true)
    expect(w.text()).toContain('还没有人喜欢你')
  })

  it('渲染列表并回喜欢', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/likes', () =>
        HttpResponse.json(page([like(1), like(2)])),
      ),
      mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: true })),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('用户1')
    await w.find('.likes__accept').trigger('click')
    await flushPromises()

    expect(w.find('.match-moment').exists()).toBe(true)
    expect(w.findAll('.likes__row')).toHaveLength(1)
    expect(w.text()).toContain('用户2')
  })

  it('加载失败展示错误并可重试', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/discovery/likes', () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json({ code: 50002, message: '服务器开小差了', request_id: 'r' }, { status: 500 })
          : HttpResponse.json(page([like(1)]))
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

在 `web/tests/component/discovery-page.spec.ts` 追加:

```ts
  it('显示喜欢我的人入口与数量', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([card])),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
      mswHttp.get('/api/v1/discovery/likes/count', () => HttpResponse.json({ count: 3 })),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.likes-entry').exists()).toBe(true)
    expect(w.text()).toContain('3')
  })
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd web
npm run test:run -- tests/component/likes-page.spec.ts
```

Expected: FAIL(`LikesPage.vue` 不存在)。

- [x] **Step 3: 实现入口与页面**

新建 `web/src/features/discovery/LikesEntry.vue`:

```vue
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppBadge from '@/components/AppBadge.vue'
import { useLikesStore } from '@/stores/likes'

const store = useLikesStore()
const router = useRouter()

onMounted(() => {
  store.loadCount().catch(() => {})
})
</script>

<template>
  <button type="button" class="likes-entry" @click="router.push({ name: 'likes' })">
    <span class="likes-entry__heart" aria-hidden="true">♥</span>
    <span class="likes-entry__label">喜欢我的人</span>
    <AppBadge v-if="store.count > 0" :count="store.count" />
  </button>
</template>

<style scoped>
.likes-entry {
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
  cursor: pointer;
}
.likes-entry__heart {
  color: var(--color-brand);
  font-size: var(--text-body);
  line-height: 1;
}
</style>
```

新建 `web/src/features/discovery/LikesPage.vue`:

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
import { useLikesStore } from '@/stores/likes'
import type { LikeReceived } from '@/api/types'
import MatchMoment from './MatchMoment.vue'

const store = useLikesStore()
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

async function onAccept(item: LikeReceived) {
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

function subtitle(item: LikeReceived): string {
  const parts = [
    item.age === null ? '' : `${item.age} 岁`,
    item.city,
    ...item.tags.slice(0, 3).map((tag) => tag.name),
    formatLikedAt(item.liked_at),
  ]
  return parts.filter(Boolean).join(' · ')
}

function formatLikedAt(iso: string): string {
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}
</script>

<template>
  <section class="likes">
    <header class="likes__header">
      <RouterLink class="likes__back" :to="{ name: 'discovery' }">← 返回</RouterLink>
      <h1 class="likes__title">喜欢我的人</h1>
    </header>

    <AppSkeleton v-if="store.loading && store.items.length === 0" height="64px" />
    <AppErrorView
      v-else-if="store.error && store.items.length === 0"
      :message="store.error"
      @retry="reload"
    />
    <AppEmpty
      v-else-if="!store.loading && store.items.length === 0"
      emoji="💗"
      title="还没有人喜欢你"
      description="把资料完善一点,多滑几张卡,缘分快到了"
    />

    <ul v-else class="likes__list">
      <li v-for="item in store.items" :key="item.user_id" class="likes__row">
        <RouterLink
          class="likes__person"
          :to="{ name: 'user-profile', params: { id: item.user_id } }"
        >
          <AppAvatar :src="item.photos[0]?.url" :name="item.nickname" :size="44" />
          <span class="likes__meta">
            <span class="likes__name">{{ item.nickname || `用户${item.user_id}` }}</span>
            <span class="likes__sub">{{ subtitle(item) }}</span>
          </span>
        </RouterLink>
        <AppButton
          class="likes__accept"
          variant="ghost"
          :loading="store.busyUserId === item.user_id"
          @click="onAccept(item)"
        >
          喜欢
        </AppButton>
      </li>
    </ul>

    <AppButton v-if="hasMore" class="likes__more" variant="ghost" block @click="loadMore">
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
.likes {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  max-width: var(--form-card-max);
  margin: 0 auto;
  padding: var(--space-xl) var(--space-section-gap);
}
.likes__header {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.likes__back {
  align-self: flex-start;
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-decoration: none;
}
.likes__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.likes__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  margin: 0;
  padding: 0;
  list-style: none;
}
.likes__row {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
}
.likes__person {
  display: flex;
  flex: 1;
  align-items: center;
  gap: var(--space-md);
  min-width: 0;
  color: inherit;
  text-decoration: none;
}
.likes__meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.likes__name {
  overflow: hidden;
  color: var(--color-text1);
  font-size: var(--text-subtitle);
  font-weight: var(--weight-semibold);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.likes__sub {
  overflow: hidden;
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.likes__more {
  align-self: center;
}
</style>
```

- [x] **Step 4: 接入发现页与路由**

`web/src/features/discovery/DiscoveryPage.vue`:

```vue
import LikesEntry from './LikesEntry.vue'
```

模板顶部:

```vue
  <section class="discovery">
    <LikesEntry />
    <MatchesList />
```

`web/src/router/routes.ts` 在 `/settings` 附近追加:

```ts
  {
    path: '/likes',
    name: 'likes',
    component: () => import('@/features/discovery/LikesPage.vue'),
  },
```

- [x] **Step 5: 跑测试确认通过**

```bash
cd web
npm run test:run -- tests/component/likes-page.spec.ts tests/component/discovery-page.spec.ts
```

Expected: PASS。

- [x] **Step 6: 提交**

```bash
git add web/src/features/discovery/LikesEntry.vue web/src/features/discovery/LikesPage.vue web/src/features/discovery/DiscoveryPage.vue web/src/router/routes.ts web/tests/component/likes-page.spec.ts web/tests/component/discovery-page.spec.ts
git commit -m "feat(web): 喜欢我的人页面与发现页入口"
```

---

### Task 7: 全量验证 + 计划回填

**Files:**
- Modify: `docs/superpowers/plans/2026-10-20-likes-received.md`(勾选全部 checkbox,补执行记录)

- [x] **Step 1: 后端全量**

```bash
cd chatapp
python manage.py test
```

Expected: 全绿(前置:Redis 在跑)。

- [x] **Step 2: App 门禁**

```bash
cd app
../flutter/bin/flutter.bat analyze
../flutter/bin/flutter.bat test
```

Expected:`No issues found!` + `All tests passed!`。

- [x] **Step 3: Web 门禁**

```bash
cd web
npm run type-check
npm run lint
npm run test:run
```

Expected:零错误、零告警、全绿。

- [x] **Step 4: 回填计划并提交**

把本文件所有 `- [ ]` 改为 `- [x]`,在末尾补:

## 执行记录

- 2026-10-20:后端接口 + App/Web 双端页面交付;全量门禁通过;PR #8 已创建。
- 后端:`python manage.py test` → `Ran 392 tests in 67.071s` / `OK`(含新增 13 条 `LikesReceivedTests`)。
- App:`flutter analyze` → `No issues found!`;`flutter test` → `All tests passed! (+347)`(新增 11 条 likes 相关用例)。
- Web:`vue-tsc` 零错误;`eslint --max-warnings 0` 零告警;`vitest run` → `65 passed / 315 tests`(新增 7 条 likes 相关用例)。
- 说明:本批未新增 Playwright 端到端(需真后端 + Redis + Celery);「回喜欢 → 配对」由 App 页面测试与 Web 组件测试覆盖。

```bash
git add docs/superpowers/plans/2026-10-20-likes-received.md
git commit -m "docs(plan): 喜欢我的人执行记录与 checkbox 回填"
```

---

## 自检清单(计划写完后逐条核对)

- [x] spec §3 数据口径 → Task 1 的 `likes_received_queryset` 与 7 条测试;
- [x] spec §4 两个接口 → Task 1 视图/路由 + Task 2 文档;
- [x] spec §5 App 入口/页面/四态/回喜欢 → Task 4;
- [x] spec §6 Web 入口/页面/路由 → Task 6;
- [x] spec §8 测试与门禁 → Task 1/3/4/5/6/7;
- [x] 无 TBD / TODO /「类似 Task N」;
- [x] 名称一致:`likes_received_queryset` / `LikeReceivedSerializer` / `likesReceivedProvider` / `likesReceivedCountProvider` / `useLikesStore` / `LikesPage.vue` / `LikesReceivedPage`。
