# 关系出口:解除配对 + 撤回消息 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 给配对关系一个不可恢复的出口(删配对 + IM 双向黑名单),并让已发消息在 2 分钟内可撤回,App 与 Web 双端对齐。

**Architecture:** 后端把 `Match` 改成软删除(`unmatched_at` / `unmatched_by`),新增 `DELETE /api/v1/matches/{user_id}` 幂等接口,事务提交后入队 IM 双向拉黑任务;撤回完全走腾讯 IM SDK,不碰后端。App/Web 各加一个「⋯」菜单、一个确认弹窗、一条「已解除配对」横幅,以及消息长按菜单里的「撤回」条件项。

**Tech Stack:** Django 5.2 + DRF + Celery + MySQL/Redis;Flutter 3.47 + Riverpod + tencent_cloud_chat_sdk 9.0.7652+1;Vue 3 + Pinia + @tencentcloud/chat。

## Global Constraints

- 后端错误契约:`{"code": <HTTP状态码>, "message": "<中文>", "request_id": ...}`;业务码见 `chatapp/config/error_codes.py`。
- 响应路径禁止任何第三方网络调用;IM 副作用一律走 Celery(`im/tasks.py`),入队用 `transaction.on_commit(fn, robust=True)`。
- 任务参数一律 `user_id`,任务内查库;`im/client.py` 对外永不抛异常。
- 每个新增/修改的 `.py` 文件必须补模块 docstring 与函数/类 docstring(公开函数带参数要写 `Args:`),否则 `CommentCoverageTests` 红。
- 新增/修改任何 `/api/v1` 接口,同一次改动内同步 `docs/api/`;`ApiDocsCoverageTests` 双向比对。
- App 视觉一律走 token(`AppColors` / `AppSpacing` / `AppRadius` / `AppText`),禁止裸 hex、裸字号、裸间距;弹窗用 `AppDialog` / `showConfirmDialog`,Toast 用 `AppToast`。
- 网页端视觉 token 与 App 双份维护(`app/lib/core/theme/*.dart` ↔ `web/src/styles/tokens.css`);本计划不新增 token。
- 撤回窗口 = **2 分钟**,与腾讯控制台默认一致;App 用 `Duration(minutes: 2)`,Web 用 `120_000` ms。
- 已读回执**不做**(腾讯 IM 旗舰版专享,当前体验版)。
- 测试纪律:后端全量绿(前置 Redis)+ `flutter analyze` 零告警 + Web `type-check`/`lint --max-warnings 0`/`vitest` 全绿;IM 一律 mock。

---

## 文件结构

| 文件 | 责任 |
|---|---|
| `chatapp/discovery/models.py` | `Match` 增 `unmatched_at` / `unmatched_by` / `is_active` |
| `chatapp/discovery/migrations/0002_match_unmatched.py` | 迁移 |
| `chatapp/discovery/views.py` | 新增 `unmatch`;`match_list` 过滤;`swipe` 防复活 |
| `chatapp/config/api_urls.py` | 挂 `matches/<int:user_id>` |
| `chatapp/im/tasks.py` | 新增 `unmatch_blacklist` |
| `docs/api/discovery.md` / `README.md` | 接口文档 + 索引 |
| `app/lib/im/im_client.dart` | `ImMessageRevoked`、`revokeMessage`、`ChatMessage.isRevoked` |
| `app/lib/im/tencent_im_client.dart` | SDK 撤回 + 撤回事件 |
| `app/lib/im/im_repository.dart` | `unmatch(userId)` |
| `app/lib/features/chat/recall.dart` | 2 分钟判定(纯函数) |
| `app/lib/features/chat/chat_controller.dart` | `revoke()` + 撤回事件 |
| `app/lib/features/chat/chat_page.dart` | 「⋯」菜单、确认、横幅、输入禁用 |
| `app/lib/features/chat/widgets/message_bubble.dart` | 撤回态渲染 |
| `app/lib/features/profile/user_profile_page.dart` | 资料页入口 |
| `app/test/support/fake_im_client.dart` | 撤回替身 |
| `web/src/im/{types,client}.ts` | 撤回接口 + 事件 |
| `web/src/features/chat/{recall.ts,MessageMenu.vue,MessageBubble.vue,ChatPage.vue,UnmatchDialog.vue,ChatMoreMenu.vue}` | Web 侧能力 |
| `web/src/api/discovery.ts` / `web/src/stores/{discovery,chat}.ts` | 解除接口与状态 |

---

### Task 1: `Match` 软删除字段与迁移

**Files:**
- Modify: `chatapp/discovery/models.py:46-89`
- Create: `chatapp/discovery/migrations/0002_match_unmatched.py`(用 `makemigrations` 生成)
- Test: `chatapp/discovery/tests.py`(新增 `MatchUnmatchModelTests`)

**Interfaces:**
- Produces: `Match.unmatched_at: datetime | None`、`Match.unmatched_by: User | None`、`Match.is_active -> bool`。后续任务全部依赖这三个名字。

- [x] **Step 1: 写失败测试**

在 `chatapp/discovery/tests.py` 的 `MatchModelTests` 之后新增:

```python
class MatchUnmatchModelTests(TestCase):
    """解除配对是软删除:行还在,但 is_active 变 False。"""

    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_new_match_is_active(self):
        match = Match.objects.create(**Match.pair_kwargs(self.a, self.b))
        self.assertIsNone(match.unmatched_at)
        self.assertTrue(match.is_active)

    def test_marked_match_is_inactive(self):
        match = Match.objects.create(**Match.pair_kwargs(self.a, self.b))
        match.unmatched_at = timezone.now()
        match.unmatched_by = self.a
        match.save(update_fields=["unmatched_at", "unmatched_by"])
        match.refresh_from_db()
        self.assertFalse(match.is_active)
        self.assertEqual(match.unmatched_by, self.a)
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd chatapp && python manage.py test discovery.tests.MatchUnmatchModelTests -v 2
```

预期:`AttributeError: 'Match' object has no attribute 'is_active'`。

- [x] **Step 3: 改模型**

`chatapp/discovery/models.py`,在 `Match.created_at` 之后加两列,并在 `other_user` 前加属性:

```python
    unmatched_at = models.DateTimeField("解除配对时间", null=True, blank=True, db_index=True)
    unmatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="matches_unmatched",
        verbose_name="解除操作人",
    )
```

```python
    @property
    def is_active(self) -> bool:
        """配对是否仍然有效(未解除)。

        Returns:
            ``True`` 表示正常配对;``False`` 表示已被任一方解除。
        """
        return self.unmatched_at is None
```

模块 docstring 的「设计要点」补一句:

```
    3. **解除配对是软删除**:``unmatched_at`` 非空即失效,行保留用于审计与防复活。
```

- [x] **Step 4: 生成并检查迁移**

```bash
cd chatapp && python manage.py makemigrations discovery --name match_unmatched
```

打开 `chatapp/discovery/migrations/0002_match_unmatched.py`,确认只含 `AddField` 两条(没有意外删除/重建约束)。

- [x] **Step 5: 跑测试确认通过**

```bash
cd chatapp && python manage.py test discovery.tests.MatchUnmatchModelTests -v 2
```

预期:2 tests OK。

- [x] **Step 6: 提交**

```bash
git add chatapp/discovery/models.py chatapp/discovery/migrations/0002_match_unmatched.py chatapp/discovery/tests.py
git commit -m "feat(discovery): Match 软删除字段(unmatched_at/unmatched_by/is_active)"
```

---

### Task 2: IM 任务 `unmatch_blacklist`

**Files:**
- Modify: `chatapp/im/tasks.py`(在 `blacklist_remove` 之后新增)
- Test: `chatapp/im/tests.py`(在 `ImSideEffectTaskTests` 里加用例 + import)

**Interfaces:**
- Produces: `im.tasks.unmatch_blacklist(user_a_id: int, user_b_id: int) -> None`,双向调用 `im.client.black_list_add`。Task 3 的 `on_commit` 会 `.delay(me.id, other.id)`。

- [x] **Step 1: 写失败测试**

`chatapp/im/tests.py` 顶部 import 区,在 `from .tasks import (...)` 里加 `unmatch_blacklist`(按字母序放在 `sync_profile` 前)。然后在 `ImSideEffectTaskTests` 末尾加:

```python
    def test_unmatch_blacklist_blocks_both_directions(self):
        calls = []
        with patch("im.client.black_list_add",
                   side_effect=lambda *args: calls.append(args) or True):
            unmatch_blacklist.run(self.a.id, self.b.id)
        self.assertEqual(calls, [
            (self.a.im_user_id, self.b.im_user_id),
            (self.b.im_user_id, self.a.im_user_id),
        ])

    def test_unmatch_blacklist_failure_raises_so_celery_retries(self):
        with patch("im.client.black_list_add", return_value=False):
            with self.assertRaises(RuntimeError):
                unmatch_blacklist.run(self.a.id, self.b.id)

    def test_unmatch_blacklist_missing_user_is_noop(self):
        with patch("im.client.black_list_add") as add:
            unmatch_blacklist.run(self.a.id, 999999)
        add.assert_not_called()
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd chatapp && python manage.py test im.tests.ImSideEffectTaskTests -v 2
```

预期:`ImportError: cannot import name 'unmatch_blacklist'`。

- [x] **Step 3: 写任务**

`chatapp/im/tasks.py`,紧跟 `blacklist_remove` 之后:

```python
@shared_task(**RETRY_POLICY)
def unmatch_blacklist(user_a_id: int, user_b_id: int) -> None:
    """解除配对:双向拉黑,双方都收不到、也发不出消息。

    这是「解除配对 = 彻底断开」的唯一实现点:腾讯 IM 只能由管理员侧
    REST 把对方加进黑名单,客户端只能拉黑自己这侧。

    Args:
        user_a_id: 配对一方(通常是发起解除的人)的账号 id。
        user_b_id: 另一方的账号 id。

    Raises:
        RuntimeError: 任一方向拉黑失败,交给 ``RETRY_POLICY`` 重试。
    """
    a, b = _user(user_a_id), _user(user_b_id)
    if a is None or b is None:
        return
    ok_ab = im_client.black_list_add(a.im_user_id, b.im_user_id)
    ok_ba = im_client.black_list_add(b.im_user_id, a.im_user_id)
    _require(ok_ab and ok_ba, "unmatch_blacklist")
```

> 注意:两次调用都要执行完再判 `_require`,不要写成 `a and b` 短路——否则第二个方向永远不拉黑。

- [x] **Step 4: 跑测试确认通过**

```bash
cd chatapp && python manage.py test im.tests.ImSideEffectTaskTests -v 2
```

预期:全绿(含原有 12 条)。

- [x] **Step 5: 提交**

```bash
git add chatapp/im/tasks.py chatapp/im/tests.py
git commit -m "feat(im): 解除配对后双向拉黑任务 unmatch_blacklist"
```

---

### Task 3: 接口 `DELETE /api/v1/matches/{user_id}` + 读取侧过滤

**Files:**
- Modify: `chatapp/config/api_urls.py:28`
- Modify: `chatapp/discovery/views.py`(`swipe` 互喜分支、`match_list`、新增 `unmatch`)
- Test: `chatapp/discovery/tests.py`(新增 `UnmatchApiTests`)

**Interfaces:**
- Consumes: `Match.is_active`(Task 1)、`im.tasks.unmatch_blacklist.delay`(Task 2)。
- Produces: `DELETE /api/v1/matches/{user_id}` → 204 幂等;`GET /matches` 不再返回已解除配对;`POST /discovery/swipe` 对已解除配对返回 `{"matched": false}` 且不重建、不通知。

- [x] **Step 1: 写失败测试**

`chatapp/discovery/tests.py` 末尾新增(复用 `MatchListTests._make_user` 的造数思路,独立写一份避免耦合):

```python
class UnmatchApiTests(APITestCase):
    """解除配对:204 幂等、列表过滤、滑卡不复活、IM 双向拉黑入队。"""

    def setUp(self):
        self.me = self._make_user("13800138000", "我")
        self.other = self._make_user("13900139000", "小红")
        self.match = Match.objects.create(**Match.pair_kwargs(self.me, self.other))
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, nickname):
        """造一个资料完善的用户(带一张已过审照片)。

        Args:
            phone: 手机号。
            nickname: 昵称。

        Returns:
            新建的用户实例。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=nickname, gender="female",
                               birthday="2000-01-01", city="上海", bio="你好",
                               status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def test_unmatch_marks_row_and_enqueues_im(self):
        with patch("im.tasks.unmatch_blacklist.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.delete(f"/api/v1/matches/{self.other.id}")
        self.assertEqual(resp.status_code, 204)
        self.match.refresh_from_db()
        self.assertIsNotNone(self.match.unmatched_at)
        self.assertEqual(self.match.unmatched_by, self.me)
        delay.assert_called_once_with(self.me.id, self.other.id)

    def test_unmatch_is_idempotent(self):
        self.match.unmatched_at = timezone.now()
        self.match.save(update_fields=["unmatched_at"])
        with patch("im.tasks.unmatch_blacklist.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.delete(f"/api/v1/matches/{self.other.id}")
        self.assertEqual(resp.status_code, 204)
        delay.assert_not_called()

    def test_unmatch_without_match_is_204(self):
        stranger = self._make_user("13900139001", "路人")
        resp = self.client.delete(f"/api/v1/matches/{stranger.id}")
        self.assertEqual(resp.status_code, 204)

    def test_match_list_hides_unmatched(self):
        self.match.unmatched_at = timezone.now()
        self.match.save(update_fields=["unmatched_at"])
        self.assertEqual(self.client.get("/api/v1/matches").json()["count"], 0)

    def test_swipe_after_unmatch_does_not_revive(self):
        self.match.unmatched_at = timezone.now()
        self.match.save(update_fields=["unmatched_at"])
        # 双方原本就互相 like,这里再点一次喜欢不应复活
        Swipe.objects.create(swiper=self.other, target=self.me, action=SwipeAction.LIKE)
        with patch("discovery.services.notify_match") as notify:
            resp = self.client.post("/api/v1/discovery/swipe",
                                    {"target_user_id": self.other.id, "action": "like"},
                                    format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["matched"])
        notify.assert_not_called()
        self.match.refresh_from_db()
        self.assertIsNotNone(self.match.unmatched_at)

    def test_unmatch_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.client.delete(f"/api/v1/matches/{self.other.id}").status_code, 401)
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd chatapp && python manage.py test discovery.tests.UnmatchApiTests -v 2
```

预期:404(路由还没挂)。

- [x] **Step 3: 挂路由**

`chatapp/config/api_urls.py`,在 `path("matches", discovery_views.match_list)` 后加:

```python
    path("matches/<int:user_id>", discovery_views.unmatch),
```

- [x] **Step 4: 写视图 + 过滤**

`chatapp/discovery/views.py`:

1) import 区补 `from django.utils import timezone` 与 `from im import tasks as im_tasks`。

2) `match_list` 的查询改成:

```python
    matches = (Match.objects.filter(Q(user_a=me) | Q(user_b=me), unmatched_at__isnull=True)
               .exclude(Q(user_a_id__in=blocked_ids) | Q(user_b_id__in=blocked_ids))
               .select_related("user_a__profile", "user_b__profile")
               .prefetch_related("user_a__photos", "user_b__photos"))
```

3) `swipe` 的互喜分支改成:

```python
    matched = False
    if swipe_obj.action == SwipeAction.LIKE and Swipe.objects.filter(
            swiper=target, target=me, action=SwipeAction.LIKE).exists():
        with transaction.atomic():
            match, created = Match.objects.get_or_create(**Match.pair_kwargs(me, target))
            # 已解除的配对不复活:get_or_create 会捞到软删除的旧行
            if match.unmatched_at is not None:
                matched = False
            else:
                if created:
                    notify_match(match)
                matched = True
```

4) 在 `match_list` 之后新增:

```python
@api_view(["DELETE"])
def unmatch(request, user_id):
    """解除配对(DELETE /api/v1/matches/{user_id})。

    幂等:没有配对 / 已解除 / 解除自己都返回 204,与 ``DELETE /blocks/{user_id}``
    保持一致。解除是软删除(``unmatched_at`` 落时间戳),并双向拉黑 IM,
    之后双方既收不到、也发不出消息。

    Args:
        request: DRF 请求对象。
        user_id: 对方的账号 id。

    Returns:
        204 空响应。
    """
    me = request.user
    match = (Match.objects
             .filter(Q(user_a=me, user_b_id=user_id) | Q(user_b=me, user_a_id=user_id))
             .first())
    if match is None or match.unmatched_at is not None:
        return Response(status=204)
    other = match.other_user(me)
    with transaction.atomic():
        match.unmatched_at = timezone.now()
        match.unmatched_by = me
        match.save(update_fields=["unmatched_at", "unmatched_by"])
        transaction.on_commit(
            lambda: im_tasks.unmatch_blacklist.delay(me.id, other.id), robust=True)
    return Response(status=204)
```

模块 docstring 的「设计要点」补:

```
    4. **解除配对是软删除 + 双向拉黑**:``DELETE /matches/{user_id}`` 只打时间戳,
       读侧统一过滤 ``unmatched_at__isnull=True``;已解除的配对不会被再次滑卡复活。
```

- [x] **Step 5: 跑测试确认通过**

```bash
cd chatapp && python manage.py test discovery -v 2
```

预期:全绿(原有 + 新增 6 条)。

- [x] **Step 6: 提交**

```bash
git add chatapp/config/api_urls.py chatapp/discovery/views.py chatapp/discovery/tests.py
git commit -m "feat(discovery): DELETE /matches/{user_id} 解除配对(软删除 + 双向拉黑 + 防复活)"
```

---

### Task 4: 接口文档与索引

**Files:**
- Modify: `docs/api/discovery.md`(头部计数 + 新增 3.6 节)
- Modify: `docs/api/README.md`(计数 35 → 36 + 接口表一行)

**Interfaces:**
- Consumes: Task 3 的接口行为。
- Produces: `ApiDocsCoverageTests` 双向比对通过。

- [x] **Step 1: 先跑门禁确认会红**

```bash
cd chatapp && python manage.py test config.tests.ApiDocsCoverageTests -v 2
```

预期:报「接口 DELETE /api/v1/matches/{user_id} 未写文档」。

- [x] **Step 2: 改 `docs/api/discovery.md`**

第 3 行改成:

```
本分册含 6 个接口:拉取候选卡、提交滑卡动作、查询配对列表、喜欢我的人列表、喜欢我的人数、解除配对。
```

在文件末尾(`3.5` 之后)追加:

```markdown
---

### 3.6 解除配对

> `DELETE` `/api/v1/matches/{user_id}` · 需要鉴权 · 无额外限流

**接口描述**

解除与指定用户的配对。**不可恢复**:

- 双方配对列表中不再出现彼此;
- 双方 IM 侧互相拉黑,**都收不到、也发不出消息**;
- 再滑到对方也不会重新配对(已划过的人不会回到候选池)。

**幂等**:没有配对、已解除、解除自己都返回 `204`,客户端重试不会报错。

**路径参数**

| 参数名称 | 必填 | 类型 | 描述 |
|----------|------|------|------|
| user_id | 是 | Integer | 对方的账号 ID(与 `GET /matches` 条目里的 `user_id` 一致) |

**响应参数**

成功返回 `204 No Content`,无响应体。

**请求示例**

```bash
curl -X DELETE "http://<域名>/api/v1/matches/8" \
  -H "Authorization: Bearer <access>"
```

**响应示例**

```
HTTP/1.1 204 No Content
```

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 401 | 401 | 未认证或令牌失效 | 重新登录或刷新令牌 |
| 403 | 403 | 账号处于重封禁状态 | 联系客服申诉 |
```

- [x] **Step 3: 改 `docs/api/README.md`**

- 「共 **35** 个接口」→「共 **36** 个接口」;
- 在 `GET /api/v1/matches` 行后插入:

```
| DELETE | `/api/v1/matches/{user_id}` | 解除配对 | [discovery](discovery.md) |
```

- [x] **Step 4: 跑门禁**

```bash
cd chatapp && python manage.py test config.tests -v 2
```

预期:全绿(含 `CommentCoverageTests`)。

- [x] **Step 5: 提交**

```bash
git add docs/api/discovery.md docs/api/README.md
git commit -m "docs(api): 补 DELETE /matches/{user_id} 解除配对,接口数 35→36"
```

---

### Task 5: App IM 层撤回接口与假客户端

**Files:**
- Modify: `app/lib/im/im_client.dart`
- Modify: `app/lib/im/tencent_im_client.dart`
- Modify: `app/test/support/fake_im_client.dart`
- Test: `app/test/im/im_client_test.dart`(若不存在则新建)

**Interfaces:**
- Produces:
  - `class ImMessageRevoked extends ImEvent { const ImMessageRevoked(this.msgId); final String msgId; }`
  - `abstract class ImClient { Future<void> revokeMessage(String msgId); }`
  - `FakeImClient.revokeMessage` 记 `revoke:<msgId>` 到 `log`,`revokeError` 可注入;`emitRevoked(String msgId)` 推事件。

- [x] **Step 1: 写失败测试**

先确认 `app/test/im/` 是否存在;不存在就新建目录与文件 `app/test/im/im_client_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/im/im_client.dart';

import '../support/fake_im_client.dart';

void main() {
  test('撤回:调用流水 + 事件可编排', () async {
    final fake = FakeImClient();
    addTearDown(fake.dispose);

    final events = <ImEvent>[];
    final sub = fake.events.listen(events.add);
    addTearDown(sub.cancel);

    await fake.revokeMessage('sent-1');
    expect(fake.log, contains('revoke:sent-1'));

    fake.emitRevoked('sent-1');
    await Future<void>.delayed(Duration.zero);
    expect(events.single, isA<ImMessageRevoked>());
    expect((events.single as ImMessageRevoked).msgId, 'sent-1');
  });
}
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd app && ../flutter/bin/flutter.bat test test/im/im_client_test.dart
```

预期:编译失败(`FakeImClient` 没有 `revokeMessage`)。

- [x] **Step 3: 改接口与真实实现**

`app/lib/im/im_client.dart`:

- 事件区加:

```dart
/// 消息被撤回(自己撤回或对方撤回都走这里)。
class ImMessageRevoked extends ImEvent {
  const ImMessageRevoked(this.msgId);
  final String msgId;
}
```

- `ChatMessage` 加字段(构造参数 `this.isRevoked = false`、字段 `final bool isRevoked;`、`copyWith({bool? isRevoked})` 与返回体里 `isRevoked: isRevoked ?? this.isRevoked`)。

- `ImClient` 抽象类在 `deleteMessage` 之后加:

```dart
  /// 撤回已发送消息(腾讯默认时限 2 分钟,超时抛 [ImException])。
  Future<void> revokeMessage(String msgId);
```

`app/lib/im/tencent_im_client.dart`:

- `init()` 里 advanced listener 加:

```dart
            onRecvMessageRevoked: (msgId) => _events.add(ImMessageRevoked(msgId)),
```

- 在 `deleteMessage` 之后加:

```dart
  @override
  Future<void> revokeMessage(String msgId) async {
    final result = await TencentImSDKPlugin.v2TIMManager
        .getMessageManager()
        .revokeMessage(msgID: msgId);
    _check(result.code, result.desc);
  }
```

- [x] **Step 4: 改假客户端**

`app/test/support/fake_im_client.dart`,字段区加:

```dart
  /// 置上就让 revokeMessage 抛这个错(测失败提示)。
  Object? revokeError;
```

方法区(`deleteMessage` 之后)加:

```dart
  @override
  Future<void> revokeMessage(String msgId) async {
    log.add('revoke:$msgId');
    if (revokeError != null) throw revokeError!;
  }
```

事件区(`emitIncoming` 之后)加:

```dart
  /// 模拟「消息被撤回」事件。
  void emitRevoked(String msgId) => emit(ImMessageRevoked(msgId));
```

- [x] **Step 5: 跑测试 + analyze**

```bash
cd app && ../flutter/bin/flutter.bat test test/im/im_client_test.dart && ../flutter/bin/flutter.bat analyze
```

预期:1 test OK、analyze 零告警。

- [x] **Step 6: 提交**

```bash
git add app/lib/im/im_client.dart app/lib/im/tencent_im_client.dart app/test/support/fake_im_client.dart app/test/im/im_client_test.dart
git commit -m "feat(app/im): 撤回消息接口 + ImMessageRevoked 事件 + 假客户端替身"
```

---

### Task 6: App 撤回 UI(判定、菜单、渲染、控制器)

**Files:**
- Create: `app/lib/features/chat/recall.dart`
- Modify: `app/lib/features/chat/chat_controller.dart`
- Modify: `app/lib/features/chat/chat_page.dart:153-186`
- Modify: `app/lib/features/chat/widgets/message_bubble.dart`
- Test: `app/test/features/chat/recall_test.dart`、`app/test/features/chat/chat_page_test.dart`、`app/test/features/chat/message_bubble_test.dart`

**Interfaces:**
- Consumes: `ImClient.revokeMessage`、`ImMessageRevoked`、`ChatMessage.isRevoked`(Task 5)。
- Produces:
  - `const recallWindow = Duration(minutes: 2);`
  - `bool canRecall(ChatMessage message, {DateTime? now})`
  - `ChatController.revoke(ChatMessage message) -> Future<void>`
  - UI key:`chat.menu.recall`、`chat.revoked`

- [x] **Step 1: 写失败测试(纯函数)**

新建 `app/test/features/chat/recall_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/features/chat/recall.dart';
import 'package:chatapp_app/im/im_client.dart';

ChatMessage _msg({
  required bool isSelf,
  required DateTime at,
  ChatMessageKind kind = ChatMessageKind.text,
  bool isPending = false,
  bool isFailed = false,
}) =>
    ChatMessage(
      msgId: 'm1',
      peerId: 'u9',
      isSelf: isSelf,
      timestamp: at.millisecondsSinceEpoch,
      kind: kind,
      text: '你好',
      isPending: isPending,
      isFailed: isFailed,
    );

void main() {
  final now = DateTime(2026, 10, 20, 12, 0);

  test('自己 2 分钟内的文字可以撤回', () {
    expect(canRecall(_msg(isSelf: true, at: now.subtract(const Duration(seconds: 30))), now: now),
        isTrue);
  });

  test('超过 2 分钟不能撤回', () {
    expect(canRecall(_msg(isSelf: true, at: now.subtract(const Duration(minutes: 3))), now: now),
        isFalse);
  });

  test('对方的消息不能撤回', () {
    expect(canRecall(_msg(isSelf: false, at: now), now: now), isFalse);
  });

  test('发送中/失败的消息不能撤回', () {
    expect(canRecall(_msg(isSelf: true, at: now, isPending: true), now: now), isFalse);
    expect(canRecall(_msg(isSelf: true, at: now, isFailed: true), now: now), isFalse);
  });

  test('系统灰条不能撤回', () {
    expect(canRecall(_msg(isSelf: true, at: now, kind: ChatMessageKind.matchNotice), now: now),
        isFalse);
  });
}
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/chat/recall_test.dart
```

预期:找不到 `recall.dart`。

- [x] **Step 3: 写判定函数**

新建 `app/lib/features/chat/recall.dart`:

```dart
/// 撤回规则:腾讯 IM 默认只允许撤回 2 分钟内的消息。
///
/// 前端先判一次,是为了「超时就不显示撤回项」,避免用户点下去才报错;
/// 真正的时限仍由服务端强制,超时调用会抛 [ImException]。
library;

import '../../im/im_client.dart';

/// 撤回窗口(与腾讯控制台默认值一致)。
const recallWindow = Duration(minutes: 2);

/// 这条消息当前能否撤回。
///
/// Args:
///   message: 待判断的消息。
///   now: 参照时间(测试注入;默认取当前时间)。
///
/// Returns:
///   自己发的、文字或图片、非发送中/失败、且距发送不超过 [recallWindow] 时为 `true`。
bool canRecall(ChatMessage message, {DateTime? now}) {
  if (!message.isSelf || message.isRevoked) return false;
  if (message.isPending || message.isFailed) return false;
  if (message.kind != ChatMessageKind.text && message.kind != ChatMessageKind.image) return false;
  final at = DateTime.fromMillisecondsSinceEpoch(message.timestamp);
  final current = now ?? DateTime.now();
  final age = current.difference(at);
  return !age.isNegative && age <= recallWindow;
}
```

- [x] **Step 4: 跑测试确认通过**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/chat/recall_test.dart
```

预期:5 tests OK。

- [x] **Step 5: 写控制器测试(失败)**

在 `app/test/features/chat/chat_controller_test.dart` 末尾加(沿用该文件已有的 container/fake 初始化;若结构不同,复用同文件里的 `_container` 或 `setUp` 变量名):

```dart
  test('撤回成功:本地立即置 isRevoked', () async {
    fake.history['u9'] = [
      ChatMessage(
        msgId: 'sent-1',
        peerId: 'u9',
        isSelf: true,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.text,
        text: '打错了',
      ),
    ];
    final container = _container();   // 该文件已有的构造方式
    addTearDown(container.dispose);
    await container.read(chatProvider('u9').future);

    await container.read(chatProvider('u9').notifier).revoke(
        container.read(chatProvider('u9')).value!.single);

    expect(fake.log, contains('revoke:sent-1'));
    expect(container.read(chatProvider('u9')).value!.single.isRevoked, isTrue);
  });

  test('收到 ImMessageRevoked:对应消息置灰', () async {
    fake.history['u9'] = [
      ChatMessage(
        msgId: 'in-1',
        peerId: 'u9',
        isSelf: false,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.text,
        text: '在吗',
      ),
    ];
    final container = _container();
    addTearDown(container.dispose);
    await container.read(chatProvider('u9').future);

    fake.emitRevoked('in-1');
    await Future<void>.delayed(Duration.zero);

    expect(container.read(chatProvider('u9')).value!.single.isRevoked, isTrue);
  });
```

> 如果 `chat_controller_test.dart` 没有 `_container()` 辅助函数,用文件里现有的 provider 容器构造方式(不要新造一套)。

- [x] **Step 6: 跑测试确认失败**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/chat/chat_controller_test.dart
```

预期:`ChatController` 没有 `revoke`。

- [x] **Step 7: 改控制器**

`app/lib/features/chat/chat_controller.dart`:

- `build()` 的事件监听改成:

```dart
    final sub = client.events.listen((event) {
      if (event is ImNewMessage && event.message.peerId == peerId) {
        _append(event.message);
        _markRead(client); // 正看着这个会话,来了就算已读
      } else if (event is ImMessageRevoked) {
        _markRevoked(event.msgId);
      }
    });
```

- 在 `deleteLocal` 之后加:

```dart
  /// 撤回:成功才置灰;失败让异常冒到页面提示,不改本地状态。
  Future<void> revoke(ChatMessage message) async {
    await ref.read(imClientProvider).revokeMessage(message.msgId);
    _markRevoked(message.msgId);
  }

  void _markRevoked(String msgId) {
    final current = state.value ?? const <ChatMessage>[];
    if (!current.any((item) => item.msgId == msgId)) return;
    state = AsyncValue.data(
        [for (final item in current) if (item.msgId == msgId) item.copyWith(isRevoked: true) else item]);
  }
```

- [x] **Step 8: 跑测试确认通过**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/chat/chat_controller_test.dart
```

预期:全绿。

- [x] **Step 9: 写渲染与菜单测试(失败)**

`app/test/features/chat/message_bubble_test.dart` 末尾加:

```dart
  testWidgets('撤回态渲染成居中灰字', (tester) async {
    await tester.pumpWidget(const MaterialApp(
      home: Scaffold(
        body: MessageBubble(
          message: ChatMessage(
            msgId: 'm1',
            peerId: 'u9',
            isSelf: true,
            timestamp: 0,
            kind: ChatMessageKind.text,
            text: '打错了',
            isRevoked: true,
          ),
        ),
      ),
    ));
    expect(find.text('你撤回了一条消息'), findsOneWidget);
    expect(find.byKey(const Key('chat.revoked')), findsOneWidget);
    expect(find.text('打错了'), findsNothing);
  });
```

`app/test/features/chat/chat_page_test.dart` 的 `main()` 里加(复用该文件已有的 `pumpChat`):

```dart
  testWidgets('自己 2 分钟内的消息菜单有「撤回」', (tester) async {
    fake.history['u9'] = [
      ChatMessage(
        msgId: 'sent-1',
        peerId: 'u9',
        isSelf: true,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.text,
        text: '打错了',
      ),
    ];
    await pumpChat(tester);
    await tester.longPress(find.text('打错了'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat.menu.recall')), findsOneWidget);
  });

  testWidgets('超过 2 分钟不显示「撤回」', (tester) async {
    fake.history['u9'] = [
      ChatMessage(
        msgId: 'sent-1',
        peerId: 'u9',
        isSelf: true,
        timestamp: DateTime.now()
            .subtract(const Duration(minutes: 3))
            .millisecondsSinceEpoch,
        kind: ChatMessageKind.text,
        text: '打错了',
      ),
    ];
    await pumpChat(tester);
    await tester.longPress(find.text('打错了'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('chat.menu.recall')), findsNothing);
  });

  testWidgets('点撤回:调 IM 并置灰', (tester) async {
    fake.history['u9'] = [
      ChatMessage(
        msgId: 'sent-1',
        peerId: 'u9',
        isSelf: true,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.text,
        text: '打错了',
      ),
    ];
    await pumpChat(tester);
    await tester.longPress(find.text('打错了'));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.menu.recall')));
    await tester.pumpAndSettle();
    expect(fake.log, contains('revoke:sent-1'));
    expect(find.text('你撤回了一条消息'), findsOneWidget);
  });
```

- [x] **Step 10: 跑测试确认失败**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/chat/message_bubble_test.dart test/features/chat/chat_page_test.dart
```

预期:找不到 `chat.revoked` / `chat.menu.recall`。

- [x] **Step 11: 改渲染**

`app/lib/features/chat/widgets/message_bubble.dart`,在 `build()` 开头(系统灰条分支之前)加:

```dart
    if (message.isRevoked) {
      return Padding(
        key: const Key('chat.revoked'),
        padding: const EdgeInsets.symmetric(vertical: AppSpacing.sm),
        child: Center(
          child: Text(
            message.isSelf ? '你撤回了一条消息' : '对方撤回了一条消息',
            style: AppText.micro.copyWith(color: AppColors.text3),
          ),
        ),
      );
    }
```

- [x] **Step 12: 改菜单**

`app/lib/features/chat/chat_page.dart`:

- 顶部 import 加 `import 'recall.dart';`、`import '../../core/widgets/app_dialog.dart';`(Task 7 也要用)、`import '../../core/widgets/app_toast.dart';`(Task 7)。
- `_showMessageMenu` 的 `items` 改成:

```dart
      items: [
        if (canRecall(message))
          const PopupMenuItem(
              key: Key('chat.menu.recall'), value: 'recall', child: Text('撤回')),
        if (message.kind == ChatMessageKind.text)
          const PopupMenuItem(
              key: Key('chat.menu.copy'), value: 'copy', child: Text('复制')),
        const PopupMenuItem(
            key: Key('chat.menu.delete'), value: 'delete', child: Text('删除')),
      ],
```

- 动作分支加:

```dart
    } else if (action == 'recall') {
      try {
        await ref.read(chatProvider(widget.peerId).notifier).revoke(message);
        if (context.mounted) AppToast.show(context, '已撤回');
      } on ImException catch (error) {
        if (context.mounted) AppToast.show(context, error.message);
      }
    }
```

- [x] **Step 13: 跑测试确认通过**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/chat/recall_test.dart test/features/chat/chat_controller_test.dart test/features/chat/message_bubble_test.dart test/features/chat/chat_page_test.dart
```

预期:全绿。

- [x] **Step 14: 提交**

```bash
git add app/lib/features/chat/recall.dart app/lib/features/chat/chat_controller.dart app/lib/features/chat/chat_page.dart app/lib/features/chat/widgets/message_bubble.dart app/test/features/chat/recall_test.dart app/test/features/chat/chat_controller_test.dart app/test/features/chat/chat_page_test.dart app/test/features/chat/message_bubble_test.dart
git commit -m "feat(app/chat): 2 分钟内撤回消息(菜单条件 + 置灰渲染 + 事件同步)"
```

---

### Task 7: App 解除配对(仓库 + 聊天页「⋯」)

**Files:**
- Modify: `app/lib/im/im_repository.dart`
- Modify: `app/lib/features/chat/chat_page.dart`(`_ChatHeader` + 新增 `_unmatch`)
- Test: `app/test/im/im_repository_test.dart`(若无则新建)、`app/test/features/chat/chat_page_test.dart`

**Interfaces:**
- Consumes: `DELETE /matches/{user_id}`(Task 3)、`showConfirmDialog`、`AppToast`、`matchCacheProvider.refresh()`、`conversationsProvider.reload()`。
- Produces: `ImRepository.unmatch(int userId) -> Future<void>`;UI key `chat.more`、`chat.menu.unmatch`、`chat.unmatch.confirm`。

- [x] **Step 1: 写仓库测试(失败)**

新建/追加 `app/test/im/im_repository_test.dart`:

```dart
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/providers.dart';
import 'package:chatapp_app/im/im_repository.dart';

import '../support/scripted_adapter.dart';

void main() {
  test('unmatch 打 DELETE /matches/{id}', () async {
    final adapter = ScriptedAdapter({
      'DELETE /matches/9': (options) => ok({}, status: 204),
    });
    final dio = Dio(BaseOptions(baseUrl: 'http://test/api/v1'))..httpClientAdapter = adapter;
    final repo = ImRepository(ApiClient(dio));

    await repo.unmatch(9);

    final request = adapter.log.lastWhere((item) => item.method == 'DELETE');
    expect(request.path, '/matches/9');
  });
}
```

> 若 `ApiClient` 的构造签名不是 `ApiClient(dio)`,按 `app/lib/core/api_client.dart` 的实际签名改;测试目标是「断言 DELETE 路径」。

- [x] **Step 2: 跑测试确认失败**

```bash
cd app && ../flutter/bin/flutter.bat test test/im/im_repository_test.dart
```

预期:`ImRepository` 没有 `unmatch`。

- [x] **Step 3: 加仓库方法**

`app/lib/im/im_repository.dart`,在 `fetchMatches` 之后:

```dart
  /// 解除配对:后端软删除 + 双向拉黑 IM;幂等(没配对也 204)。
  Future<void> unmatch(int userId) async {
    await _api.delete('/matches/$userId');
  }
```

- [x] **Step 4: 跑仓库测试**

```bash
cd app && ../flutter/bin/flutter.bat test test/im/im_repository_test.dart
```

预期:1 test OK。

- [x] **Step 5: 写聊天页测试(失败)**

`app/test/features/chat/chat_page_test.dart` 的 `main()` 里加:

```dart
  testWidgets('聊天页「⋯」→ 解除配对 → 删会话并返回', (tester) async {
    adapter.routes['DELETE /matches/9'] = (options) => ok({}, status: 204);
    await pumpChat(tester);

    await tester.tap(find.byKey(const Key('chat.more')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.menu.unmatch')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('chat.unmatch.confirm')));
    await tester.pumpAndSettle();

    final delete = adapter.log.lastWhere((item) => item.method == 'DELETE');
    expect(delete.path, '/matches/9');
    expect(fake.log, contains('deleteConversation:u9'));
  });
```

- [x] **Step 6: 跑测试确认失败**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/chat/chat_page_test.dart
```

预期:找不到 `chat.more`。

- [x] **Step 7: 加「⋯」与解除流程**

`app/lib/features/chat/chat_page.dart`:

1) `_ChatPageState` 里加方法(放在 `_showMessageMenu` 之后):

```dart
  Future<void> _unmatch() async {
    final userId = userIdFromImId(widget.peerId);
    if (userId == null) return;
    final confirmed = await showConfirmDialog(
      context,
      title: '解除配对?',
      message: '解除后双方将无法再聊天,且无法恢复。',
      confirmLabel: '解除配对',
      danger: true,
      confirmKey: const Key('chat.unmatch.confirm'),
    );
    if (!confirmed || !mounted) return;
    try {
      await ref.read(imRepositoryProvider).unmatch(userId);
    } on ApiException catch (error) {
      if (mounted) AppToast.show(context, error.message);
      return;
    }
    try {
      await ref.read(imClientProvider).deleteConversation(widget.peerId);
    } catch (_) {}
    ref.invalidate(matchCacheProvider);
    unawaited(ref.read(conversationsProvider.notifier).reload());
    if (!mounted) return;
    AppToast.show(context, '已解除配对');
    Navigator.of(context).maybePop();
  }
```

2) `_ChatHeader` 增加 `onMore` 参数,把右侧 `const SizedBox(width: 48)` 换成 `PopupMenuButton`(项目已有同款写法,见资料页 `user.more`):

```dart
          PopupMenuButton<String>(
            key: const Key('chat.more'),
            icon: const Icon(Icons.more_horiz_rounded, size: 22, color: AppColors.text1),
            padding: EdgeInsets.zero,
            constraints: const BoxConstraints.tightFor(width: 48, height: 48),
            onSelected: (value) {
              if (value == 'unmatch') onMore();
            },
            itemBuilder: (context) => const [
              PopupMenuItem(
                key: Key('chat.menu.unmatch'),
                value: 'unmatch',
                child: Text('解除配对', style: TextStyle(color: AppColors.danger)),
              ),
            ],
          ),
```

3) `build()` 里 `_ChatHeader(...)` 传 `onMore: _unmatch`。

4) 需要 `import 'dart:async';`(用 `unawaited`)。

- [x] **Step 8: 跑测试确认通过**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/chat/chat_page_test.dart
```

预期:全绿。

- [x] **Step 9: 提交**

```bash
git add app/lib/im/im_repository.dart app/lib/features/chat/chat_page.dart app/test/im/im_repository_test.dart app/test/features/chat/chat_page_test.dart
git commit -m "feat(app/chat): 聊天页「⋯」解除配对(确认 → 删会话 → 回消息页)"
```

---

### Task 8: App 他人资料页入口

**Files:**
- Modify: `app/lib/features/profile/user_profile_page.dart:89-120`(菜单项与动作)
- Test: `app/test/features/profile/user_profile_page_test.dart`

**Interfaces:**
- Consumes: `matchCacheProvider`、`ImRepository.unmatch`、`showConfirmDialog`。
- Produces: 资料页菜单在「已配对」时多一项 key `user.unmatch`;确认按钮 key `user.unmatch.confirm`。

- [x] **Step 1: 写失败测试**

在 `app/test/features/profile/user_profile_page_test.dart` 里加(复用文件已有的挂载辅助;若没有 `GET /matches` 的脚本,补一条):

```dart
  testWidgets('已配对时资料页菜单有「解除配对」', (tester) async {
    adapter.routes['GET /matches'] = (options) =>
        ok(pageJson([matchJson(userId: 9, nickname: '小红')]));
    await pumpProfile(tester, userId: 9);
    await tester.tap(find.byKey(const Key('user.more')));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('user.unmatch')), findsOneWidget);
  });
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/profile/user_profile_page_test.dart
```

预期:找不到 `user.more` / `user.unmatch`。

- [x] **Step 3: 实现**

`app/lib/features/profile/user_profile_page.dart`:

- 读取缓存与配对判定(在 `build` 里):

```dart
    final matches = ref.watch(matchCacheProvider).value ?? const <String, MatchEntry>{};
    final isMatched = matches.containsKey('u$userId');
```

- 菜单 items 加:

```dart
                  if (isMatched)
                    const PopupMenuItem(
                        key: Key('user.unmatch'), value: 'unmatch', child: Text('解除配对')),
```

- 动作分支:

```dart
              value == 'unmatch'
                  ? _unmatch(context, ref)
                  : value == 'report'
                      ? _report(context, ref)
                      : _block(context, ref),
```

- 新增 `_unmatch`:

```dart
  Future<void> _unmatch(BuildContext context, WidgetRef ref) async {
    final confirmed = await showConfirmDialog(
      context,
      title: '解除配对?',
      message: '解除后双方将无法再聊天,且无法恢复。',
      confirmLabel: '解除配对',
      danger: true,
      confirmKey: const Key('user.unmatch.confirm'),
    );
    if (!confirmed || !context.mounted) return;
    try {
      await ref.read(imRepositoryProvider).unmatch(userId);
    } on ApiException catch (error) {
      if (context.mounted) _snack(context, error.message);
      return;
    }
    try {
      await ref.read(imClientProvider).deleteConversation('u$userId');
    } catch (_) {}
    ref.invalidate(matchCacheProvider);
    unawaited(ref.read(conversationsProvider.notifier).reload());
    if (context.mounted) {
      _snack(context, '已解除配对');
      context.pop();
    }
  }
```

> 需要补 import:`dart:async`、`../../im/im_repository.dart`、`../chat/match_cache.dart`、`../chat/conversations_controller.dart`、`../../core/widgets/app_dialog.dart`。

- [x] **Step 4: 跑测试确认通过**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/profile/user_profile_page_test.dart && ../flutter/bin/flutter.bat analyze
```

预期:全绿、零告警。

- [x] **Step 5: 提交**

```bash
git add app/lib/features/profile/user_profile_page.dart app/test/features/profile/user_profile_page_test.dart
git commit -m "feat(app/profile): 他人资料页在已配对时提供解除配对入口"
```

---

### Task 9: App 对方视角横幅与输入禁用

**Files:**
- Modify: `app/lib/features/chat/chat_page.dart`(build 里判定 + 横幅 + `_InputBar(enabled:)`)
- Test: `app/test/features/chat/chat_page_test.dart`

**Interfaces:**
- Consumes: `matchCacheProvider`、`matchCacheProvider.notifier.refresh()`、`systemNoticePeerId`。
- Produces: key `chat.unmatchedBanner`;输入框在解除后 `enabled=false`。

- [x] **Step 1: 写失败测试**

`app/test/features/chat/chat_page_test.dart` 的 `main()` 里加:

```dart
  testWidgets('配对缓存里没有对方:显示横幅且输入框禁用', (tester) async {
    adapter.routes['GET /matches'] = (options) => ok(pageJson([]));
    await pumpChat(tester);

    expect(find.byKey(const Key('chat.unmatchedBanner')), findsOneWidget);
    final input = tester.widget<TextField>(find.byKey(const Key('chat.input')));
    expect(input.enabled, isFalse);
  });

  testWidgets('系统通知会话不显示解除横幅', (tester) async {
    adapter.routes['GET /matches'] = (options) => ok(pageJson([]));
    await pumpChat(tester, peerId: 'system_notice');
    expect(find.byKey(const Key('chat.unmatchedBanner')), findsNothing);
  });
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/chat/chat_page_test.dart
```

预期:找不到 `chat.unmatchedBanner`。

- [x] **Step 3: 实现**

`app/lib/features/chat/chat_page.dart`:

- `initState()` 里加(主动刷新,否则缓存是登录时的旧数据):

```dart
    // 被对方解除配对时,本地缓存还是旧的;进聊天页刷一次才能发现
    unawaited(ref.read(matchCacheProvider.notifier).refresh());
```

> `ConsumerState.initState` 里可以 `ref.read`;若 analyzer 报 `ref` 在 initState 的用法,改放到 `build` 首次执行处(用 `_refreshed` 布尔守卫)。

- `build()` 里加判定:

```dart
    final matchesAsync = ref.watch(matchCacheProvider);
    final cacheReady = matchesAsync.value != null;
    final unmatched = cacheReady &&
        widget.peerId != systemNoticePeerId &&
        !matchesAsync.value!.containsKey(widget.peerId);
```

- 在 `_ChatHeader` 与 `Expanded` 之间插入横幅:

```dart
          if (unmatched)
            Container(
              key: const Key('chat.unmatchedBanner'),
              width: double.infinity,
              color: AppColors.divider,
              padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.pageH, vertical: AppSpacing.sm),
              child: Text('你们已解除配对',
                  textAlign: TextAlign.center,
                  style: AppText.micro.copyWith(color: AppColors.text2)),
            ),
```

- `_InputBar` 传 `enabled: !unmatched`;组件加 `required this.enabled` 字段,`TextField` 加 `enabled: enabled`,三个 `_iconButton` 的 `onPressed` 在禁用时传 `null`:

```dart
                  onPressed: enabled ? onToggleEmoji : null,
```

- [x] **Step 4: 跑测试确认通过**

```bash
cd app && ../flutter/bin/flutter.bat test test/features/chat/chat_page_test.dart && ../flutter/bin/flutter.bat analyze
```

预期:全绿、零告警。

- [x] **Step 5: 提交**

```bash
git add app/lib/features/chat/chat_page.dart app/test/features/chat/chat_page_test.dart
git commit -m "feat(app/chat): 被解除配对后显示横幅并禁用输入"
```

---

### Task 10: Web IM 层撤回接口与事件

**Files:**
- Modify: `web/src/im/types.ts`
- Modify: `web/src/im/client.ts`
- Test: `web/tests/unit/im-client.spec.ts`(若不存在,新建)

**Interfaces:**
- Produces:
  - `ChatMessage.isRevoked: boolean`
  - `ImEvent` 增 `{ type: 'messageRevoked'; msgId: string }`
  - `ImClient.revokeMessage(msgId: string): Promise<void>`
  - `ImEventNames.messageRevoked`(默认 `'onMessageRevoked'`)

- [x] **Step 1: 写失败测试**

`web/tests/unit/im-client.spec.ts`(新建时按下面写;已存在则追加一个 `it`):

```ts
import { describe, expect, it } from 'vitest'
import { createImClient } from '@/im/client'
import type { TimChatLike } from '@/im/types'

function fakeSdk(overrides: Partial<TimChatLike> = {}): TimChatLike {
  return {
    login: async () => ({}),
    logout: async () => {},
    isReady: () => true,
    on: () => {},
    off: () => {},
    createTextMessage: () => ({ ID: 'm1', type: 'TIMTextElem', payload: { text: 'hi' } }),
    createImageMessage: () => ({ ID: 'm2', type: 'TIMImageElem' }),
    sendMessage: async () => ({}),
    deleteMessage: async () => ({}),
    getMessageList: async () => ({ data: { messageList: [] } }),
    setMessageRead: async () => ({}),
    getConversationList: async () => ({ data: { conversationList: [] } }),
    deleteConversation: async () => ({}),
    revokeMessage: async () => ({}),
    ...overrides,
  } as TimChatLike
}

describe('IM 撤回', () => {
  it('revokeMessage 调用 SDK 并广播事件', async () => {
    const revoked: string[] = []
    const sdkRevoked: string[] = []
    let handler: ((event: { data: unknown }) => void) | null = null
    const sdk = fakeSdk({
      on: (name, fn) => {
        if (name === 'onMessageRevoked') handler = fn
      },
      getMessageList: async () => ({
        data: { messageList: [{ ID: 'm1', type: 'TIMTextElem', payload: { text: 'hi' } }] },
      }),
      revokeMessage: async (message) => {
        sdkRevoked.push(message.ID)
        return {}
      },
    })
    const client = createImClient({ sdk, events: { messageRevoked: 'onMessageRevoked' } })
    client.onEvent((event) => {
      if (event.type === 'messageRevoked') revoked.push(event.msgId)
    })

    await client.fetchHistory('u9') // 让客户端记住消息实例
    await client.revokeMessage('m1')
    handler?.({ data: { msgID: 'm1' } })

    expect(sdkRevoked).toEqual(['m1'])
    expect(revoked).toEqual(['m1'])
  })
})
```

> 该用例不依赖登录:SDK 已注入。`revokeMessage` 需要 `known` 里的消息实例,所以先 `fetchHistory` 把实例记下来;找不到实例时实现直接返回(不抛错)。

- [x] **Step 2: 跑测试确认失败**

```bash
cd web && npm run test:run -- tests/unit/im-client.spec.ts
```

预期:`revokeMessage is not a function` / 类型错误。

- [x] **Step 3: 改类型与客户端**

`web/src/im/types.ts`:

- `ChatMessage` 加 `isRevoked: boolean`;
- `ImEvent` 联合加 `| { type: 'messageRevoked'; msgId: string }`;
- `ImClient` 加 `revokeMessage(msgId: string): Promise<void>`;
- `ImEventNames` 加 `messageRevoked: string`;
- `TimChatLike` 加 `revokeMessage(message: TimMessageLike): Promise<unknown>`。

`web/src/im/client.ts`:

- `DEFAULT_EVENT_NAMES` 加 `messageRevoked: 'onMessageRevoked'`;
- `wire()` 加:

```ts
    instance.on(names.messageRevoked, (event) => {
      const data = event.data as { msgID?: string } | string | null
      const msgId = typeof data === 'string' ? data : data?.msgID
      if (msgId) emit({ type: 'messageRevoked', msgId })
    })
```

- 在 `deleteMessage` 之后加:

```ts
  async function revokeMessage(msgId: string): Promise<void> {
    const instance = await ensureSdk()
    const message = known.get(msgId)
    if (!message) return
    await instance.revokeMessage(message)
    known.delete(msgId)
  }
```

- 返回对象加 `revokeMessage`。

`web/src/im/map.ts` 的 `chatMessageFromTim` 返回对象补 `isRevoked: false`。

- [x] **Step 4: 跑测试确认通过**

```bash
cd web && npm run test:run -- tests/unit/im-client.spec.ts
```

预期:1 test OK。

- [x] **Step 5: 提交**

```bash
git add web/src/im/types.ts web/src/im/client.ts web/src/im/map.ts web/tests/unit/im-client.spec.ts
git commit -m "feat(web/im): revokeMessage + messageRevoked 事件"
```

---

### Task 11: Web 撤回 UI(菜单、气泡、store)

**Files:**
- Create: `web/src/features/chat/recall.ts`
- Modify: `web/src/features/chat/MessageMenu.vue`
- Modify: `web/src/features/chat/MessageBubble.vue`
- Modify: `web/src/features/chat/ChatPage.vue`
- Modify: `web/src/stores/chat.ts`
- Test: `web/tests/unit/recall.spec.ts`、`web/tests/component/message-menu.spec.ts`、`web/tests/component/chat-page.spec.ts`

**Interfaces:**
- Consumes: `ChatMessage.isRevoked`、`ImClient.revokeMessage`、`messageRevoked` 事件(Task 10)。
- Produces: `canRecall(message, now?)`;`useChatStore().revokeMessage(message)`;菜单 action 联合类型加 `'recall'`。

- [x] **Step 1: 写失败测试**

`web/tests/unit/recall.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'
import { canRecall, RECALL_WINDOW_MS } from '@/features/chat/recall'
import { ChatMessageKind } from '@/im/types'
import type { ChatMessage } from '@/im/types'

function msg(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    msgId: 'm1',
    peerId: 'u9',
    isSelf: true,
    timestamp: 1_700_000_000_000,
    kind: ChatMessageKind.text,
    text: '你好',
    senderName: '',
    senderAvatar: null,
    isPending: false,
    isFailed: false,
    isRevoked: false,
    imageUrl: null,
    imageLargeUrl: null,
    ...overrides,
  }
}

describe('canRecall', () => {
  const now = 1_700_000_000_000
  it('自己 2 分钟内可撤回', () => {
    expect(canRecall(msg({ timestamp: now - 30_000 }), now)).toBe(true)
  })
  it('超过窗口不可撤回', () => {
    expect(canRecall(msg({ timestamp: now - RECALL_WINDOW_MS - 1 }), now)).toBe(false)
  })
  it('对方消息不可撤回', () => {
    expect(canRecall(msg({ isSelf: false }), now)).toBe(false)
  })
  it('发送中/失败/已撤回不可撤回', () => {
    expect(canRecall(msg({ isPending: true }), now)).toBe(false)
    expect(canRecall(msg({ isFailed: true }), now)).toBe(false)
    expect(canRecall(msg({ isRevoked: true }), now)).toBe(false)
  })
})
```

`web/tests/component/message-menu.spec.ts` 加:

```ts
  it('自己 2 分钟内的消息显示「撤回」', () => {
    const w = mount(MessageMenu, {
      props: { message: msg({ isSelf: true, timestamp: Date.now() - 1000 }), x: 0, y: 0 },
    })
    expect(w.text()).toContain('撤回')
  })

  it('超过 2 分钟不显示「撤回」', () => {
    const w = mount(MessageMenu, {
      props: { message: msg({ isSelf: true, timestamp: Date.now() - 3 * 60 * 1000 }), x: 0, y: 0 },
    })
    expect(w.text()).not.toContain('撤回')
  })
```

- [x] **Step 2: 跑测试确认失败**

```bash
cd web && npm run test:run -- tests/unit/recall.spec.ts tests/component/message-menu.spec.ts
```

预期:找不到 `recall.ts` / 菜单无「撤回」。

- [x] **Step 3: 写判定与组件**

`web/src/features/chat/recall.ts`:

```ts
import { ChatMessageKind } from '@/im/types'
import type { ChatMessage } from '@/im/types'

/** 撤回窗口:与腾讯控制台默认的 2 分钟一致。 */
export const RECALL_WINDOW_MS = 2 * 60 * 1000

/**
 * 这条消息当前能否撤回。
 *
 * @param message 待判断的消息
 * @param now 参照时间戳(毫秒,测试注入)
 */
export function canRecall(message: ChatMessage, now: number = Date.now()): boolean {
  if (!message.isSelf || message.isRevoked) return false
  if (message.isPending || message.isFailed) return false
  if (message.kind !== ChatMessageKind.text && message.kind !== ChatMessageKind.image) return false
  const age = now - message.timestamp
  return age >= 0 && age <= RECALL_WINDOW_MS
}
```

`MessageMenu.vue`:

- `defineEmits` 的 action 联合加 `'recall'`;
- import `canRecall`;
- 在「复制」前加:

```vue
    <button
      v-if="canRecall(props.message)"
      type="button"
      class="message-menu__recall"
      role="menuitem"
      @click="emit('action', 'recall')"
    >
      撤回
    </button>
```

`MessageBubble.vue`:

- 顶部加撤回分支(在 `isNotice` 之前):

```vue
  <p v-if="props.message.isRevoked" class="message-bubble message-bubble--notice">
    {{ props.message.isSelf ? '你撤回了一条消息' : '对方撤回了一条消息' }}
  </p>
```

> 复用 notice 的 pill 样式,不再新增 CSS。

`web/src/stores/chat.ts`:

- 事件处理加:

```ts
    if (event.type === 'messageRevoked') {
      markRevoked(event.msgId)
      return
    }
```

- 加方法:

```ts
  function markRevoked(msgId: string): void {
    const next = { ...messages.value }
    for (const [peerId, list] of Object.entries(next)) {
      if (list.some((item) => item.msgId === msgId)) {
        next[peerId] = list.map((item) =>
          item.msgId === msgId ? { ...item, isRevoked: true } : item,
        )
      }
    }
    messages.value = next
  }

  async function revokeMessage(message: ChatMessage): Promise<void> {
    await ensureConnected()
    await client.revokeMessage(message.msgId)
    markRevoked(message.msgId)
  }
```

- 返回对象加 `revokeMessage`。

`ChatPage.vue`:

- `onMenuAction` 的 action 联合加 `'recall'`,并加分支:

```ts
  if (action === 'recall') {
    await store.revokeMessage(target).catch(() => {})
    return
  }
```

- [x] **Step 4: 跑测试确认通过**

```bash
cd web && npm run test:run -- tests/unit/recall.spec.ts tests/component/message-menu.spec.ts tests/component/chat-page.spec.ts
```

预期:全绿。

- [x] **Step 5: 提交**

```bash
git add web/src/features/chat/recall.ts web/src/features/chat/MessageMenu.vue web/src/features/chat/MessageBubble.vue web/src/features/chat/ChatPage.vue web/src/stores/chat.ts web/tests/unit/recall.spec.ts web/tests/component/message-menu.spec.ts web/tests/component/chat-page.spec.ts
git commit -m "feat(web/chat): 2 分钟内撤回消息(菜单条件 + 撤回态渲染)"
```

---

### Task 12: Web 解除配对(api/store/菜单/对话框/横幅)

**Files:**
- Modify: `web/src/api/discovery.ts`
- Modify: `web/src/stores/discovery.ts`
- Create: `web/src/features/chat/UnmatchDialog.vue`
- Create: `web/src/features/chat/ChatMoreMenu.vue`
- Modify: `web/src/features/chat/ChatPage.vue`
- Test: `web/tests/component/chat-page.spec.ts`

**Interfaces:**
- Consumes: `DELETE /matches/{user_id}`(Task 3)、`chatStore.deleteConversation`、`discoveryStore.matches`。
- Produces: `discoveryApi.unmatch(userId)`、`discoveryStore.unmatch(userId)`;key/class:`chat__more`、`chat__unmatched`。

- [x] **Step 1: 写失败测试**

`web/tests/component/chat-page.spec.ts` 加:

```ts
  it('「⋯」→ 解除配对 → 调接口并跳回消息页', async () => {
    const { w, store } = mountPage()
    const discovery = useDiscoveryStore()
    discovery.unmatch = vi.fn(async () => {})
    store.deleteConversation = vi.fn(async () => {})
    await flushPromises()

    await w.find('.chat__more').trigger('click')
    await w.find('.chat-more__unmatch').trigger('click')
    await flushPromises()
    await w.find('.unmatch-dialog__confirm').trigger('click')
    await flushPromises()

    expect(discovery.unmatch).toHaveBeenCalledWith(8)
    expect(store.deleteConversation).toHaveBeenCalledWith('u8')
  })
```

> `useDiscoveryStore` 要在 `mountPage` 的同一个 pinia 下取;把 `mountPage` 改成同时返回 `pinia` 或在用例里 `setActivePinia(pinia)`。按文件现有写法调整,断言不变。

- [x] **Step 2: 跑测试确认失败**

```bash
cd web && npm run test:run -- tests/component/chat-page.spec.ts
```

预期:找不到 `.chat__more`。

- [x] **Step 3: 实现 api 与 store**

`web/src/api/discovery.ts` 末尾:

```ts
/** 解除配对:幂等(没配对也 204);解除后双方 IM 互相拉黑。 */
export async function unmatch(userId: number): Promise<void> {
  await http.delete(`/matches/${userId}`)
}
```

`web/src/stores/discovery.ts`:

- 新增状态 `const matchesLoaded = ref(false)`;
- `loadMatches` 成功拉到第一页(`reset` 或首次)后置 `matchesLoaded.value = true`;
- 在 `loadMatches` 之后加:

```ts
  async function unmatch(userId: number): Promise<void> {
    await discoveryApi.unmatch(userId)
    matches.value = matches.value.filter((item) => item.user_id !== userId)
    matchesCount.value = Math.max(matchesCount.value - 1, 0)
  }
```

并在 return 里加 `matchesLoaded` 与 `unmatch`。

- [x] **Step 4: 写两个组件**

`web/src/features/chat/ChatMoreMenu.vue`:

```vue
<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'

const emit = defineEmits<{ close: []; unmatch: [] }>()

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  setTimeout(() => window.addEventListener('mousedown', () => emit('close'), { once: true }), 0)
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="chat-more" role="menu">
    <button type="button" class="chat-more__unmatch" role="menuitem" @click="emit('unmatch')">
      解除配对
    </button>
  </div>
</template>

<style scoped>
.chat-more {
  position: absolute;
  top: 56px;
  right: var(--space-section-gap);
  z-index: 130;
  display: flex;
  flex-direction: column;
  min-width: 120px;
  padding: var(--space-xs);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-chip);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-floating-bar);
}
.chat-more button {
  padding: var(--space-sm) var(--space-md);
  border: none;
  border-radius: var(--radius-chip);
  background: none;
  color: var(--color-danger);
  font-size: var(--text-caption);
  text-align: left;
  cursor: pointer;
}
.chat-more button:hover {
  background: var(--hover-overlay);
}
</style>
```

`web/src/features/chat/UnmatchDialog.vue`:

```vue
<script setup lang="ts">
import AppButton from '@/components/AppButton.vue'

defineProps<{ open: boolean; busy?: boolean }>()
const emit = defineEmits<{ close: []; confirm: [] }>()
</script>

<template>
  <div v-if="open" class="unmatch-dialog" role="dialog" aria-modal="true">
    <div class="unmatch-dialog__card">
      <h2 class="unmatch-dialog__title">解除配对?</h2>
      <p class="unmatch-dialog__body">解除后双方将无法再聊天,且无法恢复。</p>
      <div class="unmatch-dialog__actions">
        <AppButton variant="ghost" @click="emit('close')">取消</AppButton>
        <AppButton
          class="unmatch-dialog__confirm"
          variant="danger"
          :loading="busy"
          @click="emit('confirm')"
        >
          解除配对
        </AppButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.unmatch-dialog {
  position: fixed;
  inset: 0;
  z-index: 150;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--scrim-strong);
}
.unmatch-dialog__card {
  width: 320px;
  padding: var(--space-xxl);
  border-radius: var(--radius-sheet);
  background: var(--color-bg-card);
  text-align: center;
}
.unmatch-dialog__title {
  margin: 0 0 var(--space-sm);
  font-size: var(--text-subtitle);
}
.unmatch-dialog__body {
  margin: 0 0 var(--space-xl);
  color: var(--color-text2);
  font-size: var(--text-caption);
}
.unmatch-dialog__actions {
  display: flex;
  gap: var(--space-md);
}
.unmatch-dialog__actions > * {
  flex: 1;
}
</style>
```

> 全部使用现有 token(`--scrim-strong`、`--radius-sheet` 均已在 `tokens.css` 中),**不新增 token**。

- [x] **Step 5: 改 ChatPage**

`web/src/features/chat/ChatPage.vue`:

- import:

```ts
import { useRouter } from 'vue-router'
import { useDiscoveryStore } from '@/stores/discovery'
import ChatMoreMenu from './ChatMoreMenu.vue'
import UnmatchDialog from './UnmatchDialog.vue'
```

- 状态:

```ts
const router = useRouter()
const discovery = useDiscoveryStore()
const moreOpen = ref(false)
const unmatchOpen = ref(false)
const unmatching = ref(false)

/** 配对列表已加载且没有这个人 → 已被解除(系统通知除外)。 */
const unmatched = computed(
  () =>
    props.peerId !== 'system_notice' &&
    discovery.matchesLoaded &&
    !discovery.matches.some((item) => item.im_user_id === props.peerId),
)

async function onUnmatch(): Promise<void> {
  if (unmatching.value) return
  unmatching.value = true
  try {
    await discovery.unmatch(Number(props.peerId.replace('u', '')))
    await store.deleteConversation(props.peerId).catch(() => {})
    unmatchOpen.value = false
    await router.push({ name: 'chats' })
  } finally {
    unmatching.value = false
  }
}
```

- `onMounted` 里加:

```ts
  if (!discovery.matchesLoaded) await discovery.loadMatches(true).catch(() => {})
```

- header 右侧加:

```vue
      <button type="button" class="chat__more" aria-label="更多" @click="moreOpen = !moreOpen">
        ⋯
      </button>
```

- header 之后加横幅:

```vue
    <p v-if="unmatched" class="chat__unmatched">你们已解除配对</p>
```

- footer 里给 `AppInput` 加 `:disabled="unmatched"`,`AppButton` 加 `:disabled="unmatched"`(`AppInput` 已支持 `disabled` 属性)。

- 模板末尾加:

```vue
    <ChatMoreMenu v-if="moreOpen" @close="moreOpen = false" @unmatch="unmatchOpen = true; moreOpen = false" />
    <UnmatchDialog :open="unmatchOpen" :busy="unmatching" @close="unmatchOpen = false" @confirm="onUnmatch" />
```

- 样式加:

```css
.chat__more {
  margin-left: auto;
  border: none;
  background: none;
  font-size: var(--text-title);
  color: var(--color-text2);
  cursor: pointer;
}
.chat__unmatched {
  margin: 0;
  padding: var(--space-xs) var(--space-section-gap);
  background: var(--color-divider);
  color: var(--color-text2);
  font-size: var(--text-badge);
  text-align: center;
}
```

- `discoveryStore` 需要 `matchesLoaded` 标记:在 `loadMatches` 成功后置 `matchesLoaded.value = true`,并在 return 里导出。

- [x] **Step 6: 跑测试确认通过**

```bash
cd web && npm run test:run -- tests/component/chat-page.spec.ts
```

预期:全绿。

- [x] **Step 7: 提交**

```bash
git add web/src/api/discovery.ts web/src/stores/discovery.ts web/src/features/chat/UnmatchDialog.vue web/src/features/chat/ChatMoreMenu.vue web/src/features/chat/ChatPage.vue web/tests/component/chat-page.spec.ts
git commit -m "feat(web/chat): 解除配对(⋯ 菜单 + 确认弹窗 + 已解除横幅)"
```

---

### Task 13: 全量验证与文档回填

**Files:**
- Modify: `docs/superpowers/specs/2026-10-20-relationship-exits-design.md`(状态行)
- Modify: `docs/superpowers/plans/2026-10-20-relationship-exits.md`(checkbox 全勾 + 执行记录)
- Modify: `CLAUDE.md`(里程碑表补一行 + 「下一步」更新)
- Modify: `README.md`(若「下一步」/接口表有对应描述)

- [x] **Step 1: 后端全量**

```bash
cd chatapp && python manage.py test
```

前置:Redis 在跑(`docker compose -f docker-compose.dev.yml up -d`)。预期全绿,含 `ApiDocsCoverageTests` / `CommentCoverageTests`。

- [x] **Step 2: App 全量**

```bash
cd app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test
```

预期:零告警、全绿。

- [x] **Step 3: Web 全量**

```bash
cd web && npm run type-check && npm run lint && npm run test:coverage
```

预期:零错误、零告警、覆盖率达标(70/60/70/70)。

- [x] **Step 4: 双模拟器手测清单**

1. 双端登录两个账号并配对;
2. A 在聊天页「⋯」→ 解除配对 → 确认:A 回到消息页、该会话消失;
3. B 刷新配对列表:B 侧该配对消失;B 打开聊天页:出现「你们已解除配对」横幅、输入框禁用;
4. B 尝试用 `im_send` 代发消息给 A:A 收不到(B 侧发送失败);
5. A 发消息 → 2 分钟内长按「撤回」:双方都显示「撤回了一条消息」;
6. A 发消息 → 等 3 分钟 → 长按:没有「撤回」项;
7. 系统通知会话:不出现「你们已解除配对」横幅。

- [x] **Step 5: 回填文档**

- spec 第 3 行状态改「已交付(YYYY-MM-DD)」;
- plan 全部 `- [x]`,末尾加「执行记录」段(测试数、commit、手测结论);
- `CLAUDE.md` 里程碑表加一行:

```
| 2026-10-2X | P1-3「关系出口」交付(解除配对软删除 + IM 双向拉黑 + 2 分钟撤回;已读回执挂起待旗舰版;后端 XXX / App XXX / Web XXX 测试绿) |
```

- `CLAUDE.md`「下一步」改成 P1-4 推送 + 上线合规轨。

- [x] **Step 6: 提交**

```bash
git add docs/superpowers/specs/2026-10-20-relationship-exits-design.md docs/superpowers/plans/2026-10-20-relationship-exits.md CLAUDE.md README.md
git commit -m "docs: P1-3 关系出口收尾回填(验收结果与里程碑)"
```

---

## 自检清单(写完后逐条核对)

- [x] 后端:软删除、幂等、防复活、双向拉黑、文档门禁、注释门禁全部有对应任务;
- [x] App:撤回(条件/渲染/事件)、解除(聊天页/资料页)、对方视角横幅与禁用全部有对应任务;
- [x] Web:撤回、解除、横幅全部有对应任务;
- [x] 类型一致:`revokeMessage(String msgId)` / `revokeMessage(msgId: string)` / `canRecall(message, now)` 在两端任务里名字一致;
- [x] 没有「TBD / 类似 Task N / 自行补充」类占位。

---

## 执行记录(2026-10-20)

**结果**:13 个任务全部完成,分支 `feat/p1-3-relationship-exits`。

**门禁**

| 套件 | 结果 |
|---|---|
| 后端 `python manage.py test` | 420 tests OK(含 `ApiDocsCoverageTests` / `CommentCoverageTests`) |
| App `flutter analyze` | No issues found |
| App `flutter test` | 375 tests passed |
| Web `vue-tsc` / `eslint --max-warnings 0` | 零错误 / 零告警 |
| Web `npm run test:coverage` | 336 tests passed;覆盖率 86.6 / 82.29 / 81.83 / 88.61(门槛 70/60/70/70) |

**提交**(均在 `feat/p1-3-relationship-exits`)

1. `feat(discovery): Match 软删除字段(unmatched_at/unmatched_by/is_active)`
2. `feat(im): 解除配对后双向拉黑任务 unmatch_blacklist`
3. `feat(discovery): DELETE /matches/{user_id} 解除配对(软删除 + 双向拉黑 + 防复活)`
4. `docs(api): 补 DELETE /matches/{user_id} 解除配对,接口数 35→36`
5. `feat(app/im): 撤回消息接口 + ImMessageRevoked 事件 + 假客户端替身`
6. `feat(app/chat): 2 分钟内撤回消息(菜单条件 + 置灰渲染 + 事件同步)`
7. `feat(app/chat): 聊天页「⋯」解除配对(确认 → 删会话 → 回消息页)`
8. `feat(app/profile): 他人资料页在已配对时提供解除配对入口`
9. `feat(app/chat): 被解除配对后显示横幅并禁用输入`
10. `feat(web/im): revokeMessage + messageRevoked 事件`
11. `feat(web/chat): 2 分钟内撤回消息(菜单条件 + 撤回态渲染)`
12. `feat(web/chat): 解除配对(⋯ 菜单 + 确认弹窗 + 已解除横幅)`

**与计划的偏差 / 踩到的坑**

1. **本机 Redis 端口**:容器实际映射在 `16379`(不是 compose 里的 6379),后端测试统一用
   `$env:TEST_REDIS_PORT="16379"` 跑(settings 的 `TEST_REDIS_PORT` 就是为这种场景留的)。
2. **`PopupMenuButton.constraints` 是「菜单」约束,不是按钮尺寸**:第一版把它当按钮宽高传,
   菜单被压成 48×48 且点击命中不了(测试报 “would not hit test”)。改成 `SizedBox(48,48)` 包按钮。
3. **资料页测试缺登录态**:`matchCacheProvider` 依赖 `sessionProvider`,原测试没覆盖登录态,
   配对缓存永远是空 → 「解除配对」菜单项测不出来。测试补 `_LoggedInSession` 覆盖。
4. **Web `ChatMessage` 新增必填 `isRevoked`**:所有测试夹具(5 个文件)同步补齐,否则 `vue-tsc` 红。
5. **App 无 `/chats` 路由**:消息页是 HomeShell 的 tab,解除后回退用 `Navigator.maybePop()`
   (spec §4.2 已同步修正)。

**待用户执行(真机)**

双模拟器按 Task 13 Step 4 的 7 条清单手测:解除配对后双向发消息失败(20006)、对方视角横幅 +
输入禁用、2 分钟内撤回双方置灰、超时无「撤回」、系统通知不显示横幅。手测通过后把本段补成
「已手测通过」并合回 `master`。
