# E-5.2 页面规格：遇见（发现）页 —— 滑卡、操作钮与配对编排

> **立项**：2026-11-24 · **状态**：page spec，**待主人评审**（开放问题见 §7）
> **上游**：[Ember 规范](../specs/2026-11-23-ui-redesign-ember-design.md)（v1.0，2026-11-23 生效）§5 / §6 / §7 / §8.2 / §8.3 / §9.1–§9.3
> **实施计划**：[E-5 逐页迁移](../plans/2026-11-23-ui-redesign-ember.md) 第 2 单
> **模板**：[E-5.1 底栏 shell](2026-11-23-e5-1-shell-nav-page-spec.md)
> **栈**：`app`（单一栈；本单不碰 `web`、不碰 `chatapp/**`）

---

## 1. 目标

把「遇见」页从心跳口径迁到 Ember：**页面骨架 + 卡面 + 操作钮 + 滑卡动效 + 配对编排**。
业务逻辑零改动 —— `discovery_controller` / `swipe_undo_controller` / `like_quota_controller`
的请求与状态机一行不动，本单只换视觉与动效实现。

用户可见的变化（其余都是底座替换）：

| # | 变化 | 从 → 到 |
|---|---|---|
| 1 | **页面标题** | 「发现」→ **「遇见」**（与底栏 tab 一致，§9.1） |
| 2 | **喜欢钮** | 粉橙渐变 + 心跳脉冲（1→1.25→1 循环）→ **朱砂实底 `brand.default` + `brand.on` 图标 + `emberGlow` 光晕**，无循环动画（§7.3） |
| 3 | **滑卡飞出** | 250ms `Curves.easeOut` → **`spring.standard`**（有位移用 spatial，§7.1） |
| 4 | **卡片按压** | 无反馈 → **`scale .98`**（§8.2 卡片 pressed） |
| 5 | **页内边距** | 16 → **20**（§5.2） |
| 6 | **配对编排** | `easeOutCubic` / `easeOutBack` 分段 → **`spring.gentle` 分段 + `emberGlow` 径向扩散**（§7.2 情感时刻） |
| 7 | **图标** | Material `*_rounded` → **Phosphor Regular / Fill**（§6） |
| 8 | **筛选入口** | 自绘胶囊 → **`EmberChip`**（§8.3 Chip 行；本单在 `core/ui` 新增该组件） |

**明确不在本单**：

- 资料页本身（E-5.4）与聊天页（E-5.3）；
- 「喜欢我的人 / 谁看过我 / 谁访问过我」三个二级页的内部视觉（只换入口图标与角标）；
- 每日喜欢额度、撤销窗口、筛选的业务逻辑（只换皮）；
- 后端与接口：**零改动**；
- 空态插画资产化（本单用暖色几何体，unDraw 图留给后续统一换）。

## 2. 层级形态（§9.3）

- 「遇见」是**根页面**，底栏常驻（E-5.1 已交付），本单不改 shell。
- **筛选** → 底部 sheet（≤60% 屏高），用 `EmberSheet`；进入 `spring.gentle`，scrim `surface.scrim`。
- **配对成功** → **全屏编排**（不是页面，§9.2），结束后落「对话」顶部「新配对」区；本单只负责编排本身。
- **卡 → 资料页**：Hero 转场（§7.2）。**本单是否做，见 §7 开放问题 3**。

## 3. 用的组件（§8）

| 元素 | 用什么 | 取值来源 |
|---|---|---|
| 页面标题 | 直接 `Text`，走 `tokens.fontSizeDisplay` 32 / w700 / **Fraunces**（`display` 档） | §8.3 标题档；颜色 `text.primary` |
| 顶部入口（喜欢我 / 看过我） | `EmberPressable` + Phosphor 图标 20 + `caption` 13 + `EmberBadge` | §6 图标、§8.5 角标行；窄屏 <360dp 只留图标，靠 `Semantics(label:)` |
| 筛选 chip | **新增 `EmberChip`**（`core/ui`，§8.3 Chip 行：未选中 `surface.sunken` + `text.secondary`；选中 `brand.default` + `brand.on`） | 本单新增组件，后续页单复用 |
| 今日精选卡 | 自绘迷你卡 + `radius.lg` + `elev.1`（深色 `border.divider`）；标题 `subtitle` 17/w600 + Phosphor `sparkle` | §5.3 / §8.2 卡片 |
| 卡面 | 改造现有 `ProfileCard`：照片全出血 + `overlay.scrim` 底部渐变叠字；圆角 `radius.xl`；内边距 20 | §8.2 卡片；scrim 用 `overlay.scrim` |
| 照片指示点 | 保留现形态（当前张 18×6 胶囊、其余 6×6 圆点，白 + 黑投影兜底可读性） | 照片上的叠层，规范未覆盖 → **假定保留**（评审可改） |
| 操作钮（跳过 / 喜欢） | **新增 `EmberActionButton`**（圆形 56 / 64，`core/ui`；按压 `scale .97` + `spring.fast`） | §7.2 微交互、§8.2 主按钮 |
| 撤销钮 | 改造现有 `UndoButton`：48 圆钮 + 30 秒倒计时环，环色换 `brand.default`（底环 `border.divider`） | 业务窗口提示，形态保留 |
| 空态 / 错误态 | `EmberEmpty`（插画 72–96 用**暖色几何体**，标题 17/w600 + 说明 13 `text.secondary`） | §8.2 空态；**禁止灰色图标占位** |
| 骨架 | `EmberSkeleton` 按卡面形状（圆角 `radius.xl`），`surface.sunken` .5↔1 / 1.2s | §8.2 骨架 |
| 配对编排 | 改造 `MatchOverlay`：`EmberAvatar` 96 + `emberGlow` 扩散 + `EmberButton`（去聊天 / 继续滑卡） | §7.2 情感时刻、§8.2 按钮 |
| Toast | `EmberToast`（额度用完 / 撤销结果 / 错误） | §8.3 Toast |

**不新增 token**：本单所需色 / 圆角 / 间距 / 弹簧全部已在 `design/tokens/*.json`；真缺值时按 §11.1
先改 token（`flow` 栈），不在页面里凑值。

**新增两个组件**（都落在 `core/ui`，属 `app` 栈）：`EmberChip`、`EmberActionButton`。

## 4. 状态清单

| 元素 | 状态 | 口径 |
|---|---|---|
| 卡面 | default | 照片全出血 + 底部 `overlay.scrim` 渐变；昵称/年龄 `title` 24 Fraunces 白字；城市/简介 `caption` 13 白 72%；标签 chip 白 22% 底 + `micro` 11 白字 |
| 卡面 | pressed | `scale .98`（`spring.fast`），阴影不变 |
| 卡面 | 无照片 / 图片失败 | `surface.sunken` 底 + Phosphor `user` 64 `text.tertiary`（**内容占位**，不是空态插画） |
| 卡面 | 在线 | `status.success` 呼吸点 8 + 「在线」`micro` 白字（颜色不是唯一线索，§8.4） |
| 卡面 | 多照片 | 顶部胶囊点 + 左右 56 热区切图（保留现有交互） |
| 喜欢钮 | default | 直径 64，`brand.default` 实底 + `brand.on` 图标 24 + `emberGlow` |
| 喜欢钮 | pressed | `scale .97`（`spring.fast`），光晕降至 50% |
| 喜欢钮 | disabled（额度用完） | `surface.sunken` 底 + `text.tertiary` 图标 + `border.divider` 描边，**无光晕无按压** |
| 喜欢钮 | loading（请求在飞） | 保持底与图标，尾随 16 白色转圈，禁点击 |
| 跳过钮 | default / pressed | 直径 56，`surface.card` + 1px `border.divider` + Phosphor `x` 24 `text.tertiary`；pressed `surface.sunken` + `scale .97` |
| 撤销钮 | countdown / busy / expired | 48 圆钮；倒计时环 `brand.default` 进度 + `border.divider` 底环；`busy` 时禁点；`expired` 置灰收起 |
| 筛选 chip | default / selected | 未选中 `surface.sunken` + `text.secondary`；选中 `brand.default` + `brand.on`；按压 `spring.fast` |
| 顶部入口 | default / pressed / 角标 | 图标 20；角标 0 不渲染、1–99 数字、≥100「99+」；热区 ≥48×48 |
| 今日精选 | default / pressed / 空 | 空数组 / 加载中 / 失败 **整块不渲染**（保持现状，不抢滑卡注意力） |
| 配对编排 | running | 光晕扩散（`emberGlow`）→ 双头像相向碰撞 → 粒子飘散 → 文案按钮；总时长 900–1400ms |
| 配对编排 | skip | 点任意处直达完成帧（保留现有 `_skip`） |
| 配对编排 | reduced motion | `disableAnimations` 为真：**直接呈现完成帧**，不做位移/缩放 |
| 深色 | — | 不用阴影：卡面 `border.divider` 1px + `surface.card`；操作钮同理（§5.3） |
| 字号缩放 | 0.85–1.3 | 支持；`micro` 档（角标 / 标签）**不跟随**（§8.4） |
| 封禁 | `banned_heavy` | 路由层已替换为 `BannedPage`，本单不改 |

## 5. 空态与错误态

| 场景 | 形态 |
|---|---|
| 资料没完善 | `EmberEmpty`：暖色几何体 + 「完善资料后就能开始滑卡」+ 还差字段说明 + 主按钮「去完善」 |
| 卡组空（附近没人） | `EmberEmpty`：暖色几何体 + 「附近暂时没有新的人了」+ 说明 + 主按钮「刷新」；有可撤销记录时，下方追加撤销钮 |
| 加载中 | `EmberSkeleton` 卡面形（圆角 `radius.xl`），不阻塞顶部标题与筛选行 |
| 加载失败 | `EmberEmpty` 错误形态：说明 + 主按钮「重试」（`apiMessageOf`） |
| 今日精选失败 | 整块不渲染（**不展示错误**，它是加餐） |
| 额度用完 | 喜欢钮置灰 + Toast「今日喜欢次数已用完，明天再来」；拖拽右滑仍由后端判定（保留现状） |

## 6. 本单验收

1. `cd app && flutter analyze` 零告警；`flutter test` 全绿；`bash scripts/verify.sh app` 全绿（末尾输出贴进 PR）。
2. **golden**（落在 `app/test/features/discovery/`）：卡面 × {明, 暗} × {有在线, 无在线} = 4；
   操作钮 × {明, 暗} × {default, 额度用完} = 4；空态 × {明, 暗} = 2；筛选 chip × {default, selected} = 2。
   合计 **12 张**。
3. **Semantics 断言**：喜欢 / 跳过 / 撤销三钮各有 `Semantics(label:)`；在线点读作「在线」；
   顶部入口读作「喜欢我的人，N 人」。
4. **手测（必须做，不能以「本机无模拟器」跳过）**：`emulator-5554` 上装包，逐项截图 ——
   滑卡左/右、按喜欢、按跳过、撤销倒计时、额度用完置灰、深色、系统「移除动画」、字号 1.3、配对编排。
5. **动效口径**：`grep -rn "Curves\." app/lib/features/discovery` 为空（全部换 `spring.*`）；
   `grep -rn "0xFF" app/lib/features/discovery` 为空；`grep -rn "Icons\." app/lib/features/discovery` 为空。
6. **循环动画**：全页除在线点呼吸与骨架屏外无循环动画（§7.3）；心跳脉冲必须消失。
7. **PR 开成 draft**，正文写「等待模拟器验收」，Before/After 截图由人补；动了
   `pubspec.yaml` / `pubspec.lock`（Phosphor 已在 E-5.1 引入，本单预计不动）则仍需人工合并。

## 7. 待拍板的开放问题

| # | 问题 | 我的建议 | 备选 / 影响 |
|---|---|---|---|
| 1 | 页面标题「发现」→「遇见」？ | **改**（与底栏一致，§9.1 把 tab 与页面都叫遇见） | 不改则同一页两个名字 |
| 2 | 喜欢钮去掉心跳脉冲与渐变？ | **去**（§7.3 禁止装饰性循环动画；渐变主按钮已被规范取消） | 保留脉冲 = 违反门禁口径，需先改规范 |
| 3 | 「点卡进资料页 + Hero 转场」本单做吗？ | **本单只做点击热区 + 普通 push**，Hero 留给 E-5.4（资料页单）一起做 | 本单做 Hero 需要资料页先有稳定的照片组件，跨单耦合 |
| 4 | 配对编排本单做，还是单开 E-5.2b？ | **本单做**（它在滑卡流程闭环里，拆开会让 E-5.2 交付一个「配对还是旧样式」的中间态） | 拆开则本单更小，但配对要等下一单 |
| 5 | 空态插画：暖色几何体还是 unDraw 图？ | **几何体**（无资产依赖，先交付；unDraw 统一换留给后续「插画体系」任务） | unDraw 需要下载/改色/入库，属于新增资产流程 |
| 6 | 「今日精选」区块保留吗？ | **保留**（功能不动，只换皮；§4 已定「空/失败整块不渲染」） | 删掉会丢一个已上线功能 |
| 7 | 撤销钮的 30 秒倒计时环保留吗？ | **保留**（窗口提示是业务语义，不是装饰） | 去掉环只留图标，用户不知道还能撤多久 |

**拍板后**：把结论写进本节下方「拍板结果」，再开工单（实现走 issue，不在会话里直接改代码）。

### 拍板结果（待填）

| # | 结论 |
|---|---|
| — | 待主人评审 |

## 8. 与后续页单的接口

- **E-5.4（我 + 资料页）**：卡 → 资料页的 Hero 转场在本单只留普通 push，Hero 由 E-5.4 落地；
  本单交付的 `ProfileCard` 照片层（圆角 / scrim / 指示点）应可被资料页复用。
- **E-5.3（对话）**：配对编排结束后「新配对」区在对话页顶部，本单只负责编排，不碰对话列表。
- **`core/ui` 新增组件**：`EmberChip` 与 `EmberActionButton` 供 E-5.3–E-5.6 复用；本单需为它们补
  golden 或 Semantics 断言（与 E-2 的组件层纪律一致）。
- **裸值纪律**：本单交付后，`app/lib/features/discovery` 下不得出现 `0xFF` / `Curves.` / `Icons.`；
  后续页单以本单为样板。
