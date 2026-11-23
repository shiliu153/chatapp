# E-5.1 页面规格：底栏 shell + 四个 Tab（骨架）

> **立项**：2026-11-23 · **状态**：page spec，**已确认**（2026-11-23 主人拍板，结论见 §7）
> **上游**：[Ember 规范](../specs/2026-11-23-ui-redesign-ember-design.md)（v0.1，2026-11-23 评审通过）§5 / §8.3 / §8.5 / §9.1 / §9.3
> **实施计划**：[E-5 逐页迁移](../plans/2026-11-23-ui-redesign-ember.md) 第 1 单
> **栈**：`app`（单一栈；本单不碰 `web`、不碰 `chapp/**`）

---

## 1. 目标

本单只做**壳**：底栏 + 四个 tab 的容器骨架 + 切 tab 的状态与动效。
四个 tab 的**页面内容**仍按「心跳」维护，由 E-5.2 起的页单逐页迁——本单不排布局、不搬内容。

用户可见的变化只有三件（其余都是底座替换）：

| # | 变化 | 从 → 到 |
|---|---|---|
| 1 | **tab 命名** | 发现 / 广场 / 消息 / 我的 → **遇见 / 回声 / 对话 / 我**（规范 §9.1） |
| 2 | **选中态** | 粉→橙渐变胶囊 → **朱砂实色胶囊**（`brand.default`，规范 §8.3 底栏行） |
| 3 | **切换动效** | `duration + curve` → **`spring.fast` 弹跳 + 胶囊位移**（规范 §8.5 底栏 selected） |

**明确不在本单**：页面内部布局与间距重排、tab 页的空态 / 错误态改写、配对成功的全屏编排、
Web 侧底栏（PC 布局没有移动底栏）、**除底栏这四枚之外的图标替换**（其余页面的图标随各页单走）。

## 2. 层级形态（规范 §9.3）

- 底栏是**常驻导航**，不是页面；四个 tab 各自是根页面，用 `IndexedStack` 保状态（沿用
  `app/lib/features/shell/home_shell.dart` 现有做法，切换 tab 不重建、不丢滚动位置）。
- 本单不引入底部 sheet、不引入独立二级页、不加 dialog —— 层级规则留给各页单。

## 3. 用的组件（规范 §8）

| 元素 | 用什么 | 取值来源 |
|---|---|---|
| 底栏本体 | 改造现有的 `AppBottomBar`（建议改名 `EmberNavBar`，旧文件删除不留双份） | §8.3：`surface.card` 胶囊，高 64，左右外距 12、底距 10，圆角 `radius.xl`；浮层用 `elev.2`，深色模式改 `border.strong` 1px + `surface.card`（§5.3） |
| 选中胶囊 | 纯容器（不叠 `emberGlow`——一屏最多一处高音，底栏不是） | `brand.default` 实色，高 40，胶囊圆角 `radius.pill` |
| 选中图标 / 标签 | — | 白图标 20 + 白字 `micro` 11/w700（§8.3）；未选中图标 24 `text.tertiary` + 标签 11 |
| 未读角标 | 复用 `core/ui/ember_badge.dart`（替换 `core/widgets/app_badge.dart`） | §8.5 角标行：`brand.default` 底 + `brand.on` 字 11/w700 + `radius.pill` + min 18×18；≥100 显示「99+」 |
| 图标 | **本单就换 `phosphor_glyphs`**（规范 §6 指定的 Flutter 包，纯 const `IconData`，随包带六个字重字体） | 未选中 = **Regular** 20/24 + `text.tertiary`；选中 = **Fill** + 白（坐在朱砂胶囊上，§8.3 的「白图标 20」优先于 §6 的「Fill + brand.default」——前者是底栏专用取值）；热区 ≥48×48（§8.4） |

**四个 tab 的图标映射**（Phosphor 名，Regular → Fill）：

| tab | 语义 | 图标 |
|---|---|---|
| 遇见 | 滑卡 / 推荐，主动词 | `cards` |
| 回声 | 广场动态流 | `broadcast` |
| 对话 | 会话列表 | `chat-circle` |
| 我 | 资料与设置 | `user` |

**不新增 token**：本单所需的色 / 圆角 / 间距 / 弹簧全部已在 `design/tokens/*.json` 里；
真缺值时按规范 §11.1 先改 token（那是 `flow` 栈的改动），不在页面里凑值。

## 4. 状态清单

| 元素 | 状态 | 口径 |
|---|---|---|
| 底栏 | default | 见 §3；未选中图标 24 `text.tertiary`、标签 11 `text.tertiary` |
| 底栏 | selected | `brand.default` 胶囊高 40 + 白图标 20 + 白字 11/w700，胶囊随选中项位移（`spring.fast`） |
| 底栏项 | pressed | 规范未定义 → **假定**复用卡片 pressed 的 `scale .98`，颜色不变（评审可改） |
| 底栏项 | focus | App 自绘 FocusRing（§8.4：2px `brand.default` + 2px 间隙），键盘 / 读屏可达 |
| 角标 | 0 / 1–99 / ≥100 | 0 不渲染；1–99 数字；≥100 「99+」 |
| 角标归属 | 只在「对话」tab | 沿用现有 `unreadTotalProvider`，不新开数据源 |
| 深色 | — | 无阴影：`border.strong` 1px + `surface.card`；选中胶囊仍 `brand.default`（深色为 `#FF9370` + 深字，`brand.on`） |
| reduced motion | — | `disableAnimations` 为真：120ms 线性淡入（`motion.reducedDurationMs`），胶囊**不位移**、图标**不缩放** |
| 字号缩放 | 0.85–1.3 | 底栏标签走 `micro`，按 §8.4 **固定不缩放**（避免撑破胶囊）；标签超长按 1 行省略 |
| 封禁 | `banned_heavy` | 整页替换为 `BannedPage`，底栏不渲染（沿用现状） |

## 5. 空态与错误态

- **底栏本身没有空态 / 错误态**：它不依赖网络。
- tab 页自身加载中（骨架）或失败（该页的 EmberEmpty / 错误态）**不得阻塞底栏**：底栏照常渲染、照常可切。
- 未登录 / 令牌失效由路由层拦截（`lib/router.dart`），本单不改鉴权路径。

## 6. 本单验收

1. `cd app && flutter analyze` 零告警；`cd app && flutter test` 全绿；`bash scripts/verify.sh app` 全绿（末尾输出贴进 PR）。
2. golden：底栏 × {明, 暗} × {未选中, 选中, 有角标, 角标 99+} = 8 张，落在 `app/test/features/shell/`。
3. Semantics 断言：每个 tab 项 `Semantics(label: '遇见 tab，已选中' / '对话 tab，3 条未读')`，与 §8.4「颜色不是唯一线索」对应。
4. 手测（**必须做，不能以「本机无模拟器」跳过**）：`emulator-5554` 上装包，逐项截图 —— 切四个 tab、
   深色模式、系统「移除动画」开启、字号 1.3。
5. 图标：底栏四处图标全部来自 `phosphor_glyphs`；该文件内不再有 `Icons.*`（Material）；
   六个字重字体随包打包后 APK 体积增量写进 PR 正文（供主人判断是否要子集化）。
6. 裸值：`grep -rn '0xFF' app/lib --include=*.dart` 除 `tokens.g.dart` 外为空（现仅位掩码一处，非色值）。
7. PR **开成 draft**，正文写「等待模拟器验收」，Before/After 截图由人补——本单是 App UI 可见改动；
   且因为动了 `pubspec.yaml` / `pubspec.lock`，**必须人工合并，worker 不得合并**。

## 7. 拍板结果（2026-11-23 主人确认）

| # | 问题 | 结论 |
|---|---|---|
| 1 | 图标族：本单是否顺带换 Phosphor Regular？ | **本单就换**。用规范 §6 指定的 `phosphor_glyphs`（pub.dev `2.1.2+2`，`sdk ^3.6.0` / `flutter >=3.27.0`，本项目 `^3.13.2` + Flutter 3.47.2 满足）。**这会让 `app/pubspec.yaml` + `pubspec.lock` 变化 —— 依赖锁改动属「永远不算低风险」，PR 必须由主人人工合并，worker 不得合并** |
| 2 | tab 改名（遇见 / 回声 / 对话 / 我）本单就上？ | **就上**，规范 §9.1 已定 |
| 3 | 角标偏移：规范只定尺寸（min 18×18）没定位置 | 沿用现状 `top: -6 / right: -12`（相对图标右上角） |

图标映射见 §3 的表；若某款图标在该包里不存在，取同语义最近的一款并在 PR 正文写明换了什么、为什么。

## 8. 与后续页单的接口

- 本单交付后，四个 tab 的页面仍是「心跳」口径 —— 见规范 §12 过渡期：**存量页面按旧规范维护，
  直到各自被迁**。E-5.2（遇见 / 滑卡）、E-5.3（对话 / 聊天）、E-5.4（我 / 资料）、E-5.5（回声）各开一单。
- 本单一旦合并并通过模拟器验收，就满足规范 §12 的「首个页面按新规范交付并通过验收」，
  E-4（转正 v1.0 + 归档心跳）即可开工。
