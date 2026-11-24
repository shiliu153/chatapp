# E-5.5 页面规格：回声（广场）—— 动态流与详情

> **立项**：2026-11-24 · **状态**：page spec，**已确认**（2026-11-24 主人拍板，结论见 §7）
> **上游**：[Ember 规范](../specs/2026-11-23-ui-redesign-ember-design.md)（v1.0）§5 / §6 / §7 / §8.2 / §8.3 / §9.3 / §9.4
> **实施计划**：[E-5 逐页迁移](../plans/2026-11-23-ui-redesign-ember.md) 第 5 单（App 线）
> **模板**：[E-5.3 对话页](2026-11-24-e5-3-chat-page-spec.md) / [E-5.4 我的+资料页](2026-11-24-e5-4-profile-page-spec.md)
> **栈**：`app`

---

## 1. 目标

把「回声」tab（广场动态流）与动态详情页从心跳口径迁到 Ember。业务逻辑零改动：
`square_controller` / `post_detail_controller` / `feed_repository` 一行不动。

用户可见的变化：

| # | 变化 | 从 → 到 |
|---|---|---|
| 1 | **动态卡** | `EmberCard`：`surface.card` + `radius.lg` + `elev.1`，内边距 20；深色 `border.divider` 1px 无阴影 |
| 2 | **作者行** | `EmberAvatar` 40 + 昵称 `subtitle` 17/w600 + 时间 `caption` 13 `text.tertiary` |
| 3 | **正文** | `body` 15 / 行高 1.55（§18.4） |
| 4 | **图片** | `radius.sm` 12、最多 9 宫格（保留现有网格规则），失败占位 `surface.sunken` |
| 5 | **点赞 / 评论钮** | 图标换 Phosphor（`heart` / `chat-circle`）；已赞 = **Fill + `brand.default`**，未赞 = Regular + `text.tertiary` |
| 6 | **点赞动效** | 保留心形弹跳（`spring.fast`），reduced-motion 下只换色不缩放 |
| 7 | **详情页顶栏** | §9.4 shell **52**（返回 22 + 标题 17/w600 居中） |
| 8 | **评论** | 楼中楼：`surface.sunken` 底 + `radius.md`；作者名 `caption` 13/w600 `text.primary`，内容 `body` 15 |
| 9 | **Hero 转场** | 动态卡图片 → 详情页图片（沉浸内容，§9.3） |
| 10 | **发帖入口** | 顶栏右侧 Phosphor `plus`（`brand.default`），热区 ≥48×48 |

**明确不在本单**：

- 发帖页（`post_compose_page.dart`）、收藏页、我的动态、点赞列表页 —— 属 **E-5.6 二级页**；
- 评论输入栏的富交互（只换皮）；
- 后端 / 接口零改动；Web 侧广场（属 W-5.3）。

## 2. 层级形态（§9.3 / §9.4）

- **回声**是 tab 根页面（底栏常驻）。
- **动态详情**是二级页：全屏 push，顶栏 §9.4 shell；照片走 Hero。
- 评论输入：键盘上方内联输入条（不用 sheet —— 它是持续动作，不是单次选择）。
- 删除 / 举报：Dialog（带图标 + 明确动词）。

## 3. 用的组件（§8）

| 元素 | 用什么 | 取值来源 |
|---|---|---|
| 顶栏（tab 内） | 标题「回声」`display` 32 Fraunces + 右侧发帖 `plus` | §8.3 标题档 |
| 动态卡 | `EmberCard`（内边距 20、`radius.lg`、`elev.1`） | §8.2 卡片 |
| 作者行 | `EmberAvatar` 40 + 昵称 + 时间 | §8.2 头像 |
| 正文 | `Text` 走 `fontSizeBody` 15 / 行高 1.55 | §18.4 |
| 图片网格 | 自绘 `Wrap`/`GridView`，`radius.sm` 12，间距 4 | §5.1 / §5.2 |
| 标签 | `EmberChip`（只读态） | §8.3 Chip |
| 点赞 / 评论钮 | `EmberPressable` + Phosphor 图标 20 + `caption` 13 计数；热区 48 | §6 / §8.4 |
| 详情页顶栏 | §9.4 shell 52 | §9.4 |
| 评论项 | `surface.sunken` + `radius.md`；楼中楼缩进 16 | §8.2 次级容器 |
| 评论输入条 | `EmberField` + 发送 `EmberButton`（文字按钮） | §8.2 |
| 空态 / 错误态 | `EmberEmpty` + unDraw 图（同 E-5.2 口径） | §8.2 空态 |
| 骨架 | `EmberSkeleton`（卡形 + 头像圆 + 两行文字） | §8.2 骨架 |
| Toast | `EmberToast` | §8.3 Toast |

**不新增 token、不新增 `core/ui` 组件**。

## 4. 状态清单

| 元素 | 状态 | 口径 |
|---|---|---|
| 动态卡 | default / pressed | 整卡可点进详情；pressed `scale .98`（§8.2 卡片） |
| 动态卡 | loading | `EmberSkeleton`（头像圆 + 两行 + 图片块） |
| 点赞钮 | 未赞 / 已赞 | 未赞 Regular `text.tertiary`；已赞 Fill `brand.default` + 计数 +1 |
| 点赞钮 | pressed | `scale .97`（`spring.fast`）+ 心形弹跳 |
| 评论钮 | default | Regular `text.tertiary` + 计数；点进详情并聚焦输入 |
| 图片 | 单图 / 多图 / 失败 | 单图按比例、多图 9 宫格；失败 `surface.sunken` + Phosphor `image` |
| 评论项 | default / 自己的 | 自己的评论右侧「删除」文字按钮（`text.tertiary`） |
| 评论输入 | default / focus / sending | `EmberField` 口径；sending 时发送钮转圈 |
| 深色 | — | 无阴影，卡片 `border.divider` + `surface.card` |
| 字号缩放 | 0.85–1.3 | 支持；`micro` 不跟随 |
| reduced motion | — | spring → 120ms 淡入；点赞只换色不缩放；Hero 退化为淡入 |
| 封禁 | `banned_heavy` | 路由层 BannedPage，本单不改 |

## 5. 空态与错误态

| 场景 | 形态 |
|---|---|
| 动态流空 | `EmberEmpty`：unDraw 图 + 「还没有人留下回声」+ 说明 + 主按钮「发第一条」 |
| 动态流加载中 | `EmberSkeleton` × 3 张卡 |
| 动态流失败 | `EmberEmpty` 错误形态 + 「重试」 |
| 详情加载失败 | `EmberEmpty` 错误形态 + 「重试」 |
| 详情已删除 | `EmberEmpty` + 「这条动态已被删除」+ 返回 |
| 评论为空 | 居中提示「还没有评论，来说点什么」`caption` `text.tertiary` |
| 评论发送失败 | 输入条下方 `status.danger` 提示 + 保留草稿（**不静默丢弃**） |

## 6. 本单验收

1. `cd app && flutter analyze` 零告警；`flutter test` 全绿；`bash scripts/verify.sh app` 全绿（末尾输出贴进 PR）。
2. **golden**：动态卡 × {明, 暗} × {单图, 多图} = 4；点赞钮 × {明, 暗} × {未赞, 已赞} = 4；
   评论项 × {明, 暗} = 2；空态 × {明, 暗} = 2。合计 **12 张**。
3. **Semantics**：动态卡读「作者，正文摘要，N 赞，M 评论」；点赞钮读「赞，已赞/未赞」；
   评论项读「作者，内容，时间」。
4. **手测（必须做）**：`emulator-5554` —— 刷动态流、点赞/取消、进详情、发评论、删自己的评论、
   Hero 转场（图 → 详情）、深色、系统「移除动画」、字号 1.3。
5. **三条 grep 为空**：`0xFF` / `Curves.` / `Icons.`（范围 `app/lib/features/square`）。
6. **PR 开成 draft**，正文写「等待模拟器验收」。

## 7. 评审问题与拍板结果

| # | 问题 | 我的建议 | 备选 / 影响 |
|---|---|---|---|
| 1 | 发帖页 / 收藏 / 我的动态 / 点赞列表留 E-5.6？ | **留在 E-5.6**（本单只做流 + 详情） | 并进来会让本单跨到表单与图片选择 |
| 2 | 点赞心形弹跳保留？ | **保留**（`spring.fast`，属于微交互不是装饰循环动画） | 去掉会失去「回声」的手感 |
| 3 | 详情页图片 Hero 本单做？ | **本单做**（沉浸内容，§9.3 明确） | 推后则详情页仍是硬切 |
| 4 | 评论楼中楼层级保留（二级回复）？ | **保留**（只换皮，缩进 16） | 删掉会丢功能 |
| 5 | 广场顶栏是否保留「发帖」入口在顶栏（而非 FAB）？ | **顶栏 plus**（与 §9.4 一致，且 App 已有 FAB 的页面不多） | FAB 需要额外处理底栏遮挡 |

**拍板后**：结论回填本节下方，再开工单。

### 拍板结果（2026-11-24 主人确认）

| # | 结论 |
|---|---|
| 1 | 发帖页 / 收藏 / 我的动态 / 点赞列表 **留在 E-5.6** |
| 2 | 点赞心形弹跳 **保留**（`spring.fast`；reduced-motion 只换色不缩放） |
| 3 | 详情页图片 **Hero 本单做** |
| 4 | 评论楼中楼 **保留**（只换皮，缩进 16） |
| 5 | 发帖入口 **顶栏右侧 `plus`**（不用 FAB） |

## 8. 与后续页单的接口

- **E-5.6**：发帖页、收藏、我的动态、点赞列表沿用本单的卡片与图片网格口径。
- **E-5.4**：动态作者头像点击进资料页（Hero 已在 E-5.4 落地）。
