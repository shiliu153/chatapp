# P12 · 广场 feed（约 387 行）

> 上一批：[P11 合规与封禁两级](P11-合规与封禁两级.md) · 下一批：[P13 运维台 ops](P13-运维台ops.md)
> 预计 2.5 小时 · 本批是全书**查询优化最密集**的地方：一次查询里同时算点赞数、评论数、"我是否已赞"

---

## §1 本批目标

1. 说出 `visible_posts` 的三条可见性规则与三个注解（`like_count` / `comment_count` / `liked_by_me`）；
2. 解释什么是 N+1，以及本项目用了哪三种手段规避；
3. 说出发布动态的四层校验（内容非空 / 数量 / 大小 / 真是图片）；
4. 说出"删除动态"为什么要先关闭待处理举报。

---

## §2 读前必建概念

### 1）N+1 问题

假设要列 20 条动态，每条都要显示作者昵称与头像：
- 1 次查询取 20 条动态
- 每条再查一次作者（20 次）、再查一次头像（20 次）……

总计 1+N 次（甚至更多）。**表现是"数据量一大就变慢"，而不是"出错"**，所以最容易被忽略。

### 2）三种武器

| 手段 | 解决什么 | 本项目例子 |
|---|---|---|
| `select_related` | 多对一/一对一 → **一次 JOIN 取回** | `.select_related("author__profile")` |
| `prefetch_related` | 一对多/多对多 → **额外一条 IN 查询再拼接** | `.prefetch_related("author__photos", "images")` |
| `annotate` + `Count`/`Exists` | **把统计下推到数据库**，不要 Python 里循环 | `like_count=Count("likes", distinct=True)`、`liked_by_me=Exists(...)` |

### 3）`distinct=True` 为什么必须加

当一条 SQL 同时 JOIN 多张"一对多"表（likes、comments）时，行数会**相乘**，`Count` 会重复计数。`Count("likes", distinct=True)` 让数据库按主键去重后再数。

### 4）`annotate` 会丢掉 `Meta.ordering`

一旦 `annotate` 引入聚合（`GROUP BY`），Django 会丢弃模型 `Meta.ordering`（因为排序字段可能不在 GROUP BY 里）。所以 `feed/services.py` 第 25–26 行**必须显式 `order_by`**，注释也写明了这一点。

### 5）`SerializerMethodField` 与 `context`

需要"按 request 拼绝对 URL"或"做条件过滤"的字段，用 `SerializerMethodField` 手写；它通过 `self.context["request"]` 拿请求。**代价**：这类字段是 Python 里算的，如果内部触发查询就会引入 N+1——所以必须配合 `prefetch_related`（下面第 3 点会看到）。

---

## §3 精读清单

### 1. `feed/models.py`（83 行）——四张表

| 行 | 内容 | 要抓的点 |
|---|---|---|
| 7–17 | `Post` | 第 10 行 `text = TextField(max_length=500, blank=True)`：**允许只有图片没有文字**；14 行 `ordering = ["-created_at", "-id"]`（**加 `-id` 是为了同一秒内也有稳定顺序**，分页不漏不重） |
| 20–29 | `PostImage` | `upload_to="posts/%Y/%m/"`；`order` 保证排序（与 P06 的 `Photo` 同一套做法） |
| 32–44 | `PostLike` | `UniqueConstraint(["post","user"])` → 一人一赞；`related_name="post_likes"` |
| 47–58 | `PostComment` | 按 `created_at, id` 升序（评论是时间正序，与动态列表相反） |
| 61–83 | `PostReport` | **第 62 行 docstring**："post 用 `SET_NULL`：动态删除后举报行留档（运营对账）"——这是与 `Report`（P11）的关键差别：动态没了，举报记录还要在 |

### 2. `feed/services.py`（53 行）——**可见性与注解**

| 行 | 在干什么 | 要抓的点 |
|---|---|---|
| 13–26 | `visible_posts(viewer)` | ①排除双向拉黑（`blocked_user_ids`，P11）②排除 `BANNED_HEAVY` 的作者 ③`select_related("author__profile")` ④`prefetch_related("author__photos","images")` ⑤**三个注解**：`Count("likes", distinct=True)`、`Count("comments", distinct=True)`、`Exists(PostLike...user=viewer)` |
| 25–26 | 注释 + 显式 `order_by` | 见 §2 第 4 点 |
| 29–43 | `delete_post(post)` | **第 34–40 行**：先把该动态全部**待处理**举报标成 `handled`、写 `handled_note="动态已删除"`、补 `handled_at`，并调 `notify_report_handled`（docstring：否则作者自删后举报会在 ops 队列里悬空）；**第 41–42 行**：连磁盘图片一起删（`file.delete(save=False)`）；第 43 行删动态。**作者自删与运营删除共用这一个函数** |
| 46–52 | `notify_post_commented(comment)` | **自己评自己不打扰**（第 51–52 行）+ `on_commit(robust=True)` 入队 |

### 3. `feed/serializers.py`（88 行）

| 行 | 内容 | 要抓的点 |
|---|---|---|
| 10–18 | `author_brief(user, request)` | 普通函数（不是 serializer）：返回 `{user_id, nickname, avatar_url}`；**第 13–16 行遍历 `user.photos.all()` 找第一张过审**——这里**依赖 `prefetch_related`**，否则每条动态都会多一次查询 |
| 21–38 | `PostSerializer` | `author`/`images` 用 `SerializerMethodField`；`like_count`/`comment_count`/`liked_by_me` 声明为只读字段（值来自注解，见 below）；`get_images` 拼绝对 URL |
| 24–26 | 那三个字段的 `default=0/False` | **为什么需要默认值**：`post_detail`（单条）与 `_create_post`（刚建完）走的是**没有注解**的查询路径，此时字段不存在，默认值避免报错 |
| 52–71 | `PostCreateSerializer` | 53 行 text 可空；55–58 敏感词；**60–71 对象级校验**：从 `self.context["request"].FILES.getlist("images")` 拿文件 → 文字与图片不能都空 → 最多 9 张 → 单张 ≤5MB → **第 70 行 `image_field.run_validation(file)` 用 ImageField 校验器验证"这真是图片"**（PIL 解析失败即 400） |
| 74–83 | `PostCommentCreateSerializer` | 敏感词 + 去空白后不能为空 |
| 86–88 | `PostReportCreateSerializer` | 复用 `moderation.models` 的 `ReportType`/`ReportStatus`（**跨 app 复用枚举**） |

### 4. `feed/views.py`（113 行）

| 行 | 内容 | 要抓的点 |
|---|---|---|
| 21–25 | `_page_response(...)` 私有助手 | 把"手工分页 + 序列化"抽出来，供 3 个接口复用（P08 的 `match_list` 是同一手法，但这里抽成了函数——**更好的写法**） |
| 28–33 | `posts`（GET 列表 / POST 发布） | 一个视图两个方法，按 `request.method` 分发 |
| 36–45 | `_create_post` | **39–43 行 `with transaction.atomic():`**：动态与图片要么都建、要么都不建；`enumerate(request.FILES.getlist("images"))` 给 `order` 编号；**第 44 行 `post = visible_posts(request.user).get(pk=post.pk)`**——重新按"带注解的查询"取一次，才能返回 `like_count` 等字段（这解释了第 24–26 行的默认值只是兜底） |
| 48–57 | `my_posts` | 与 `visible_posts` 结构相同**但不做可见性过滤**（只看自己的）——重复了一遍注解。**值得思考：这两处能不能合并？**（答案：能，但会让"我的动态包含重封禁者自己"这个语义变隐晦；作者选择了显式重复） |
| 60–67 | `post_detail` | DELETE：`get_object_or_404(Post, pk=..., author=request.user)` → **非作者 404**（不是 403，同 P07 的越权思路）；GET：走 `visible_posts` |
| 70–77 | `post_like` | POST：`get_or_create` → 幂等，`201 if created else 200`；DELETE：直接删（不存在也 204） |
| 80–97 | `post_comments` | POST：建评论 + `notify_post_commented`；GET：排除拉黑者与重封禁作者的评论（92–96 行），并 `select_related`/`prefetch_related` |
| 100–113 | `post_report` | 不能举报自己 → `get_or_create(status=PENDING)` 幂等 → 只返回 `{id, status}` |

### 5. `feed/throttles.py`（38 行）

三个限流器（发布/评论/举报），全部按用户。**注意 `PostCreateThrottle` 与 `PostCommentThrottle` 多了 `allow_request`**（第 12–15、26–29 行）：

```python
def allow_request(self, request, view):
    if request.method != "POST":
        return True
    return super().allow_request(request, view)
```
**为什么需要它？** 因为 `posts` 视图同时处理 GET 与 POST，而 `@throttle_classes` 作用于整个视图。若不拦，**看列表也会消耗发布额度**。这是"视图合并了两种方法"带来的额外成本。

### 6. `feed/urls.py`（12 行）

`posts` / `posts/mine` / `posts/<int:post_id>` / `.../like` / `.../comments` / `.../report`。**顺序论证**（P07 练过）：`posts/mine` 与 `posts/<int:post_id>` 不冲突，因为 `mine` 不是整数。

---

## §4 动手实验

> 前置：`$H` = 你的 access；建议先 `seed_fake_users --count 20` 让广场有内容（P08 实验 1）。

### 实验 1 · 发布动态的四层校验

```powershell
# a) 纯文字
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/posts -Headers $H `
  -ContentType 'application/json' -Body (@{ text = "第一条动态" } | ConvertTo-Json) | ConvertTo-Json -Depth 5
# 预期 201 + {id, author:{...}, images:[], like_count:0, comment_count:0, liked_by_me:false, created_at}
```
```powershell
# b) 啥都不给 → 400 "写点文字或选张图片吧"
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/posts -Headers $H -ContentType 'application/json' -Body '{}'
# c) 敏感词 → 400 "内容包含违规内容,请修改"
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/posts -Headers $H -ContentType 'application/json' -Body (@{ text = "刷单兼职" } | ConvertTo-Json)
# d) 带 10 张图 → 400 "最多 9 张图片"（先造图，见 P07 实验 1）
python -c "from PIL import Image; Image.new('RGB',(40,40),(0,120,255)).save('t.png')"
1..9 | ForEach-Object { $files += "-F", "images=@t.png" }
curl.exe -s -X POST http://127.0.0.1:8000/api/v1/posts -H "Authorization: Bearer $($login.access)" -F "images=@t.png" -F "images=@t.png" -F "images=@t.png" -F "images=@t.png" -F "images=@t.png" -F "images=@t.png" -F "images=@t.png" -F "images=@t.png" -F "images=@t.png" -F "images=@t.png"
# e) 假图片（把 txt 改名成 png）→ 400（PIL 校验挡下）
Set-Content fake.png "not an image"
curl.exe -s -X POST http://127.0.0.1:8000/api/v1/posts -H "Authorization: Bearer $($login.access)" -F "images=@fake.png"
```
> 多图上传的字段名是 **`images`**（复数，可重复），与用户头像的 `file`（单数）不同——`request.FILES.getlist("images")` 第 42 行。

### 实验 2 · 点赞的幂等与计数

```powershell
$pid = (Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/posts?limit=1" -Headers $H).results[0].id
# 连点两次
1..2 | ForEach-Object { curl.exe -i -s -X POST "http://127.0.0.1:8000/api/v1/posts/$pid/like" -H "Authorization: Bearer $($login.access)" | Select-String 'HTTP/' }
# 看计数与"我是否已赞"
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/posts/$pid" -Headers $H | Select-Object id, like_count, liked_by_me
# 取消点赞（可重复）
curl.exe -i -s -X DELETE "http://127.0.0.1:8000/api/v1/posts/$pid/like" -H "Authorization: Bearer $($login.access)" | Select-String 'HTTP/'
```
**预期**：第一次 201、第二次 200（幂等）；`like_count` 为 1（不会变成 2）；`liked_by_me` 为 true。

### 实验 3 · 亲手量一次"注解 + 预取"省了多少查询（**本批最有价值**）

```powershell
python manage.py shell
```
```python
from django.db import connection, reset_queries
from users.models import Profile
from feed.services import visible_posts

# 至少保证有 5 条动态(先跑实验 1)
me = Profile.objects.first().user
from django.conf import settings
settings.DEBUG = True

reset_queries(); list(visible_posts(me)); print("可见性+注解查询数:", len(connection.queries))
for q in connection.queries: print(q["sql"][:110])
```
**观察点**：查询条数是个**很小的常数**（拉黑集合、主查询、预取照片/图片……），**与动态条数无关**。
把它和"朴素写法"对比（**别在生产代码里这么写，只是实验**）：
```python
from feed.models import Post
from feed.serializers import PostSerializer
from rest_framework.test import APIRequestFactory
req = APIRequestFactory().get("/")
reset_queries(); [PostSerializer(p, context={"request": req}).data for p in Post.objects.all()]
print("朴素写法查询数:", len(connection.queries))
```
> 把两个数字记进笔记——**亲身量过一次 N+1，比记住概念有用十倍**。

### 实验 4 · 评论通知（自己评自己不打扰）

```powershell
# 起 worker（P10 实验 1），然后评论自己的动态
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/posts/$pid/comments" -Headers $H -ContentType 'application/json' -Body (@{ text = "自评" } | ConvertTo-Json)
# 预期：worker 里【不会】出现 post_commented 任务（services 第 51-52 行拦掉了）
# 换另一个账号（$B）评论你的动态 → worker 里出现 post_commented 任务
```
读 `im/tasks.py` 第 94–109 行验证任务体的三个细节（延迟导入、自评跳过、昵称降级）。

### 实验 5 · 删除动态会关闭待处理举报

```powershell
# 1) 用 $B 举报你的动态
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/posts/$pid/report" -Headers $B -ContentType 'application/json' -Body (@{ type = "other" } | ConvertTo-Json)
# 2) 你删除这条动态
Invoke-RestMethod -Method Delete -Uri "http://127.0.0.1:8000/api/v1/posts/$pid" -Headers $H
```
```python
# python manage.py shell —— 查举报行是否被关闭
from feed.models import PostReport
list(PostReport.objects.values("id", "status", "handled_note"))
# 预期 status='handled', handled_note='动态已删除'；且 report_handled 通知已入队
```
**再验证留档特性**：`PostReport.post` 是 `SET_NULL`，所以动态删了，举报行仍在（`post_id` 变 None）——这与 `Report`（用户举报）不同。

### 实验 6 · 可见性：拉黑与重封禁

```powershell
# 拉起黑（P11 实验 2 的做法），确认广场里刷不到对方动态
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/posts?limit=20" -Headers $H |
  Select-Object -ExpandProperty results | Select-Object -ExpandProperty author | Select-Object -ExpandProperty user_id -Unique
```
```python
# 把某人设为 banned_heavy，确认其动态从广场消失
from users.models import Profile, ProfileStatus
Profile.objects.filter(user_id=8).update(status=ProfileStatus.BANNED_HEAVY)
```
（记得还原：`Profile.objects.filter(user_id=8).update(status=ProfileStatus.COMPLETE)`。）

### 实验 7 · 读测试

```powershell
python manage.py test feed --noinput
```
重点找：图片数量/大小/真实性的用例、点赞幂等、删除关闭举报、可见性过滤、`my_posts` 与广场的差异。

---

## §5 自查题

**Q1. 什么是 N+1？本项目用了哪三种手段规避？**

**参考答案**：取 N 条主记录后又为每条各查一次关联（1+N 次往返），数据量增大就变慢。本项目：①`select_related`（多对一/一对一 JOIN）②`prefetch_related`（一对多/多对多额外一条 IN 查询）③`annotate` + `Count`/`Exists`（把统计下推到数据库，不在 Python 循环里算）。`feed/services.py` 第 19–24 行三件套齐全。

**Q2. `Count("likes", distinct=True)` 里的 `distinct=True` 能不能省？**

**参考答案**：不能。同时 JOIN `likes` 与 `comments` 两张一对多表会让结果行**笛卡尔式相乘**，不 distinct 会把点赞数与评论数都放大。加 `distinct=True` 让数据库按去重后计数。

**Q3. 为什么 `visible_posts` 里必须显式 `order_by`？**

**参考答案**：`annotate` 引入聚合会让 Django 丢弃模型 `Meta.ordering`（`GROUP BY` 与默认排序冲突）。若不显式排序，分页顺序不稳定（可能重复或漏项）。`services.py` 第 25 行注释写明了这一点。

**Q4. `PostSerializer` 里那三个字段为什么要有 `default=0/False`？**

**参考答案**：`post_detail`（单条 GET）与发布后的回读走的是**没有注解**的查询路径（`Post.objects.get`），此时对象上没有 `like_count` 等属性；给默认值避免序列化报错。注意发布接口第 44 行仍特意用 `visible_posts(...)` 回读一次，所以正常路径拿到的是真实计数。

**Q5. 为什么 `PostCreateThrottle` 要覆写 `allow_request`？**

**参考答案**：`posts` 视图同时服务 GET（看列表）与 POST（发布），而 `@throttle_classes` 对两者都生效。不覆写的话，刷列表会消耗发布额度（20/天），正常浏览几下就被限。覆写后只对 POST 计数。

**Q6. 删除动态为什么要先关闭待处理举报？**

**参考答案**：否则动态被作者删掉后，运营队列里那条举报会**悬空**（点进去发现对象不存在，无法处理也无法关闭）。`delete_post` 先把待处理举报标成 `handled` 并写 `handled_note="动态已删除"`，同时通知举报者（`services.py` 第 34–40 行）。**作者自删与运营删除共用同一函数**，保证两条入口行为一致。

**Q7. `PostReport.post` 为什么用 `SET_NULL` 而不是 `CASCADE`？**

**参考答案**：动态删除后举报记录要**留档对账**（第 62 行 docstring）。`CASCADE` 会把举报一起删掉，运营就失去了"这条动态曾被举报过"的证据。

**Q8. 用户举报（`moderation.Report`）与动态举报（`feed.PostReport`）为什么不合成一张表？**

**参考答案**：被举报对象的生命周期与外键策略不同（用户不会被删就走 `CASCADE`；动态删除后要留档走 `SET_NULL`），且处理入口不同（用户举报会触发封禁流程，动态举报只处理内容）。**同一概念在不同上下文里可以有不同实现**——读代码时要接受这种"看起来重复"的合理性。

---

## §6 卡住时查哪里

| 需要 | 去处 |
|---|---|
| 广场接口契约（分页、字段、四态） | [../../api/feed.md](../../api/feed.md) |
| 广场设计意图 | [../../superpowers/specs/2026-09-12-square-feed-design.md](../../superpowers/specs/2026-09-12-square-feed-design.md) |
| 图片上传相关坑 | [../../pitfalls/frontend.md](../../pitfalls/frontend.md)（前端视角）、[../../pitfalls/backend.md](../../pitfalls/backend.md) |
| ORM 聚合语义 | Django `annotate` / `aggregation` 文档（只查这两处） |

---

## §7 验收

1. 能默写 `visible_posts` 的三条可见性规则与三个注解；
2. 实验 3 亲手量过两种写法的查询数差异，并把数字写进笔记；
3. 实验 5 里确认过"动态删除 → 举报被关闭 + 留档（post_id 变 None）"；
4. 能解释 `PostCreateThrottle.allow_request` 的存在理由；
5. 笔记 `docs/learning/backend-notes/P12-广场feed.md`，勾掉总纲 P12。
