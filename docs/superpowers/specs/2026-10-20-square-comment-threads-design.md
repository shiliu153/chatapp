# 广场评论:楼中楼与回复提醒(设计)

日期:2026-10-20 · 状态:已交付(2026-10-20;三端门禁全绿)
上游:P1「留存闭环」收官后的新功能批次(用户选定:广场评论楼中楼 + @ 提醒)。
下游:实施计划 `docs/superpowers/plans/2026-10-20-square-comment-threads.md`。

## 1. 背景与定位

广场评论目前是**单层扁平列表**:`PostComment` 只有 `post` / `author` / `text`,
所有评论按时间排成一行;评论后只给**动态作者**发一条 IM 灰条
(`feed/services.py::notify_post_commented` → `im/tasks.py::post_commented`)。

这带来两个真实问题:

1. **无法对话**。A 在评论里问了一句,B 想回答,只能再发一条顶层评论 ——
   列表里两条评论互不相干,第三条评论插进来就把话题冲散了;
2. **评论者之间没有任何提醒**。被回复的人只有下次打开这条动态才可能看到,
   「回复」只能靠正文手写「@某人」,对方完全不知道。

**目标:** 给评论加**两级楼中楼**(顶级评论 + 回复),回复某人时自动提醒对方
(IM 灰条),并允许作者删除自己的评论;App 与 Web 能力对齐。

**非目标(本批不做):**

- 第三层及更深嵌套(回复的回复一律挂在同一楼层,用「回复 @某人」区分);
- 手动 `@` 选人(不弹候选列表、不支持 @ 多人);
- 评论点赞、评论举报(现有举报只针对动态)、评论编辑;
- 评论推送(只走 IM 灰条,不接极光);
- 通知中心 / 站内消息列表(点击灰条进会话,不新建收件箱);
- 楼中楼排序切换(热门/最新)、评论折叠阈值可配置。

## 2. 已定关键决策(用户确认)

| 决策点 | 结论 | 落选理由 |
|---|---|---|
| 层级 | **两级**:顶级评论 + 回复;回复的回复归到同一楼层 | 无限嵌套在移动端读不动,分页与缩进都失控 |
| @ 触发方式 | **回复即 @**:点某条评论的「回复」,发布后提醒被回复者 | 手动 @ 选人要做候选接口与弹层,本批价值低于成本 |
| 提醒通道 | **只走 IM 灰条**(复用现有评论通知通道) | 推送的 `system` 类已用于举报/封禁,混入评论会提高打扰 |
| 删除 | **作者可删自己的评论**:删顶级 = 整楼(二次确认);删回复 = 只删自己那条 | 发错的回复撤不回,楼中楼体验不完整 |
| 回复加载 | **顶层分页 + 每条内嵌前 2 条 + 「查看全部 N 条回复」走独立接口** | 一次返回全部回复会让火爆动态首屏变慢 |
| 落库方案 | **自引用 `parent` + `reply_to`**,服务端归一化到两级 | 独立回复表要两套序列化/聚合/级联;材料化路径属过度设计 |
| 正文前缀 | 「回复 @昵称」**渲染出来**,不写进 `text` | 写进正文会被用户删改,字数也被前缀占掉 |
| 交付范围 | **App + Web 双端** | 项目惯例:同一套接口、两端能力对齐 |

## 3. 后端设计

### 3.1 模型改动(`feed/models.py`)

`PostComment` 新增两列,一次迁移:

```python
class PostComment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="post_comments")
    parent = models.ForeignKey("self", null=True, blank=True,
                               on_delete=models.CASCADE, related_name="replies")
    reply_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL,
                                 related_name="comment_replies_received")
    text = models.CharField("内容", max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
```

要点:

- `parent` 可空 = 顶级评论;非空 = 回复,**且一定指向顶级评论**(由服务层保证,
  数据库无法跨行约束);
- `on_delete=CASCADE`:删顶级评论连带删回复;注销作者连带删其评论(与现状一致);
- `reply_to` 用 `SET_NULL`:被回复者注销后评论仍留档,只是不再显示「回复 @某人」;
- **不做 `CheckConstraint(~Q(id=F("parent_id")))`**:MySQL 8 明确拒绝
  「CHECK 约束引用自增列」(`(3818) Check constraint ... cannot refer to an
  auto-increment column`)。自引用在接口层本来就不可能发生(新评论的 id 在插入前不存在),
  两级约束由服务层保证。

### 3.2 归一化规则(唯一一处)

客户端**只需要传被点的那条评论 id**(`parent_id`),服务端在
`feed/services.py::create_comment` 里归一化:

| 客户端传的 `parent_id` | 落库 `parent` | 落库 `reply_to` |
|---|---|---|
| 不传 / `null` | `NULL`(顶级评论) | `NULL` |
| 顶级评论的 id | 该评论 | 该评论作者 |
| 某条回复的 id | 该回复的**顶级评论** | 该**回复**的作者 |

校验(全部在服务层,失败抛 `ValidationError` / 404):

1. `parent.post_id` 必须等于路径里的 `post_id`,否则 404(不暴露别的动态的评论);
2. `parent` 必须对当前用户可见(作者未被双向拉黑 / 未被重封禁),否则 404;
3. `reply_to` 由服务端推导,**不接受客户端传入**,避免伪造提醒对象。

### 3.3 计数口径

`comment_count` 维持「全部评论行」:顶级 + 回复都算(现有
`Count("comments")` 天然正确,不用改)。列表上「评论 12」= 12 条(含回复)。

### 3.4 可见性

- 顶级评论:沿用现有过滤(排除双向拉黑 / 重封禁作者的评论);
- 内嵌 `replies`:用 `Prefetch("replies", queryset=<同一套过滤>)`,保证「前 2 条」
  不会恰好都是被过滤掉的人;
- `GET /replies`:同一套过滤;
- 被过滤的回复仍计入 `reply_count` 吗?**不**:`reply_count` 与内嵌/展开口径一致,
  按可见性过滤后计数,避免「显示 5 条回复但只展开出 3 条」。

### 3.5 迁移

新增 `feed/migrations/0002_postcomment_parent_reply_to.py`(以实际最新编号为准),
只加两列,无数据迁移。

## 4. 接口设计(36 → 38 个;P1-4 合入 master 后为 42)

### 4.1 评论对象(新结构)

```json
{
  "id": 12,
  "author": {"user_id": 12, "nickname": "小雨12", "avatar_url": "..."},
  "text": "同问,我也想知道",
  "parent_id": 9,
  "reply_to": {"user_id": 7, "nickname": "阿哲"},
  "reply_count": 3,
  "replies": [ ...前 2 条,结构同本对象但 replies 为空、reply_count 为 0... ],
  "created_at": "2026-10-20T10:00:00+08:00"
}
```

- 顶级评论:`parent_id = null`、`reply_to = null`、`replies` = 前 2 条回复;
- 回复:`parent_id` = 顶级评论 id、`reply_to` = 被回复者、`replies = []`、
  `reply_count = 0`(不递归,避免无限嵌套);
- `reply_to` 里只给 `user_id` / `nickname`(不给头像,前端渲染文案够用);
- 被回复者已注销时 `reply_to = null`。

### 4.2 `GET /api/v1/posts/{post_id}/comments`

只返回**顶级评论**(`parent__isnull=True`),分页不变(默认 20、上限 100),
按时间正序;每条带 `reply_count` 与内嵌 `replies`(前 2 条,正序)。
动态不可见 → 404(不变)。

### 4.3 `GET /api/v1/posts/{post_id}/comments/{comment_id}/replies`(新增)

- 返回某条**顶级评论**的全部回复,分页,按时间正序;
- `comment_id` 不存在 / 不属于该动态 / 本身是回复 → 404;
- 可见性过滤同 §3.4;
- 动态不可见 → 404。

### 4.4 `POST /api/v1/posts/{post_id}/comments`

body 新增可选 `parent_id`(Integer)。响应 201 + 评论对象(§4.1);
`parent_id` 不存在 → 404;`parent_id` 属于别的动态 → 404;
违禁词 / 空内容 / 超 200 字 → 400(不变)。限流不变(60 次/天,回复同额度)。

### 4.5 `DELETE /api/v1/posts/{post_id}/comments/{comment_id}`(新增)

- 只有**作者本人**能删;非作者 / 评论不存在 / 不属于该动态 → 一律 404(不暴露存在性);
- 删顶级评论:`CASCADE` 连带删全部回复,成功 204;
- 删回复:只删这一条,成功 204;
- 重复删除返回 404:本接口**不做幂等**(与 `DELETE /posts/{id}` 的「非作者 / 不存在一律 404」一致);
- 不需要关闭任何举报(评论不可被举报)。

### 4.6 路由(`feed/urls.py`)

```python
path("posts/<int:post_id>/comments", views.post_comments),
path("posts/<int:post_id>/comments/<int:comment_id>/replies", views.post_comment_replies),
path("posts/<int:post_id>/comments/<int:comment_id>", views.post_comment_detail),
```

## 5. 提醒(IM 灰条)

### 5.1 分流规则

| 场景 | 收件人 | 任务 | 文案 |
|---|---|---|---|
| 顶级评论 | 动态作者 | `post_commented`(现状) | `X 评论了你的动态:<前 50 字>` |
| 回复顶级评论 | 该评论作者(= 楼主) | `post_replied`(新增) | `X 回复了你:<前 50 字>` |
| 回复某条回复 | 被回复的那条回复的作者 | `post_replied` | 同上 |
| 自己回复自己(含自己评自己的动态) | 不发 | — | — |

服务层入口改名 `notify_comment_created(comment)`(原 `notify_post_commented`),
在 `transaction.on_commit` 里按 `comment.parent_id` 分流入队。

### 5.2 IM 侧

- `im/client.py` 新增 `send_post_replied(to_identifier, replier_nickname, snippet)`,
  与 `send_post_commented` 同构(自定义消息 `system_notice`,沿用现有模板与跳转);
- `im/tasks.py` 新增 `post_replied(comment_id)`:任务内查库取 `reply_to` 与作者昵称,
  收件人已注销 / 内容缺失时静默返回;
- 被重封禁用户不做额外拦截(其 IM 会话本就受限,与现状一致)。

### 5.3 失败语义

IM 客户端对外永不抛异常;任务失败走既有 `RETRY_POLICY`。
灰条失败**不影响**评论创建成功(评论已落库,提醒是副作用)。

## 6. App(`app/lib/features/square/`)

### 6.1 模型与仓库

- `models.dart`:`PostCommentItem` 增 `parentId`、`replyTo`(`FeedAuthor?`)、
  `replyCount`、`replies`;`FeedAuthor` 已够用;
- `feed_repository.dart`:`addComment(postId, text, {int? parentId})`;
  新增 `fetchReplies(postId, commentId, {limit, offset})`;新增 `deleteComment(postId, commentId)`;
- `post_detail_controller.dart`:`commentsProvider` 仍是顶层列表;
  新增 `repliesProvider`(按评论 id 家族)或在控制器里维护「已展开楼层」的回复缓存。

### 6.2 详情页楼层

`post_detail_page.dart` 的评论区改为:

- 顶级评论行:28 圆头像 + 昵称 + 正文 + 时间 + 行尾「回复」「删除」(自己的才有删除);
- 缩进一级的回复行:24 圆头像 + 昵称 + `回复 @某人`(text3)+ 正文 + 时间 + 「回复」「删除」;
- 回复数 > 2 时显示「查看全部 N 条回复」(文字按钮),点击原地展开并分页续拉;
- 空态不变(「还没有评论 / 来抢沙发」)。

### 6.3 回复态输入栏

- 点「回复」→ 输入栏上方出现 chip「回复 @昵称 ×」(可取消),hint 变「回复 @昵称…」;
- 发送时带 `parentId`;成功后清空输入与回复态,并刷新评论列表与评论数;
- 正文只存用户输入,`回复 @昵称` 由 `reply_to` 渲染。

### 6.4 删除

- 自己的评论/回复行尾显示「删除」,走 `AppDialog` 二次确认;
- 删顶级评论的文案:「连同 N 条回复一起删除?删除后不可恢复」;
- 成功后刷新评论列表与评论数。

### 6.5 动效与 Hero

- 展开/收起用 `AnimatedSize`(微交互档),尊重 reduced-motion;
- 回复头像沿用 `avatar-comment-{id}` 作为 Hero tag(id 全局唯一,不会撞);
- 不新增裸色值/裸字号,全部走「心跳」token。

## 7. Web(`web/src/`)

### 7.1 类型与 API

- `api/types.ts`:`Comment` 增 `parent_id`、`reply_to`、`reply_count`、`replies`;
- `api/feed.ts`:`createComment(postId, text, parentId?)`、
  `fetchReplies(postId, commentId, limit?, offset?)`、`deleteComment(postId, commentId)`。

### 7.2 `CommentList.vue`

- 两层渲染:顶层列表 + 每条下方回复块(24 头像、昵称、`回复 @某人`、正文、时间);
- 回复数 > 2 显示「查看全部 N 条回复」,点击展开并分页;
- 每条评论有「回复」;底部表单进入回复态(标题条「回复 @昵称」+ 取消);
- 自己的评论显示「删除」,沿用 `window.confirm`(与删动态、拉黑一致);
- 删除顶级评论后按 `1 + reply_count` 扣减评论数。

### 7.3 `PostDetailPage.vue`

- 新增评论/回复 +1;删除后按规则扣减;
- 404 仍是致命错误(不提供重试),其余错误可重试(现状不变)。

## 8. 测试与门禁

### 8.1 后端(`feed/tests.py`)

- 归一化:回复顶级 / 回复某条回复 / 跨动态 404 / `parent_id` 不存在 404;
- 列表:只返回顶级、`reply_count` 正确、内嵌 `replies` 前 2 条且正序;
- `/replies`:分页、正序、404 规则(评论属于别的动态 / 评论本身是回复);
- 删除:非作者 404、删顶级级联、删回复只删一条、`comment_count` 相应变化;
- 可见性:被拉黑 / 重封禁作者的回复不出现在内嵌与 `/replies`;
- 提醒:顶级 → `post_commented`、回复 → `post_replied`、自回自不入队
  (沿用 `im.tasks.*.delay` mock);
- 限流:回复与顶级共用 `post_comment` 额度(单测 `allow_request` 已覆盖,补一条回复用例)。

### 8.2 App

- 楼层渲染(顶级 + 回复 + 「回复 @某人」文案);
- 展开「查看全部 N 条回复」并续拉;
- 回复态:点「回复」出现 chip、发送带 `parentId`、成功后清空;
- 删除:自己的才有入口、二次确认、删顶级文案含回复数;
- Hero tag 不与楼层冲突。

### 8.3 Web

- `CommentList` 组件测试:两层渲染、展开、回复态、删除回调、取消回复;
- `PostDetailPage` 计数增减(含删顶级按 `1 + reply_count`);
- 覆盖率门槛维持 70/60/70/70。

### 8.4 文档

- `docs/api/feed.md`:5.8 / 5.9 补字段与 `parent_id`,新增 5.11 回复列表、5.12 删除评论;
- 接口总数 **36 → 38**(本分支基线;P1-4 合入 master 后为 42),
  `ApiDocsCoverageTests` 双向比对必须绿;
- 所有新增/修改的 `.py` 补 docstring(`CommentCoverageTests` 门禁);
- 收尾回填 `CLAUDE.md` 里程碑表与「下一步」、`README.md` 功能清单。

## 9. 风险与取舍

| 风险 | 处理 |
|---|---|
| 内嵌回复导致 N+1 | 顶层查询 `Prefetch` 带过滤,序列化只读 `to_attr`,不逐条查库 |
| 旧客户端(不认新字段) | 只显示顶级评论、看不到回复,但不会崩;新字段对旧端是无害的多余字段 |
| 删顶级评论时回复数已变 | 删除用 `CASCADE` 一条 SQL,计数由 `Count("comments")` 重新聚合,无脏值 |
| 回复正文与「回复 @」重复 | 前缀只在渲染层拼,正文不落前缀,不会出现「回复 @A 回复 @B」 |
| 被拉黑者的楼内回复 | 与顶层同一套过滤;`reply_count` 同步按可见口径计数 |
| 归一化写错层级 | 只在 `create_comment` 一处实现,单测覆盖三种输入,别处不许拼 `parent` |

## 10. 验收清单(手测)

1. 双模拟器:A 发动态,B 评论 → A 收灰条;A 回复 B 的评论 → B 收「回复了你」灰条;
2. 对回复再回复 → 仍挂在同一楼层,`回复 @` 指向正确的人,楼层只增一条;
3. 展开「查看全部 N 条回复」→ 分页续拉正确,顺序与时间一致;
4. 删除自己的顶级评论 → 整楼消失,评论数按 1 + 回复数扣减;
5. 删除自己的回复 → 只少一条;
6. 拉黑 B 后刷新 → B 的评论与回复都不再出现,`reply_count` 同步变小;
7. Web 重复 1–6,布局与 App 语义一致。
