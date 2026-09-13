# 广场动态作者入口 + 在线绿点设计

日期:2026-09-13
状态:已与用户逐项确认(见 §6 决策记录),待用户终审
上游:广场页(动态流,`specs/2026-09-12-square-feed-design.md`);在线状态(`specs/2026-09-13-online-presence-design.md`,复用其接口/前端模块);公开资料卡(`GET /users/{id}` + App 路由 `/users/:id`)
背景:用户在广场手测时提出两个缺口 —— (1) 点击动态作者头像没有反应(期望打开用户资料页);(2) 广场缺少在线状态标识。探索结论:两者都是当时做广场时未接线的入口,后端接口与前端组件均已就绪;本设计 = 纯前端接线 + 一处共享控制器的健壮性修复。

## 1. 目标与范围

1. **点击入口**(广场列表 + 动态详情页):
   - 动态卡片:头像、昵称均可点 → `context.push('/users/{author.user_id}')` 打开公开资料页;卡片其余区域行为不变(列表页 = 进动态详情,详情页 = 无操作)。
   - 动态详情页评论区:每条评论的头像、昵称可点 → 同上。
   - **自己**(自己发的动态、自己的评论):头像/昵称不可点(无响应)。原因:公开资料页右上角有「举报/拉黑」菜单,本人视角语义错误;跳底部「我的」tab 需把 tab 状态重构为全局可控,不做。
2. **在线绿点**(样式与消息列表一致):
   - 动态卡片作者头像右下角,复用 `OnlineDot`(白描边绿点),仅 `online == true` 时渲染;离线不显示任何标识。
   - 评论区**不带**绿点(信息流密度考量,用户确认)。
3. **数据来源**:复用 `features/presence` 共享控制器(`track()` 登记 + 45 秒周期刷新 + 多页面合并去重),后端 `GET /api/v1/presence` 零改动。

**非目标(YAGNI)**:评论区绿点;公开资料页内展示在线状态;点自己头像跳「我的」tab;作者点击的埋点/统计;后端任何改动。

## 2. 交互与展示细节

| 位置 | 点击目标 | 行为 |
|---|---|---|
| 广场列表卡片 | 头像 / 昵称 | push `/users/{id}`;自己的动态 → 无响应 |
| 广场列表卡片 | 其余区域 | 进动态详情(现状不变) |
| 动态详情页顶部卡片 | 头像 / 昵称 | push `/users/{id}`;自己的动态 → 无响应 |
| 动态详情页评论区 | 每条评论头像 / 昵称 | push `/users/{id}`;自己的评论 → 无响应 |

绿点小样(40px 方头像,与消息列表同款构图):

```
╭────────╮
│  头像  │●     昵称(加粗)
╰────────╯    3 小时前
```

- 绿点直径 11px(40 × 0.28,消息列表同款比例),白描边 2px;允许溢出头像边界(Stack `clipBehavior: Clip.none`)。
- 可点区域 = 头像整体(含绿点)+ 昵称文字本身;**昵称的可点区域要收紧到文字**(`Align` 包裹,避免 `Expanded` 撑满后右侧空白也可点)。
- 嵌套手势:内层点击不触发外层卡片点击(进详情)——Flutter 手势竞技场中内层识别器胜出,无需额外代码,但测试要覆盖回归。

## 3. 前端设计

**`features/square/widgets/post_card.dart`**:
- 新增参数:`bool online = false`、`VoidCallback? onTapAuthor`(null = 不可点,页面据此传「自己」的情况)。
- `_Avatar` 增加 `online` 参数:在线时 `Stack(clipBehavior: Clip.none)` 在右下角叠 `OnlineDot`(沿用 `chats_page.dart::_Avatar` 同款写法)。
- 头像(连同绿点)与昵称分别包 `GestureDetector`,统一回调 `onTapAuthor`;测试 keys:`post.avatar.{postId}` / `post.nickname.{postId}`。
- PostCard 保持哑组件(不 watch provider),数据由页面传入 —— 与发现卡/消息列表现行模式一致。

**`features/square/square_page.dart`**:
- build 里 `final presenceById = ref.watch(presenceProvider);`;`data:` 分支 `track('square', [for (final p in items) p.author.userId])`(控制器内部去重)。
- 逐卡传 `online: presenceById[post.author.userId]?.online == true`;`onTapAuthor: post.author.userId == myId ? null : () => context.push('/users/${post.author.userId}')`(`myId` 已由现有 `profileProvider` 提供)。

**`features/square/post_detail_page.dart`**:
- build 里同样 watch `presenceProvider`;`data:` 分支 `track('post:${widget.postId}', [data.author.userId])`。
- 顶部 PostCard 同列表页传参。
- `_CommentTile` 增加 `onTapAuthor` 参数(页面按 `comment.author.userId == myId` 传 null 或跳转回调);头像/昵称包点击,keys:`post.comment.avatar.{commentId}` / `post.comment.nickname.{commentId}`。

**`features/presence/presence_controller.dart`(健壮性修复,方案 1)**:
- 现状:所有登记 id 合并成**一次**请求,而接口单次上限 100,超过 → 400 → 整轮刷新失败(会把消息列表/发现页的绿点一并打没)。
- 广场是第一个随翻页无限增长的登记源,故在 `refresh()` 内**按 100 分片顺序请求、合并结果后一次写 state**;id 数 ≤100 时与现状完全一致(常规路径不增加请求)。
- 任一片失败 → 整轮放弃、保留旧值(与现状语义一致),下个周期重试;不引入半更新状态。

**错误处理**:无新增失败面 —— 点头像/昵称是本地路由跳转;资料页 404(拉黑/重封禁)按现有「加载失败 + 重试」展示;presence 拉取失败保留旧值、不打扰用户(现状)。

## 4. 测试与验证

**Flutter(预计 +7~9 用例,基线 189 全绿,analyze 零告警)**:
- `presence_controller_test`:登记 >100 个 id → 拆成 2 个请求(断言请求次数与 query 分批),合并结果;某片失败 → 保留旧值。
- `square_page_test`:点头像 → 进资料页;点昵称 → 进资料页;自己的动态头像点击无导航;点卡片其余区域仍进动态详情(回归);在线 → `find.byType(OnlineDot)` 命中、离线不渲染;`/presence` 假响应按 harness `"METHOD path"` 铺法。
- `post_detail_page_test`:评论者头像/昵称 → 进资料页;自己的评论无导航;顶部卡片作者绿点。
- 现有广场用例补铺 `/presence` 响应(不铺则静默 404,断言仍绿但噪音大、掩盖回归)。

**手测(双模拟器)**:
1. 广场列表点他人头像/昵称 → 资料页;点自己头像 → 无反应;点卡片正文区 → 动态详情(回归)。
2. 另一端在线(开着 App) → 作者头像绿点;另一端杀 App ≤2 分钟 → 绿点消失。
3. 动态详情页作者区同列表页;评论区点评论者 → 资料页。

**后端**:零改动,不新增用例(全量 327 回归)。

## 5. 改动面

| 端 | 文件 | 动作 |
|---|---|---|
| 前端 | `features/square/widgets/post_card.dart` | 头像/昵称点击 + `online` 绿点 + 新参数 |
| 前端 | `features/square/square_page.dart` | track + 传参 + 跳转回调 |
| 前端 | `features/square/post_detail_page.dart` | track + 顶部卡片传参 + 评论行点击 |
| 前端 | `features/presence/presence_controller.dart` | 100 个/片批量请求 |
| 前端 | `test/features/square/*`、`test/features/presence/*` | 新增/补充用例 |
| 文档 | `CLAUDE.md` | 交付后补广场/在线状态章节(惯例) |

## 6. 关键决策记录

- 范围:广场列表 + 动态详情页(含评论作者可点)(用户选 B)。
- 展示样式:头像右下角绿点、仅在线时显示(用户选 A;否决昵称旁文字、两者都要)。
- 自己头像:无响应(用户选 A;否决进资料页、跳「我的」tab)。
- 评论区绿点:不做(用户确认)。
- 100 上限处理:PresenceController 内部分片(用户选方案 1;否决调用方封顶)。
- 视觉沟通:沿用文字 + ASCII 小样,不开浏览器伴生页(与既往偏好一致)。
