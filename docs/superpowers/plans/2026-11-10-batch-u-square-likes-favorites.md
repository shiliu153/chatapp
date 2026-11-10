# 批次 U 实施计划:广场点赞列表 + 收藏

- **状态**:待实施
- **Spec 链接**:[批次 R–W 设计](../../specs/2026-11-09-batch-r-w-design.md) §4.4
- **交接来源**:[批次 U/W 交接](2026-11-10-batch-u-w-handoff.md) §2
- **Goal**:广场动态能看「谁点了赞」(点赞列表),能「收藏」一条动态并有「我的收藏」列表;
  收藏是**私密书签**,不通知作者、不产生灰条。
- **Architecture**:收藏 = 新表 `feed.PostFavorite`(`unique(post, user)` + `(user, -created_at)` 索引),
  两个幂等写接口 + 两个游标分页读接口;动态序列化器新增 `is_favorited`,**用 `Exists` 子查询注解**
  (与既有 `liked_by_me` 完全同款 ⇒ 不新增任何 SQL 往返,查询预算不变)。
  点赞列表复用广场可见性(`visible_posts`)与 `author_brief`,不另立口径。
- **Global Constraints**:一单一条栈;改对外字段必须同改 `docs/api/feed.md` + 重生成 `docs/api/openapi.yml`;
  新增 `.py` 补 docstring(`Args:`);App UI 走「心跳」token;不动版本号、不发版、不合并 PR。
- **验收命令**:`scripts/verify.sh backend` / `scripts/verify.sh app` / `scripts/verify.sh web`

---

## 0. 为什么三单不能同时起跑(派单顺序)

后端这一单会**改 `docs/api/openapi.yml`**(新增 `Post.is_favorited` 与 `PostLiker` 组件),
而:

- `verify.sh web` 会跑 `npm run gen:api` 从 `openapi.yml` 重生成 `web/src/api/schema.d.ts`,
  `web/src/api/contract.ts` 的编译期断言要求手写类型的字段名 ⊆ schema;
- `contract.yml`(由 `app/lib/**` 触发)会跑 `scripts/check_app_models.py`,
  要求 App `models.dart` 里 `json['is_favorited']` / `json['liked_at']` 都存在于 `openapi.yml`。

所以 **App 与 Web 必须在 backend 合并之后才能开分支**,否则两条轨会因为「契约里还没有这个字段」直接红
(不是代码问题)。本批按:backend → 合并 → **app ∥ web 两路并行** → 各自合并。

---

## 现状(已核实)

| 已有 | 位置 | 复用方式 |
|---|---|---|
| 广场可见性(排除双向拉黑 + 重封禁作者) | `feed/services.py::visible_base` / `visible_posts` | 点赞列表与收藏列表都走它,不另写一份 |
| 「我是否已赞」的注解写法 | `visible_posts` 里的 `Exists(PostLike…)` | `is_favorited` 照抄这一行,换表名即可 |
| 两段式游标分页 | `feed/services.py::page_visible_posts` + `config/cursor.py` | 收藏列表按**收藏行**做游标(见 Task 1 §4) |
| 作者摘要(昵称 + 第一张已过审照片) | `feed/serializers.py::author_brief` | 点赞列表直接复用;配 `select_related`/`prefetch_related` 防 N+1 |
| 幂等写 + 幂等回执的先例 | `views.post_like`(201/200)、`follow_user`(恒 204) | 收藏**统一恒 204**(见 Task 1 §3 的理由) |
| 查询预算门禁 | `config/test_query_budget.py`(`BUDGET` 字典 + 页大小不变性) | 新增 `post_likes` / `favorites` 两档,`posts` / `following` **保持 15 不变** |
| 读接口限流 | `feed/throttles.py::FollowingReadThrottle` 等 | 新增两个读限流 + 一个写限流 |
| App 动态卡与操作行 | `app/lib/features/square/widgets/post_card.dart` | 加「收藏」菜单项 + 点赞数独立命中区 |
| App 二级页范式 | `app/lib/features/square/my_posts_page.dart` | 点赞列表页与收藏页照抄它的骨架/空态/错误态 |
| Web 动态流 store 工厂 | `web/src/stores/feed.ts::createFeedState` | 收藏列表再建一个 store,不复制分页逻辑 |
| 「我的动态」入口 | App `profile/my_profile_page.dart`;Web `settings/SettingsPage.vue` | 「我的收藏」**并列放在同一处** |
| `app-ui.yml` 的 integration_test 清单 | `.github/workflows/app-ui.yml` 的 `script:` 行**逐个列文件** | 新增 integration_test 必须把路径加进这一行,否则 CI 不跑它 |

---

## Task 1 —— backend(先合,契约源头)

### 1. 模型与迁移

`chatapp/feed/models.py` 新增:

```python
class PostFavorite(models.Model):
    """一条收藏记录(私密书签:不通知作者、不产生灰条)。"""
    post = FK(Post, on_delete=CASCADE, related_name="favorites")
    user = FK(AUTH_USER_MODEL, on_delete=CASCADE, related_name="post_favorites")
    created_at = DateTimeField(auto_now_add=True)
```

- `Meta.constraints = [UniqueConstraint(fields=["post", "user"], name="uniq_post_favorite")]`
  —— 让「重复收藏」在库层只落一行,接口才能做成恒 204 幂等;
- `Meta.indexes = [Index(fields=["user", "-created_at"], name="fav_user_time_idx")]`
  —— 服务「我的收藏」按收藏时间倒序取页;
- `Meta.ordering = ["-created_at", "-id"]`;
- 迁移用 `makemigrations feed` 生成(`feed/migrations/000X_postfavorite.py`),**不手写**。

### 2. `GET /api/v1/posts/{post_id}/likes`(点赞列表)

- 参数:`limit`(默认 20、上限 100)、`before`(游标)。**不提供 `offset` 兼容分支**
  —— 新接口没有老客户端(与 `/feed/following` 同口径)。
- 响应:`{count, next_cursor, has_more, results}`(用 `config.cursor.cursor_body`);
  `results[]` 的元素是
  `{"user_id": int, "nickname": str, "avatar_url": str|null, "liked_at": ISO8601}`。
- 排序:**点赞时间倒序**(`PostLike.created_at` desc,同时间按 `id` desc);
  游标 = `encode_cursor(like.created_at, like.id)`。
- 可见性:
  - 动态本身用 `visible_posts(viewer)` 取,不可见(**含被双向拉黑 / 重封禁作者 / 不存在**)一律 **404**;
  - 点赞者过滤:排除 `blocked_user_ids(viewer)`(双向拉黑)与 `ProfileStatus.BANNED_HEAVY` 作者;
    **`count` 是过滤后的可见人数**(不是原始点赞数);
  - 列表为空 → 200 + `results: []` + `count: 0`,**不 404**。
- 取数:`select_related("user__profile").prefetch_related("user__photos")` 后逐条调
  `author_brief`,**总共 2 条 SQL 且与页大小无关**(禁止在循环里 `User.objects.get`)。
- schema:在 `serializers.py` 定义 `POST_LIKER_SCHEMA = inline_serializer("PostLiker", …)`
  (四个字段见上),响应用 `cursor_page("PostLikerPage", POST_LIKER_SCHEMA)`。
  —— 组件名 `PostLiker` 是**跨栈契约**,App/Web 的手写类型会拿它做字段名断言,别改名。
- 限流:`feed/throttles.py` 新增 `PostLikesReadThrottle`(scope `post_likes_read`,
  `settings.DEFAULT_THROTTLE_RATES` 加 `"post_likes_read": POST_LIKES_READ_RATE`,默认 `120/hour`)。

### 3. `POST` / `DELETE /api/v1/posts/{post_id}/favorite`(收藏 / 取消收藏)

- **两个方法都恒 204**(首次收藏 204、重复收藏 204、没收藏过取消也 204)。
  理由:与 `follow_user` 同口径;App/Web 只做乐观翻转,不需要知道「是不是第一次」,
  少一种状态就少一处分支。
- 动态不可见 → 404(同 §2 口径)。
- 收藏自己的动态**允许**(书签语义,不需要禁止)。
- **不发通知、不产生 IM 灰条**:不调 `notifications.services.notify_on_commit`、
  不碰 `im/tasks.py`(与「关注」同口径,避免通知洪水)。
- 限流:`PostFavoriteThrottle`(scope `post_favorite`,默认 `300/hour`),POST/DELETE 共用额度。

### 4. `GET /api/v1/feed/favorites`(我的收藏)

- 参数:`limit`(默认 20、上限 100)、`before`。响应形状**与广场列表逐字段一致**
  (`{count, next_cursor, has_more, results}`,`results` 是 `PostSerializer`)。
- **排序 = 收藏时间倒序**,不是发帖时间。因此游标建在**收藏行**上:
  1. 先算可见帖子集 `base = visible_base(viewer)`(排除双向拉黑与重封禁作者);
  2. `fav_qs = PostFavorite.objects.filter(user=viewer, post_id__in=base.values("id"))`
     `.order_by("-created_at", "-id")`;
  3. `total = fav_qs.count()`;`apply_before(fav_qs, "created_at", cursor)`;
     取 `values_list("post_id", "created_at", "id")[:limit + 1]` 判 `has_more`;
  4. 用 `visible_posts(viewer, base=base).filter(pk__in=ids)` 取当页带注解对象,
     **按第 3 步的顺序还原**;
  5. `next_cursor = encode_cursor(最后一条收藏行的 created_at, 该收藏行 id)`。
- 帖子被删 → `PostFavorite` 随 `CASCADE` 一起没了,列表自动不出现(无需额外清理逻辑)。
- 限流:`FavoritesReadThrottle`(scope `favorites_read`,默认 `120/hour`)。

### 5. `PostSerializer.is_favorited`

- 序列化器加 `is_favorited = serializers.BooleanField(read_only=True, default=False)`,
  并加进 `Meta.fields`(紧跟 `liked_by_me`)。
- 注解加在**两处**:
  - `services.visible_posts`:`is_favorited=Exists(PostFavorite.objects.filter(post=OuterRef("pk"), user=viewer))`
    —— 覆盖广场列表 / 关注流 / 详情 / 收藏列表 / 发布后的回读;
  - `views.my_posts` 的 `annotate(...)` 里同样加一行。
- **禁止**在序列化器里 `PostFavorite.objects.filter(...).exists()`(逐条查 = 广场一页 20 条变 20 次 SQL,
  `config/test_query_budget.py` 必红)。

### 6. 文档与契约

- `docs/api/feed.md`:
  - 新增 §5.16 点赞列表 / §5.17 收藏动态 / §5.18 取消收藏 / §5.19 我的收藏
    (按既有分册格式:方法、路径、参数表、响应字段表、错误码、备注);
  - §5.1 动态流 / §5.3 我的动态 / §5.4 动态详情 / §5.15 关注流的响应字段表补 `is_favorited`;
  - 头部若有「本册接口一览」表,同步补四行。
- `docs/api/README.md` 的接口总表补四行(点赞列表 / 收藏 / 取消收藏 / 我的收藏)。
- 重生成 `docs/api/openapi.yml`:
  `cd chatapp && python manage.py spectacular --file ../docs/api/openapi.yml --validate`
  —— **禁止手改**。

### 7. 测试(必须真的断言,不是「跑得通」)

1. **点赞列表**:3 人点赞 → 3 条、按点赞时间倒序;
   把其中一人与我对向拉黑 → 只剩 2 条且 `count == 2`;
   动态作者被重封禁 → 整个接口 404;没人点赞 → 200 + `results: []`。
2. **收藏幂等**:POST 两次都 204 且表里只有 1 行;DELETE 两次都 204 且表里 0 行。
3. **收藏不发通知**:收藏前后 `Notification.objects.count()` 不变(IM 侧同理:不新增 `im.tasks` 入队)。
4. **我的收藏**:收藏 3 条 → 按**收藏时间**倒序(故意让「先收藏的是新帖、后收藏的是老帖」,
   断言顺序与发帖时间**相反**,否则这条测试抓不住「按发帖时间排」的实现);
   删掉中间那条帖子 → 列表少一条;作者把我拉黑 → 那条消失。
5. **`is_favorited`**:广场一页里只有收藏过的那条为 `true`;`liked_by_me` 行为不变。
6. **查询预算**:`BUDGET` 新增 `post_likes` 与 `favorites` 两档 + 各自的「页大小不变性」用例;
   **`posts` / `following` 仍为 15**,若实测涨了说明写成了逐条查询,回去改注解而不是调预算。
7. 门禁:`CommentCoverageTests` / `ApiDocsCoverageTests` / openapi 生成物校验 / `config/test_schema_contract.py`。

### 验收口径

1. `scripts/verify.sh backend` 全绿(末尾输出贴进 PR 正文)。
2. 上面 7 组测试全部通过,且新用例**在改回错误实现时会红**(幂等、顺序、拉黑、预算四条尤其)。
3. `git diff docs/api/openapi.yml` 里能看到 `is_favorited` 与 `PostLiker` 组件。

### 禁止事项

不改 `PostLike` / `Post` 既有字段与语义;不改点赞的 201/200 回执;
不给收藏加通知或灰条;不动 `config/test_query_budget.py` 里既有档位的数字;
不手改 `docs/api/openapi.yml`;不新增业务码(404/400/429 走既有信封);不动版本号。

### 不在本期范围

收藏夹分组 / 收藏备注 / 点赞列表按「我关注的人优先」排序 / 收藏数展示在卡片上(本期不做计数列)。

---

## Task 2 —— app(依赖 Task 1 已合并)

### 改什么

1. `app/lib/features/square/models.dart`
   - `Post` 加 `final bool isFavorited`,`fromJson` 读 `json['is_favorited'] as bool? ?? false`,
     `copyWith` 支持改它;
   - 新增 `PostLikeUser { int userId; String nickname; String? avatarUrl; DateTime likedAt; }`
     + `fromJson`(键:`user_id` / `nickname` / `avatar_url` / `liked_at`)。
2. `app/lib/features/square/feed_repository.dart`
   - `fetchLikes(int postId, {int limit = 30, String? cursor})`
     → `({List<PostLikeUser> items, String? nextCursor})`;
   - `setFavorite(int postId, {required bool favorite})` → POST / DELETE `/posts/{id}/favorite`;
   - `fetchFavorites({int limit = 20, String? cursor})` → `({List<Post> items, String? nextCursor})`。
3. `widgets/post_card.dart`
   - `menuAction` 的菜单项:自己 → 「收藏/取消收藏」+「删除」;他人 → 「收藏/取消收藏」+「举报」;
     `value` 用 `'favorite'` / `'unfavorite'`;
   - **点赞数单独可点**:`_PulseIcon` 拆成两个命中区 —— 图标区 = 点赞/取消(现有行为不变),
     数字区 = 打开点赞列表(新增回调 `onTapLikes`);`likeCount == 0` 时数字区不响应(不弹空页)。
     两区**不得重叠**(integration_test 会钉这条)。
4. 控制器(`square_controller.dart`):收藏做**乐观更新 + 失败回滚**(照 `toggleLike` 的写法),
   失败弹 `AppToast`;新增 `FavoritesController`(照 `MyPostsController`,游标分页)。
5. 新页面:
   - `app/lib/features/square/post_likes_page.dart`,路由 `/posts/:id/likes`
     (二级页顶栏「点赞」;行 = 头像 + 昵称 + 相对时间;点行 → `/users/:id`;
     空态「还没有人点赞」;游标分页);
   - `app/lib/features/square/favorites_page.dart`,路由 `/favorites`
     (二级页顶栏「我的收藏」;复用 `PostCard` 流;空态「还没有收藏」)。
6. 入口:`app/lib/features/profile/my_profile_page.dart` 里在「我的动态」**旁边**加「我的收藏」
   → `context.push('/favorites')`。广场/详情页的点赞数字 → `context.push('/posts/${post.id}/likes')`。
7. 新 integration_test `app/integration_test/post_card_actions_test.dart`(照
   `discovery_filter_test.dart` 的写法:直接 pump `PostCard` + 假 `Post`,**不碰网络**),钉三件事:
   ① 点「更多」菜单能展开并**点中「收藏」**(真实 hit test);
   ② 点点赞**数字**触发 `onTapLikes`,点**图标**触发 `onToggleLike`,两者互不串;
   ③ `likeCount == 0` 时点数字不触发 `onTapLikes`。
   并把路径**追加**进 `.github/workflows/app-ui.yml` 的 `script:` 行(只加路径,不改别的)。

### 验收口径

1. `scripts/verify.sh app` 全绿(`flutter analyze` 零告警 + 全部测试)。
2. 新增组件测试:收藏乐观翻转与失败回滚;`is_favorited` 正确映射;点赞列表/收藏列表空态不崩。
3. `no_raw_colors_test.dart` 与 `dark_mode_sweep_test.dart` 仍绿(收藏图标用 `colors.brand` / `colors.text3`,不写裸色值)。
4. **模拟器逐页手测**(`emulator-5554`),坐标一律**用 Pillow 从原始 PNG 量**(见交接文档 §4.1):
   登录 → 广场 → 点某条动态的点赞数 → 点赞列表 → 点某人进资料页 → 返回 →
   长按/更多 → 收藏 → 我的页 → 我的收藏 → 看到那条 → 取消收藏 → 列表变空。截图贴 PR 正文。
5. **PR 必须开 draft**,正文写「等待模拟器验收」。

### 禁止事项

不改滑卡/发现页;不新引依赖;不写 shared_preferences(收藏态以服务端为准);
不碰 `flutter/`;不改既有 Hero 互斥不变式;不把点赞图标区的语义改成「打开列表」。

### 不在本期范围

收藏的本地缓存/离线;点赞列表的「关注」按钮;收藏数角标。

---

## Task 3 —— web(依赖 Task 1 已合并)

### 改什么

1. `web/src/api/types.ts`:`Post` 加 `is_favorited: boolean`;新增
   `PostLiker { user_id: number; nickname: string; avatar_url: string | null; liked_at: string }`。
2. `web/src/api/contract.ts`:补
   `PostLikerUnknown = MustBeNever<UnknownFields<PostLiker, Schema<'PostLiker'>>>`
   (`Post` 那条已有,字段加进 `types.ts` 即可继续成立)。
3. `web/src/api/feed.ts`:`fetchPostLikes` / `favoritePost` / `unfavoritePost` / `fetchFavorites`。
4. `web/src/stores/feed.ts`:收藏乐观更新(照 `toggleLikeIn` 写 `toggleFavoriteIn`,失败回滚);
   新增 `useFavoritesStore`(用 `createFeedState` 工厂,不复制分页逻辑)。
5. `web/src/features/square/PostCard.vue`:加收藏按钮(书签图标,已收藏用 `--brand` 色);
   点赞数**单独可点** → `router.push({ name: 'post-likes', params: { id } })`(0 赞不响应)。
6. 新页面 `web/src/features/square/PostLikesPage.vue`(昵称 + 头像 + 时间,点行进资料页,空态)
   与 `web/src/features/square/FavoritesPage.vue`(复用 `PostCard` 网格,空态);
   `web/src/router/routes.ts` 加 `post-likes`(`/posts/:id/likes`)与 `favorites`(`/favorites`);
   `web/src/components/AppSidebar.vue` 的 name→section 映射把两条新路由归到 `square`。
7. 入口:`web/src/features/settings/SettingsPage.vue` 的菜单里在「我的动态」**旁边**加「我的收藏」。
8. `npm run gen:api` 重生成 `web/src/api/schema.d.ts`(**不手改**)。

### 验收口径

1. `scripts/verify.sh web` 全绿(`vue-tsc` 零错误 + `eslint --max-warnings 0` + vitest 覆盖率门槛)。
2. 组件/store 测试:收藏乐观翻转与失败回滚;`is_favorited` 映射;点赞列表与收藏列表的空态;
   点赞数为 0 时点数字不发请求。
3. `no-raw-color.spec.ts` / `tokens.spec.ts` 仍绿;`npm run build` 通过。

### 禁止事项

不手改 `schema.d.ts`;不改 `tokens.css` 既有变量值;页面不直接调 `http`(只碰 store);
不把点赞图标区的语义改成「打开列表」;不动 `MIN_APP_VERSION` 相关逻辑。

### 不在本期范围

收藏的离线缓存;点赞列表的搜索/筛选;收藏分组。

---

## 执行记录

(实施后补:每单的 PR / 合并 SHA / 关键交付 / 与计划的偏差 / 踩到的坑 / 模拟器验收表)
