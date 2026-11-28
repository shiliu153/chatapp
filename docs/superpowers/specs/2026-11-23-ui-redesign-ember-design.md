# UI 设计语言「余烬 Ember」— 从零重建的设计规范

> **立项**：2026-11-23 · **状态**：**v1.0 生效**（2026-11-23 评审通过，同日转正）· 唯一在用的 UI 规范
> **实施计划**：[../plans/2026-11-23-ui-redesign-ember.md](../plans/2026-11-23-ui-redesign-ember.md)
> **取代**：[2026-09-15-ui-design-language-design.md](../archive/specs/2026-09-15-ui-design-language-design.md)（「心跳」，v1.5，**已归档**）。
> 那份文档的全部视觉口径（品牌色、渐变、字阶、圆角、动效、组件皮肤）自本文 **v1.0 生效起作废**，只作历史证据保留。
>
> **版本变更记录**
>
> | 版本 | 日期 | 变更 |
> |---|---|---|
> | v0.1 | 2026-11-23 | 首版草案 → 同日评审通过（主人审批），进入实施期（双轨：新页按本文、存量页仍按「心跳」） |
> | **v1.0** | 2026-11-23 | **转正生效**：token 链路（E-1）与两端接线（E-2 [#470](https://github.com/shiliu153/chatapp/pull/470) / E-3 [#468](https://github.com/shiliu153/chatapp/pull/468)）已合并、六道设计门禁在 `contract` 轨常驻；首个页面（E-5.1 底栏 shell，[#476](https://github.com/shiliu153/chatapp/pull/476)）按本规范交付并通过模拟器验收 —— §12 的三项齐备。同日旧「心跳」规范归档，**双轨结束、单轨生效** |
>
> 「余烬（Ember）」是**设计语言代号**，不是产品名。

---

## 1. 为什么重建，而不是迭代

旧规范的问题不是「不好看」。先把事实说准：「心跳」**有**深色模式（`app/lib/core/theme/heart_colors.dart`
的 `HeartDarkColors` + `web/src/styles/tokens.css` 的 `[data-theme='dark']`，由 `tokens.spec.ts` 双向锁定）。
真正的问题是四条，条条都有证据：

1. **对比度从来没守过。** 用本文 §11.2 那把脚本量旧色板（2026-11-23 实测）：

   | 旧配对 | WCAG | 判定 |
   |---|---|---|
   | 主按钮：白字 on `#FF2C55` | **3.66** | 不达 AA（正文需 4.5）——**这是线上主按钮** |
   | `text2 #8A8F9E` / 页面底 `#F6F7FB` | **3.02** | 不达 AA |
   | `text3 #B3B7C0` / 页面底 | **1.88** | 远低于任何门槛 |
   | `amber #FFB020` 上放白字 | **1.83** | 同上 |
   | 深色 `text3 #6E7482` / 卡片 | 3.72（APCA 30.5） | 灰得看不见 |

   这不是审美偏好，是可访问性硬失败。旧规范从头到尾没有一条阈值，也没有任何脚本量过。

2. **深色值是逐 token 手抄成三份的。** 浅色在 `AppColors`、深色在 `HeartDarkColors`、Web 侧在
   `:root` 与 `[data-theme='dark']` 两段。`tokens.spec.ts` 锁的是「两份抄得一致」，**不是「值对不对」**
   —— 抄错了但抄得一样，门禁照样绿。

3. **没有语义角色层。** 色彩只有十四个扁平名字（`text1/text2/text3`），没有 `surface` / `onSurface` /
   `container` / `outline` 这一层。后果是同一种灰被迫同时服务卡片底与页面底，压不出层级；
   想在凹陷区用更浅的次级文字，没有 token 可挑。

4. **动效用旧体系**（duration + curve）。手势打断（滑卡、拖拽面板）会「重启」而不是续接，这是手感问题，
   不是调参数能解决的。

5. **组件规范只写了正常态。** 没有 disabled / focus / pressed / loading 的逐项取值，验收时没有
   可机械对照的东西 —— 于是「验收」只能靠肉眼。

所以这次不是换一套配色，是换**产生配色的方式**：值有单一事实来源、口径能被脚本判定。
下面每一节都尽量写成可执行的形式。

---

## 2. 设计定位

**一句话**：一个温度可感、克制不喧哗的私人空间——用暖纸与朱砂，而不是霓虹与渐变。

| 维度 | 取向 | 反面（明确不做） |
|---|---|---|
| 气质 | 手作、私密、真实 | 潮流、赛事感、霓虹 |
| 色彩 | **单一强调色 + 暖中性** | 多色相、渐变主按钮、彩色文字 |
| 密度 | 松（内边距 20，行高 1.55） | 紧凑信息流、九宫格堆叠 |
| 动效 | 慢、软、可打断 | 弹跳、循环装饰动画 |
| 图像 | 全出血、大圆角、暖调 | 硬边裁切、冷调滤镜 |

**品牌签名元素**：`emberGlow` —— 一层极浅的朱砂径向光晕（不是渐变条）。
出现场合只有三处：① 主按钮的按压与聚焦；② 配对成功的扩散光；③ 「新配对」头像环。
**一屏最多一处**。这条纪律继承自旧规范（「一屏一个高音」），做法换了。

**与旧设计的断裂点**（评审时对照）：

| 旧 | 新 |
|---|---|
| 主色 `#FF2C55` + 粉橙渐变 | `#C93C22` 朱砂**实色**，全站无渐变主按钮 |
| 页面底冷灰 `#F6F7FB` | 暖纸 `#FBF7F3` |
| 拉丁字体 Space Grotesk | 标题 Fraunces（衬线），正文走系统中文字体 |
| 圆角 20/16/8，内边距 16 | 圆角 20/16/12，**内边距 20**，间距更松 |
| duration + curve | **spring（damping / stiffness）** |
| Material `*_rounded` 图标 | Phosphor Regular |
| 只有浅色 | 浅色 + 深色双模，跟随系统 |

---

## 3. 色彩系统

### 3.1 三层架构

| 层 | 内容 | 谁可以改 |
|---|---|---|
| **Tier 1 primitive** | `ember.*`（朱砂 10 档）、`paper.*`（暖中性 12 档） | 仅品牌决策，走 §11 变更流程 |
| **Tier 2 semantic** | `surface.*` / `text.*` / `border.*` / `brand.*` / `status.*` | 常态改动都在这一层 |
| **Tier 3 component** | `button.primary.*`、`avatar.online.*` 等 | **默认不建**；只在组件取值与语义不一致时才建（如在线点要在卡片底与页面底两种背景上都成立） |

不建状态色的完整色阶：危险/成功/警告各只需 `fg / on / container` 三个值，造 10 档没人用，反而给「随手挑一个」开口子。

### 3.2 Primitive 色阶

`ember`（朱砂，暖橙红 h≈14°）

| 档 | 50 | 100 | 200 | 300 | 400 | 500 | 600 | 700 | 800 | 900 | 950 |
|---|---|---|---|---|---|---|---|---|---|---|---|
| hex | `#FFF0E9` | `#FFD8C9` | `#FFB79E` | `#FF9370` | `#F2704A` | `#DC5127` | `#C93C22` | `#A82E18` | `#862314` | `#6A1C10` | `#1A0F0B` |

`paper`（暖中性，h≈30°，低饱和；档位数字只表示序号，**不是亮度百分比**）

| 档 | 0 | 5 | 10 | 20 | 30 | 40 | 50 | 60 | 70 | 80 | 90 | 92 | 95 | 100 | 110 | 120 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hex | `#FFFFFF` | `#FBF7F3` | `#F6F1EB` | `#F5EFE8` | `#EDE6DF` | `#DED4C9` | `#C4B9AD` | `#A39789` | `#8F8478` | `#6A5F55` | `#3A332D` | `#2E2723` | `#1E1916` | `#1C1714` | `#14110F` | `#100D0B` |

> 这两张表是**产物而非事实**：真正的 owner 是 `design/tokens/primitive.color.json`，
> 一致性由 `python scripts/design_spec_sync.py --check` 双向判定（表里有、JSON 里没有 = 红；
> 反过来也红）。改色阶请先改 JSON，再跑生成器与这道门禁。

### 3.3 Semantic 对照表（双模式，全部实测过线）

| Semantic | Light | Dark | 用途 |
|---|---|---|---|
| `surface.page` | `#FBF7F3` | `#14110F` | 页面底 |
| `surface.card` | `#FFFFFF` | `#1E1916` | 卡片、列表行、sheet |
| `surface.sunken` | `#F5EFE8` | `#100D0B` | 凹陷区、输入底、骨架底色 |
| `text.primary` | `#1C1714` | `#F6F1EB` | 正文、标题 |
| `text.secondary` | `#6A5F55` | `#C4B9AD` | 次级信息、说明 |
| `text.tertiary` | `#8F8478` | `#A39789` | 时间戳、占位、禁用文字 |
| `border.divider` | `#EDE6DF` | `#2E2723` | 分割线、描边 |
| `border.strong` | `#DED4C9` | `#3A332D` | 需要明确边界的容器 |
| `brand.default` | `#C93C22` | `#FF9370` | 主按钮底、强调文字、未读 |
| `brand.on` | `#FFFFFF` | `#1A0F0B` | 主色底上的文字 |
| `accent.default` | `#B4610C` | `#FFC38F` | 次强调、精选标识 |
| `accent.on` | `#FFFFFF` | `#1A0F0B` | 次强调底上的文字 |
| `status.danger` | `#A81E3C` | `#FF8FA3` | 错误、删除 |
| `status.onDanger` | `#FFFFFF` | `#2A0410` | 危险底上的文字 |
| `status.success` | `#10784A` | `#4FD69A` | 成功、在线点 |
| `status.onSuccess` | `#FFFFFF` | `#04140E` | 成功底上的文字 |
| `status.warning` | `#8A5F00` | `#FFC152` | 预警、会员 |
| `status.onWarning` | `#FFFFFF` | `#14100A` | 警告底上的文字 |
| `status.info` | `#54409E` | `#B3A5FF` | 系统通知、官方标识 |
| `overlay.scrim` | `#1C1714` @ 92% | `#000000` @ 92% | Toast、遮罩 |
| `overlay.on` | `#FFFFFF` | `#FFFFFF` | 遮罩上的文字（Toast） |

> `overlay.on` 配 `overlay.scrim` 用：Toast 是「遮罩底 + 浅色字」，页面里不许再写死白字。
> 对比度门禁走 `design/contrast-pairs.toml` 的实底口径（`parse_hex` 丢 alpha，量的是
> `#1C1714` / `#000000`：浅色 17.77 / 109.5，深色 21.00 / 110.6）；真实叠底
> （浅色页面底 `#FBF7F3` 上 92% 的 `#1C1714` ≈ `#2D2925`）对比度略低，仍远高于门槛
> （WCAG 14.43 / APCA Lc 106.8；深色叠底 20.85 / 110.6）。

### 3.4 对比度口径（分级，且是门禁）

按 APCA 的字号/字重分档，同时保留 WCAG 2.2 作底线：

| 用途 | 字号/字重 | WCAG 下限 | APCA Lc 下限 |
|---|---|---|---|
| 正文 | 15–17px / w400 | 4.5 | 75 |
| 次级 | 13–15px | 4.5 | 60 |
| 三级（时间戳） | 11–13px | 3.0 | 45 |
| 按钮文字 | 16px / w700 | 4.5 | 60 |
| 强调文字 / 链接 | 任意 | 4.5 | 60 |

**两条从实测里掉出来的硬规则**（不是审美意见）：

1. **深色模式的主按钮＝亮底 + 近黑文字**，浅色模式＝深底 + 白字。
   亮朱砂 `#FF9370` 配白字 WCAG 只有 2.17，必挂；配 `#1A0F0B` 是 8.65。
2. **深色模式的次级灰比直觉亮得多**。`#9BA5B4` 在 `#1E1916` 上 APCA 仅 54，必须到 `#C4B9AD` 才够 60。

### 3.5 使用纪律

- 一屏内 `brand` 强调面积不超过屏幕的 5%；`emberGlow` 最多一处。
- 文字不用彩色，链接/强调按钮除外；正文永远 `text.primary`。
- `status.danger` 与 `brand` 同属红区，**必须靠位置与图标区分**（危险操作永远在二次确认后，且带图标），不允许仅靠色相分辨。
- 头像底色允许低饱和暖色（`ember.50` / `paper.100` / 派生柔色），文字取同系深色。
- 深色模式不用阴影分层（见 §5.3）。

---

## 4. 字体与排版

### 4.1 字族策略

| 角色 | 字族 | 说明 |
|---|---|---|
| `font.display` | **Fraunces**（OFL，variable） | 只用于 ≥24px 的标题与大数字（年龄、计数）。衬线是这套语言的记忆点 |
| `font.body` | 系统无衬线 | 中文走系统（PingFang SC / MiSans / HarmonyOS Sans / Noto Sans CJK）；拉丁与数字在小字号走系统 SF/Roboto |

- **只打包 Fraunces 一个可变字体文件**（含 optical size 轴），体积可控；中文**不打包**任何字族（思源宋体全量太大，子集化维护成本高于收益）。
- 规则：`Fraunces` 只用于 `display` / `title` 两档；小字号数字（时间戳、角标、金额）走 `font.body`，避免衬线数字在小尺寸糊成一团。
- 落地约束：字体文件必须 `app/assets/fonts/` 与 `web/public/fonts/` **同名同内容**，`fonts.spec.ts` 双向比对（沿用既有门禁）。
- **已落地（2026-11-23）**：实物是 `Fraunces-Variable.ttf`（360,440 B，含 opsz / SOFT / WONK / wght 四轴）+ 同名 `OFL.txt`，两端逐字节一致；
  旧的 Space Grotesk 三份静态字重随「心跳」一起删除。两端接法各有一处坑，记在这里免得下次重踩：
  - **Flutter**：pubspec 的 `fonts:` 里**不要给可变字体写 `weight`** —— 写了等于声明「这份文件只有那个字重」，
    其余字重会被**假粗体**合成（衬线描边加粗会糊）。真实字重走 `TextStyle.fontVariations: [FontVariation('wght', …)]`，
    见 `app/lib/core/theme/app_typography.dart`。
  - **Web**：一条 `@font-face` 声明 `font-weight: 100 900` 即可，浏览器按 `font-weight` 走真实轴（`web/src/styles/base.css`）。
  - **全局字族**：`font.family.body` 在 token 里是一条 CSS 风格的字体链，Flutter 的 `fontFamily` 只认单个名字，
    所以主字族留空（平台默认 SF / Roboto）、中文链落到 `fontFamilyFallback`（见 `kBodyFontFallback`）。

### 4.2 字阶

| 名称 | 字号/字重 | 行高 | 字距 | 字族 | 用途 |
|---|---|---|---|---|---|
| `display` | 32 / w700 | 1.15 | -0.02em | Fraunces | Tab 大标题、年龄大字 |
| `title` | 24 / w600 | 1.25 | -0.01em | Fraunces | 区块标题、弹层标题 |
| `subtitle` | 17 / w600 | 1.35 | 0 | body | 列表主文字、昵称、会话名 |
| `body` | 15 / w400 | **1.55** | 0 | body | 正文、消息、按钮文字（按钮 w600–700） |
| `caption` | 13 / w400 | 1.45 | 0 | body | 辅助说明、预览 |
| `micro` | 11 / w500 | 1.3 | 0.01em | body | 角标、标签、底栏文字 |

### 4.3 排版纪律

- 正文行高 1.55（旧版 1.45）——松是这套语言的一部分，不要为了塞内容调紧。
- 最小字号 11（仅角标 / 底栏）；正文不小于 13。
- 允许系统字号缩放到 0.85–1.3；`micro` 档**不跟随缩放**（角标固定，避免撑破容器）。
- 数字对齐：表格、计数、金额一律用 tabular figures。

---

## 5. 形状、空间、层级

### 5.1 圆角

| token | 值 | 用途 |
|---|---|---|
| `radius.xs` | 8 | 小标签、chip 内元素 |
| `radius.sm` | 12 | 图片内容格、缩略图 |
| `radius.md` | 16 | 输入框、次级容器 |
| `radius.lg` | 20 | 卡片、大图 |
| `radius.xl` | 24 | 底部弹层上圆角、全屏大卡 |
| `radius.pill` | 999 | 按钮、头像、角标、导航胶囊 |

### 5.2 间距

4 基数：`4 / 8 / 12 / 16 / 20 / 24 / 32 / 40`。

- **页面水平内边距统一 20**（旧版 16）。
- 卡片间距 12；区块间距 24；标题与内容 12。
- 列表行高 68–76，头像 44–48。

### 5.3 层级（阴影 vs 描边）

| 场景 | Light | Dark |
|---|---|---|
| 卡片 | `elev.1`：`0 2px 8px rgba(28,23,20,.06)` | `border.divider` 1px + `surface.card` |
| 浮层（底栏、sheet、浮卡） | `elev.2`：`0 10px 24px rgba(28,23,20,.10)` | `border.strong` 1px + `surface.card` |
| 主按钮 | `emberGlow` 光晕 | 同左（光晕在深底上更明显） |

**深色模式不用阴影**——阴影在深底上不可见，靠描边和表面色差分层。这条要写进组件实现，不允许「两模式同一套 boxShadow」蒙混。

同屏层级别超过两级。

---

## 6. 图标

| 项 | 规范 |
|---|---|
| 字族 | **Phosphor Regular**（Flutter：`phosphor_glyphs`；Web：`@phosphor-icons/vue`） |
| 尺寸档 | 16（行内）/ 20（按钮内）/ 24（导航、工具栏）；不小于 16 |
| 状态 | 未选中 = Regular + `text.tertiary`；选中 = **Fill 字重** + `brand.default` |
| 语义色 | 在线 = `status.success`；未读 = `brand.default` 角标；系统/官方 = `status.info`；会员/精选 = `status.warning`；错误 = `status.danger` |
| 空态 | **禁止灰色图标占位**；用大号插画（unDraw，主色改为 `brand.default`）或暖色几何体 |
| 触控 | 图标可点区域 ≥48×48（App）/ 44×44（Web），图标本体可小 |

废弃 Material `*_rounded`——它的圆角是「系统圆角」，与衬线标题的手作感不搭。替换清单在实施计划里逐页列。

---

## 7. 动效

### 7.1 spring 基座

直接采用 M3 Expressive 的 spring 复合 token（damping / stiffness 成对使用，永不解开单值）：

| token | damping | stiffness | 用途 |
|---|---|---|---|
| `spring.fast` | 0.6 | 800 | 按压、开关、chip 选中 |
| `spring.standard` | 0.8 | 380 | 页面切换、展开收起、列表入场 |
| `spring.gentle` | 0.8 | 200 | 大卡片、sheet 上浮、头像环 |
| `spring.effects` | 1.0 | 1600 | 纯透明度/颜色过渡（无位移） |

选择规则：**有位移用 spatial 系列，只有透明度/颜色用 effects**。位移类动画一律用 spring（可被手势打断），不用 `Curves.*`。

### 7.2 三档清单

1. **微交互**（每个可点区域必须有）：按压 `scale .97`（`spring.fast`）；选中态切换用 `spring.fast`；角标出现 `scale .7→1`（`spring.fast`）。
2. **结构动效**：列表入场「上移 12 + 淡入」，逐项错峰 40ms（`spring.standard`）；页面 push 右滑入；Hero 转场（头像→资料页、动态卡→详情）。
3. **情感时刻**（只允许一处）：配对成功全屏编排——`emberGlow` 从双头像扩散、双向碰撞、粒子飘散，总时长 900–1400ms，**全程可点击跳过**。

### 7.3 约束

- 尊重系统减弱动态效果：`MediaQuery.disableAnimations` / `prefers-reduced-motion` 为真时，所有 spring 替换为 120ms linear 淡入，取消位移与缩放。
- 动效不阻塞交互；超过 400ms 的动画必须可跳过。
- **禁止纯装饰的循环动画**，例外只有两处：在线点呼吸、骨架屏。

---

## 8. 组件规范

### 8.1 状态矩阵（必须逐项给值，不再只写正常态）

每个组件规范必须覆盖这张表里打勾的状态：

| 组件 | default | pressed | focus | disabled | loading | error | selected |
|---|---|---|---|---|---|---|---|
| Button（主/次/文字/危险） | ✓ | ✓ | ✓ | ✓ | ✓ | — | — |
| Input / Textarea | ✓ | — | ✓ | ✓ | — | ✓ | — |
| Card（可点/静态） | ✓ | ✓ | ✓ | — | ✓(骨架) | — | ✓ |
| Avatar | ✓ | — | — | — | ✓ | — | ✓(在线/新配对) |
| Badge / Chip | ✓ | — | ✓ | — | — | — | ✓ |
| 导航胶囊（底栏） | ✓ | ✓ | ✓ | — | — | — | ✓ |
| 消息气泡 | ✓ | ✓ | — | — | ✓(发送中) | ✓(发送失败) | — |
| Sheet / Dialog | ✓ | — | ✓ | — | — | — | — |
| Toast | ✓ | — | — | — | — | ✓ | — |
| 空态 / 错误态 | ✓ | — | — | — | — | ✓ | — |
| 骨架屏 | ✓ | — | — | — | — | — | — |

### 8.2 关键取值（v0.1 已定部分）

| 组件 | 规范 |
|---|---|
| 主按钮 | `brand.default` 实底 + `brand.on` 文字 16/w700；高 52；`radius.pill`；`emberGlow` 光晕；按压 `scale .97` |
| 次按钮 | `surface.card` 底 + 1px `border.divider`；文字 16/w600 `text.primary`；高 52 |
| 文字按钮 | `brand.default`，15/w600，无底；最小触控 48 |
| 危险按钮 | `status.danger` 描边；确认后实底 + `status.onDanger` |
| 禁用态 | 底 `surface.sunken`、字 `text.tertiary`、无光晕、无按压反馈 |
| 输入框 | `surface.card` 底 + 1px `border.divider`；聚焦 2px `brand.default` + 2px 外扩；`radius.md`；高 52 |
| 卡片 | `surface.card` + `radius.lg` + `elev.1`；内边距 20；可点卡片按压 `scale .98` |
| 头像 | 一律圆形；尺寸 28/32/40/48/56/96；在线点直径 11（小场景 8）+ `status.success` + 呼吸；「新配对」用 `emberGlow` 环 2.5px（**不画渐变，画光晕**） |
| 底栏 | 悬浮胶囊：`surface.card` + `radius.xl`，高 64，左右外距 12、底距 10；四 tab；选中 = 朱砂胶囊（`brand.default`，高 40）+ 白图标 20 + 白字 10/w700 |
| 消息气泡 | 自己：`brand.default` 实底 + `brand.on` 字，`radius.md` + 靠头像侧上角 6，最大宽 72%，内边距 12/16；对方：`surface.card` + `text.primary`，圆角镜像 |
| 时间条 | 12 / `text.tertiary` 居中，上下边距 12；间隔 >5 分钟插入 |
| Toast | `overlay.scrim` 底 + `overlay.on` 字 13 + `radius.md`；底栏上方 12；淡入 + 上移 8；2s 自动消失 |
| 底部弹层 | `surface.card`；上圆角 24；顶部拖把 36×4 `border.divider` |
| 空态 | 插画 72–96 + 标题 17/w600 + 说明 13/`text.secondary` + 可选主按钮 |
| 骨架屏 | `surface.sunken` 色块，透明度 .5↔1，1.2s 循环，形状按目标内容 |

---

### 8.3 状态取值表

**取值只允许引用 §3.3 / §5 / §7 的 token**。下表是验收时逐格对照的那一份 —— 少一格就是一条待补的规范。

**按钮**

| 状态 | 主按钮 | 次按钮 | 文字按钮 | 危险按钮 |
|---|---|---|---|---|
| default | 底 `brand.default` / 字 `brand.on` / `emberGlow` | 底 `surface.card` / 描边 1px `border.divider` / 字 `text.primary` | 字 `brand.default` 15/w600，无底 | 描边 1px `status.danger` / 字 `status.danger` |
| pressed | `scale .97` + 光晕降至 50% | 底 `surface.sunken` + `scale .97` | 底 `surface.sunken` | 底 `status.danger` + 字 `status.onDanger`（**仅在二次确认后**） |
| focus | 外扩 2px `brand.default` + 2px 间隙 | 同左 | 同左 | 外扩 2px `status.danger` |
| disabled | 底 `surface.sunken` / 字 `text.tertiary` / 无光晕 / 无按压 | 同左，描边透明 | 字 `text.tertiary` | 同左 |
| loading | 保持底与字，尾随 16 白色转圈，禁点击 | 同左，转圈取 `brand.default` | 保持字号，转圈替换文字 | 同主按钮 |

**输入 / 卡片 / 头像**

| 组件 | 状态 | 取值 |
|---|---|---|
| 输入框 | default | `surface.card` 底 + 1px `border.divider` + 字 `text.primary` + 占位 `text.tertiary`；`radius.md`；高 52；内边距 16 |
| 输入框 | focus | 2px `brand.default` 描边 + 2px 外扩 `brand.default` @12% |
| 输入框 | error | 2px `status.danger` 描边 + 下方 13 `status.danger` 说明（**必须同时有文字**，不能只变红） |
| 输入框 | disabled | `surface.sunken` 底 + 字 `text.tertiary` + 描边透明 |
| 卡片 | default | `surface.card` + `radius.lg` + `elev.1` + 内边距 20 |
| 卡片 | pressed | `scale .98`（阴影不变） |
| 卡片 | selected | 2px `brand.default` 描边（不放大，避免布局跳动） |
| 卡片 | loading | 骨架：`surface.sunken` 色块，透明度 .5↔1，1.2s 循环 |
| 头像 | default | 尺寸 28/32/40/48/56/96；圆形；无照片时首字 + 柔色底 |
| 头像 | selected(在线) | `status.success` 点直径 11（小场景 8）+ 2px 背景色描边 + 呼吸 |
| 头像 | selected(新配对) | `emberGlow` 环 2.5px |
| 头像 | loading | `surface.sunken` 圆 + 骨架 |

**角标 / 导航 / 气泡 / 浮层 / 空态**

| 组件 | 状态 | 取值 |
|---|---|---|
| 角标 | default | `brand.default` 底 + `brand.on` 字 11/w700 + `radius.pill` + min 18×18；数字 ≥100 显示「99+」 |
| Chip | default / selected | 未选中 `surface.sunken` + `text.secondary`；选中 `brand.default` + `brand.on` |
| Chip | disabled | `surface.sunken` + `text.tertiary` |
| 底栏 | default | `surface.card` 胶囊（高 64，左右外距 12、底距 10）；未选中图标 24 `text.tertiary` + 标签 10 |
| 底栏 | selected | `brand.default` 胶囊高 40 + 白图标 20 + 白字 10/w700；切换用 `spring.fast` 弹跳 + 胶囊位移 |
| 气泡 | 自己 / 对方 | 自己 `brand.default` + `brand.on`；对方 `surface.card` + `text.primary`；`radius.md`，靠头像侧上角 6，最大宽 72%，内边距 12/16 |
| 气泡 | loading(发送中) | 气泡保持，右下角 12 转圈；不显示时间 |
| 气泡 | error(发送失败) | 气泡左侧 `status.danger` 感叹号 + 点按重发（**不静默丢弃**） |
| Sheet | default | `surface.card` + 上圆角 24 + 拖把 36×4 `border.divider`；进入 `spring.gentle`；scrim `surface.scrim` |
| Toast | default | `surface.scrim` 底 + `overlay.on` 字 13 + `radius.md`；底栏上方 12；`spring.effects`；2s 自动消失；不可堆叠（新的顶替旧的） |
| 空态 | default | 插画 72–96 + 标题 17/w600 + 说明 13 `text.secondary` + 可选主按钮；**禁止灰色图标占位** |
| 骨架 | default | `surface.sunken`，透明度 .5↔1，1.2s 循环，形状按目标内容 |

### 8.4 交互与无障碍口径

| 项 | 口径 |
|---|---|
| 触控 | 可点区域 ≥48×48（App）/ ≥44×44（Web）；图标本体可以更小，热区不能缩 |
| 焦点环 | Web 用 `:focus-visible`：2px `brand.default` + 2px 间隙；App 用自绘 FocusRing 组件；**禁止去掉焦点环**（`outline: none` 必须同时给替代视觉） |
| 键盘 | Tab 顺序跟随视觉顺序；`Esc` 关弹层；弹层打开时焦点困在层内，关闭后回到触发元素 |
| 颜色不是唯一线索 | 所有状态色必须配**图标或文字**：错误带感叹号、在线带「在线」文案或点位 + 语义标签、未读带数字 |
| 语义标签 | 图标按钮必须有 `Semantics(label:)` / `aria-label`；图片有替代文字；纯装饰图形标 `excludeSemantics` |
| 读屏播报 | 列表行 = 昵称 + 最后一条 + 时间；聊天消息 = 方向 + 内容 + 时间 + 发送状态；配对成功要主动播报不强依赖动画 |
| 字号缩放 | 支持 0.85–1.3；`micro` 档**不跟随**（角标固定，避免撑破容器）；缩放到 1.3 时列表行高允许自适应到 84 |
| 减弱动态效果 | `disableAnimations` / `prefers-reduced-motion` 为真：全部 spring 替换为 **120ms 线性淡入**，取消位移与缩放；配对编排降级为静态结果页 |
| 门禁 | Web：axe-core 零 critical + Lighthouse a11y（`scripts/verify.sh web`）；App：golden 截图 + Semantics 断言（`scripts/verify.sh app`）；对比度：`scripts/design_contrast.py --check` |



本次重构**包含 IA 与交互流**，不只是视觉层。v0.1 主张如下（页面级细节留实施计划逐页定）：

## 9. 信息架构

### 9.1 主轴

底部导航四项：**遇见 / 回声 / 对话 / 我**。

- 「遇见」= 滑卡与推荐，App 的主动词，永远默认落地页。
- 「回声」= 广场动态流（改名理由是它是「别人留下的痕迹」，不是信息广场）。
- 「对话」= 会话列表，顶部固定「新配对」横向区。
- 「我」= 资料与设置。

### 9.2 配对成功 = 独立状态，不是页面

配对时刻不进任何 tab：全屏编排 → 结束后落到「对话」顶部的「新配对」区。
**理由**：这是产品唯一的「情感高音」，放进 tab 就等于降级成通知。

### 9.3 层级选择规则（新，替代旧的无规则情况）

| 场景 | 形态 |
|---|---|
| 单一字段编辑、筛选 | 底部 sheet（≤60% 屏高） |
| 需要专注完成的流程（登录、编辑资料） | 独立二级页 |
| 破坏性确认 | Dialog（必须带图标 + 明确动词） |
| 轻量结果反馈 | Toast（不打断） |
| 沉浸内容（大图、动态详情） | 全屏 + Hero 转场 |

### 9.4 二级页统一 shell

顶栏高 52（返回 22 + 标题 17/w600 居中）；内容按卡片组织，水平内边距 20；滚动时顶栏可透明化（仅图片头图场景）。

---

## 10. 落地架构（token 单一事实来源）

### 10.1 链路

```
design/tokens/*.json   (DTCG 格式，Tokens Studio 兼容)   ← 唯一事实来源，可 review
        │  只读
        ▼
scripts/design_tokens.py  （DTCG 解析 + 代码生成，纯标准库）
        ├─→ app/lib/core/theme/tokens.g.dart          （生成物，禁手改）
        ├─→ web/src/styles/tokens.generated.css       （生成物，禁手改）
        └─→ design/tokens.resolved.json               （给 agent 与文档查值）
```

**为什么不用 Style Dictionary（2026-11-23 实测后改）**：它是 JS 包，而 `contract` 轨
只装 Python（PyYAML + tree-sitter）。为了让两份产物生成，把 Node 拉进契约轨、并让
门禁依赖 `npm ci`，成本远高于收益；DTCG 用到的子集只有「嵌套分组 + `{alias}` 引用」，
纯标准库两百行就够，且没有版本漂移。

**为什么 CSS 产物叫 `tokens.generated.css` 而不是 `tokens.css`**：过渡期旧文件
`web/src/styles/tokens.css`（心跳口径，被 `tokens.spec.ts` 双向锁定）还在服役。
生成物换一个名字并存，E-3 接线时删旧的、改引用，避免同一次改动同时动规则与实现。

### 10.2 目录约定

| 路径 | 内容 | 手改 |
|---|---|---|
| `design/tokens/primitive.color.json` | 朱砂与暖中性色阶 | ✓ |
| `design/tokens/semantic.light.json` / `semantic.dark.json` | 语义层双模式 | ✓ |
| `design/tokens/scale.json` | 间距、圆角、字阶、spring | ✓ |
| `design/tokens.resolved.json` | 展开后的最终值 | ✗ |
| `app/lib/core/theme/tokens.g.dart` | Flutter 常量 | ✗ |
| `web/src/styles/tokens.generated.css` | CSS 变量（过渡期与旧的 `tokens.css` 并存） | ✗ |

### 10.3 Figma 侧（免费档）

> **2026-11-28 按官方分档表复核过一次，本节已把当初的两条错误假设改掉。**
> 依据：[Paid Figma plugin features](https://docs.tokens.studio/get-started/pro-licence)
> 的 Free / Team 对照表（不是营销页的口径）。

- 免费档 = 1 个项目 / 1 编辑者。**仓库 JSON 是事实来源，Figma 是可视化编辑端**，这条不变。

| 能力 | 免费档 | Team 档 |
|---|---|---|
| token 数与 set 数 | 不限（**同名 token 允许存在于不同 set**，这正是双模式的基础） | 同 |
| 同步到 Git / 外部存储 | ✅ 但**只能一个文件** | 多文件 + 分支 |
| **新建 / 修改 Theme** | ❌ 只能切换别人建好的 Theme | ✅ |
| 多模式 Figma Variables | ❌（依赖 Theme） | ✅ |

两条被证伪的旧假设：

1. ~~「Figma 内靠切换 theme 预览双模式」~~ —— **建 Theme 是付费项**，免费档建不出来。
   免费档的替代是手动勾选 set 的 checkbox（启用 `light` / 停用 `dark`），能预览，
   但每切一次要手点，且不保存成可切换的 Theme。
   注：**Figma 原生 Variables 我们本来就不用**（消费者是 `design_tokens.py`），
   所以「不支持多模式 Variable 同步」对我们不构成损失。
2. ~~「连 GitHub raw URL 拉取」~~ —— 能连，但免费档只允许**单文件**同步；本仓库是
   4 个文件，单文件同步会把它们合并/覆盖成一个。**所以本轮不接 sync provider，
   走「本地 JSON 导入 + 导出」**：Tokens Studio 可以一次性吃下一个 set 的 JSON。

工作方式（免费档下真实可行的形态）：

- 一次只编辑**一个 set**（`light` / `dark` / `primitive` / `scale`），改完导出该 set 的
  JSON，提交 PR —— 与代码改动走同一条评审。双模式 = 两轮，不是一轮。
- **只允许在 Figma 里改值，不允许改结构**（token 名、层级、`$type`、`$description`、
  新增分类一律走 PR）。
- 这条纪律**不靠自觉**，靠机械判据：`python scripts/figma_tokens_roundtrip.py --export <导出文件>`
  把差异分成「值变更 / 结构变更 / 悬空引用」三类，结构变更（路径增删、类型变更、描述变更）
  与悬空引用（值被改成了仓库里不存在的 `{alias}`）**都拒绝落盘**，只有值变更可用 `--apply`
  写回源文件；导出物里的 `$themes` / `$metadata` 包裹块、legacy 键名（`value` 而非 `$value`）、
  `hex → rgba()` 改写、`"8px" → 8`、`fontFamily` 数组化都在该脚本里归一，不算结构变更。
- **真实往返踩到的坑（2026-11-28 第一次导出）**：本项目的 set 根是 `color` 分组，Tokens Studio
  会把引用写成 **set 内相对路径** `{ember.100}`，而仓库要求全路径 `{color.ember.100}`。
  这种值进仓库就是悬空引用（`design_tokens.py` 会 fail-closed），所以校验器会拦下并直接提示
  正确写法。**在 Figma 里把值改成「引用另一个 token」时，务必确认导出物里的路径带全前缀。**
- 落盘后照旧 `python scripts/design_tokens.py --write` 重生成三份生成物，
  `--check` 必须绿（`scripts/verify.sh contract` 兜底）。

**什么时候才值得升 Team（€39/月）**：当且仅当出现下面任一情况——
① 双模式往返的频率高到「两轮手工导出」成为瓶颈；② 需要把多文件目录直接挂成 sync provider
（省掉手工导出）；③ 需要 Figma 原生 Variables 的多模式做原型联动。
在此之前**不付费**；升档只换同步方式，token 结构与纪律不变。
（价格以 [tokens.studio/pricing](https://tokens.studio/pricing) 当期页面为准：官网写明
所有插件付费能力已并入 Team 档，历史 Pro / Starter Plus / Essential 订阅自动迁移。）


### 10.4 过渡期双轨

新链路落地前，`app` 与 `web` 两处手改的旧规矩**继续有效**；落地后 `docs/standards/sources-of-truth.md` 里「视觉 token」那行的 owner 改为 `design/tokens/`，双改规矩同时废除。**不允许两套并行超过一个交付批次**。

---

## 11. 变更流程与验收门禁

### 11.1 设计变更流程（任何视觉决策都走这条）

1. 想改视觉 → **先改 `design/tokens/*.json`**（PR，含对比度自检输出）。
2. 生成物由 CI 重生成并比对（禁止手改生成物）。
3. 若涉及组件取值 → 同一次 PR 更新 §8 状态矩阵。
4. 若涉及新场景 → 先更新本文件（v1.x + 变更记录）再写代码。

### 11.2 门禁（新增，全部要能机械跑）

| 门禁 | 判什么 | 命令 |
|---|---|---|
| token 生成物新鲜度 | JSON 改了但生成物没跟上 → 红；**明暗两套键集不一致**也红（少一个深色值 → 该元素在深色模式下静默回落到浅色值） | `python scripts/design_tokens.py --check` |
| 规范 ↔ token 同步 | §3.2 / §3.3 / §18.2 的表与 `design/tokens/*.json` 不一致（含透明度）→ 红，**双向**；§18.2 整节被删属正常（迁移完成），不判红 | `python scripts/design_spec_sync.py --check` |
| 对比度 | §3.4 全部分级配对，双模式 → 任一不过 → 红 | `python scripts/design_contrast.py --check` |
| 裸值 | 新代码出现裸 hex / 裸字号 / 裸间距 / 裸圆角 → 红 | App：`python scripts/check_app_raw_values.py --check`（门禁 `app-raw-values`，扫 `app/lib`、排除 token 生成物，存量按脚本内的逐条白名单放行）；Web：`stylelint` + `eslint` 规则 |
| 视觉回归 | 关键页 golden 截图漂移 → 红 | `scripts/verify.sh app`（golden） |
| 无障碍 | Web 页 axe-core 零 critical + Lighthouse a11y | `scripts/verify.sh web` |
| 字号 | 正文 <13、任意 <11 → 红 | 并入裸值判定：App 由 `check_app_raw_values.py` 对写死的字号一并报出下限 |

对比度校验脚本的判据**就是 §3.4 那张表**，不许在代码里另写一份阈值。

### 11.3 新增页面的流程

1. 写 page spec（一页纸）：目标 / 层级形态（§9.3）/ 用的组件 / 状态清单 / 空态与错误态。
2. 评审通过后开工单（实现走 issue，不在会话里直接改代码）。
3. 验收：golden + 模拟器手测（App）/ 真浏览器（Web）+ 门禁全绿。

---

## 12. 规则边界与过渡期

- **唯一允许偏离的情形**：本文件未覆盖的新场景。处理顺序：先挑最接近的 token 复用 → 实现时注明 → 确需新 token 时先更新本文件（v1.x）。
- **禁止**：裸 hex / 裸字号 / 裸间距 / 裸圆角；§3 之外的色相；渐变主按钮；纯装饰循环动画；灰色图标空态；深色模式套用阴影。
- **过渡期已于 2026-11-23 结束**（本文 v1.0 生效），下面是它当时说了什么，供对照：
  - 本文件 2026-11-23 评审通过后实施即解封：`flow` 链路（E-1）与两端接线（E-2 / E-3）已落地，
    逐页迁移（E-5）按 §14 开工单；
  - 过渡期内存量页面继续按旧规范（「心跳」）维护，直到该页被 E-5 迁移为止；**现在没有例外** ——
    存量页在被迁移前照旧实现可以，但**任何新写的视觉取值只认本文**；
  - 旧规范文件顶部的作废横幅与双轨口径已随归档消失（文件在
    `archive/specs/2026-09-15-ui-design-language-design.md`，只作历史证据）。
- **v1.0 生效条件（三项，2026-11-23 全部满足）**：
  1. token 链路落地 —— E-1（[#467](https://github.com/shiliu153/chatapp/pull/467)）；
  2. 门禁全绿 —— 六道设计门禁常驻 `contract` 轨（`contract-design-tokens` / `-contrast` / `-spec-sync`
     各带一道 `-selftest`）；
  3. 首个页面按新规范交付并通过验收 —— E-5.1 底栏 shell（[#476](https://github.com/shiliu153/chatapp/pull/476)），
     2026-11-23 在本机 Pixel_7 模拟器上逐项手测（四个 tab / 深色 / 移除动画 / 字号 1.3）通过。
  三项齐备后旧规范已 `git mv` 到 `archive/specs/`，`CLAUDE.md` 的 UI 规则段与 `AGENTS.md` 的 App 行
  也在同一次改动里改成单轨。

---

## 13. 规模风险（必须先承认）

本次重构包含 IA、组件层、双端 token 链路与全站页面迁移，远超「换配色」。因此：

- **实施必须拆成单栈工单**（`flow` 建链路 / `app` 换底座与组件层 / `web` 接 PrimeVue 与新 token / `docs` 收口），一条工单一条栈，跨栈需求回报拆单。映射见 §14。
- **页面迁移分批**，每批一个 PR，每批可独立回滚。
- token 链路（`flow`）必须**先于**任何页面改造交付，否则页面改造会再造一批硬编码。

---

## 14. 实施拆单（E-1 / E-2 / E-3 / E-4 已落地；E-5 进行中）

| 单 | 栈 | 内容 | 验收 | 状态 |
|---|---|---|---|---|
| E-1 | `flow` | `design/tokens/*.json` + `scripts/design_tokens.py` + `scripts/design_contrast.py` + `scripts/design_spec_sync.py` + 门禁注册 | 三个 `--check` 绿；`scripts/verify.sh contract` 绿 | **已落地**(2026-11-23)：双模式配对全过线，生成物按字节锁定，规范与 token 双向比对 |
| E-2 | `app` | 换 `core/theme` 为生成物；`core/ui` 组件层按 §8 重建 | `scripts/verify.sh app` 绿 + 模拟器验收 | **已落地**(2026-11-23，PR [#470](https://github.com/shiliu153/chatapp/pull/470))：会话内联交付，工单 [#465](https://github.com/shiliu153/chatapp/issues/465) 随之关闭；`app/lib` 已无手写色值 |
| E-3 | `web` | `tokens.generated.css` 接线 + PrimeVue unstyled + passThrough 映射；删除旧的 `tokens.css` 与 `tokens.spec.ts` 双份比对 | `scripts/verify.sh web` 绿 + axe 零 critical | **已落地**(2026-11-23，PR [#468](https://github.com/shiliu153/chatapp/pull/468))：会话内联交付，工单 [#466](https://github.com/shiliu153/chatapp/issues/466) 随之关闭；`tokens.css` 已删，`tokens.spec.ts` 改为生成物存在性断言 |
| E-4 | `docs` | 本文转正 v1.0；旧规范归档；`CLAUDE.md` / `AGENTS.md` / `sources-of-truth.md` 三处引用同改 | `scripts/verify.sh contract` 绿 | **已落地**(2026-11-23)：本文转 v1.0，旧规范 `git mv` 到 `archive/specs/`，四处引用同一次改完（纯文档，`contract` 轨 39/39 绿） |
| E-5.1 | `app` | 底栏 shell + 四个 tab 骨架（含 Phosphor 图标） | `scripts/verify.sh app` 绿 + 8 张 golden + 模拟器手测 | **已落地**(2026-11-23，[#476](https://github.com/shiliu153/chatapp/pull/476))：底栏换 `EmberNavBar`（遇见/回声/对话/我），这就是 §12 第三项里的「首个页面」 |
| E-5… | `app` / `web` | 逐页迁移（按 §13 分批），每页一单 | 每单 golden + 手测 | **进行中**(2026-11-23 起)：E-5.1 已交付，后续页单按批次排 |

---

## 15. 未决

- **品牌名与 logo**：本文只定视觉语言，产品名与标识另立设计任务。
- **插画体系**：空态先用 unDraw 改色，是否需要专属插画形象待定。
- **动态类型 / 无障碍的进取档**（AAA、屏幕阅读器全链路走查）暂不做，只保 AA + APCA 分级。
- **iOS**：当前项目只发布 Android + PC Web；若上 iOS，Dynamic Type 会让 `micro` 档设计重新评估。
- **Fraunces 的子集范围**：是否只保留拉丁基本集 + 数字（体积更小），待实测字形覆盖后定。

---

## 16. 决策记录

| 决策 | 结论 | 依据 |
|---|---|---|
| 重构范围 | 视觉 + 组件 + 信息架构全部重做 | 用户 2026-11-23 拍板 |
| 品牌基座 | 全部换新，方案 A「余烬 Ember」 | 用户从三套方案中选定 A |
| 双模式 | 浅色 + 深色，跟随系统 | 用户选定 |
| token 工具链 | DTCG JSON 为源 + Style Dictionary 生成；Figma Variables + Tokens Studio 做可视化端 | 用户选定；免费档限制见 §10.3 |
| Web 组件库 | PrimeVue unstyled + Tailwind + passThrough | 用户选定 |
| 对比度口径 | WCAG 2.2 AA 底线 + APCA 分级 | 实测：旧 `text2` 在白卡上 APCA 不足，WCAG 4.5 对灰字过宽 |
| 阴影 vs 描边 | 深色模式不用阴影 | 阴影在深底上不可见 |
| 主按钮文字色 | 随模式翻转（浅底深字 / 深底白字） | 实测：亮朱砂配白字 WCAG 2.17 |
| 字体 | 标题 Fraunces + 正文系统中文字体 | 衬线是记忆点；中文打包字体成本高于收益 |
| 图标 | Phosphor Regular 取代 Material rounded | 与衬线标题的手作感一致 |
| 生成器实现 | 纯标准库自研 DTCG 解析，**不用 Style Dictionary** | 它是 JS 包；`contract` 轨只装 Python，为两份产物引入 Node 与 `npm ci` 成本过高，且子集只需「分组 + 别名」 |
| 对比度阈值归属 | 阈值只在规范 §3.4，脚本解析这张表 | 代码里再写一份阈值必然分叉；解析不出来时 fail-closed 判红 |
| 规范评审 | **通过**（2026-11-23 主人审批 v0.1），实施解封：E-5 逐页迁移可开工 | 视觉口径必须先定稿才能派单，否则 worker 按未定稿施工 |
| CSS 产物命名 | `tokens.generated.css`（过渡期与旧 `tokens.css` 并存） | 避免同一次改动同时动规则与被旧测试锁定的实现 |

---

## 17. 选型依据与外部资源清单

九层选型的**依据与被否方案**。这一节的作用不是留链接，是让下一个人看到「为什么不选那个」
——否则半年后会有人重新提议一遍 Lottie 或 Ant Design Vue。

| 层 | 选了什么 | 依据 | 否掉了什么（理由） |
|---|---|---|---|
| ① 硬标准 | [WCAG 2.2](https://www.w3.org/TR/WCAG22/) 作底线 + [APCA](https://git.apcacontrast.com/documentation/APCA_FAQ) 作感知判据 | 实测：`#8A8F9E` 在白卡上 WCAG 4.5 过关、APCA 仅 54；只守 WCAG 会让灰字普遍偏浅 | 只守 WCAG AA（对中灰过于宽松，等于没管灰字） |
| ② 结构参照 | [M3 的角色体系](https://m3.material.io/styles/color/the-color-system)（ColorScheme 角色 + tonal）+ [Ant Design 设计价值观](https://ant.design/docs/spec/values-cn) 的写法（规则 + 为什么 + 反例）+ [shadcn/ui](https://ui.shadcn.com/) 的组件页结构（variant × state 矩阵） | 三者各补一块：M3 给角色、Ant 给中文写作范式、shadcn 给可验收的组件页形态 | 直接套用任何一套的**视觉**（桌面后台气质 / Tailwind 默认调色板 / Material 系统感） |
| ③ token 工具链 | DTCG JSON 为源 + Figma Variables / [Tokens Studio](https://docs.tokens.studio/) 免费档做编辑端 + 自研生成器（§10.1） | 免费档 1 项目 / 1 编辑者，够单人用；仓库 JSON 可 review、可进 CI | [Style Dictionary](https://styledictionary.com/)（JS 包，会把 Node 拉进只装 Python 的 `contract` 轨）；Tokens Studio Team 档 €39/月（多模式同步，暂不需要） |
| ④ 组件库 | Flutter：M3 原生 + 自建 `core/ui`；Web：[PrimeVue 4 无样式模式](https://primevue.dev/theming/unstyled/) + Tailwind v4 `@theme` + passThrough | 无样式模式把「组件行为与无障碍」和「视觉」彻底分开，视觉全部由 token 注入 | Naive UI（主题只能整体覆盖，难锁单点）、Element Plus（视觉陈旧、性能弱）、Ant Design Vue（维护停滞） |
| ⑤ 素材 | 头像 [DiceBear](https://www.dicebear.com/how-to-use/http-api/)；空态插画 [unDraw](https://undraw.co/)；字体 [Fraunces](https://fonts.google.com/specimen/Fraunces)（OFL，可变字体，仅标题）+ 系统中文字体 | DiceBear 可用 userId 作 seed 生成稳定头像；unDraw 免署名且可在线改主色 | Space Grotesk（与衬线标题气质不搭，且属旧品牌）；打包思源宋体（全量 20MB+，子集化维护成本高于收益）；Unsplash/Pexels **只允许做 demo 数据**，不入生产 |
| ⑥ 动效 | [M3 Expressive 的 spring token](https://m3.material.io/styles/motion/overview/specs)（damping / stiffness 成对，值见 §7.1） | 弹簧可被手势打断；duration + curve 的动画在滑卡 / 拖拽面板上会「重启」 | Lottie / Rive 运行时（包体积 + 默认不满足 reduced-motion + 400ms 可跳过）；纯装饰循环动画 |
| ⑦ 参考库 | [Mobbin](https://mobbin.com/) 看**流程级**、[Pttrns](https://www.pttrns.com/) 看**单交互级**（已完全免费）、Figma Community 看版式 | 三种颗粒度各司其职 | Dribbble 类作品站做可用性依据（几乎没有真实状态、空态、错误态）；照抄竞品视觉 |
| ⑧ 验收工具 | axe-core + Lighthouse（Web）、golden 截图（App）、自研 `design_contrast.py`（双模式阈值） | 前三者能进 CI；对比度那一道必须自研，因为阈值 owner 是本文 §3.4 | 只靠 [Stark](https://www.getstark.co/) 之类插件人工查（不可进 CI，会退回「靠人记得」） |
| ⑨ 中文生态 | [TDesign](https://tdesign.tencent.com/)（有 Flutter 版，中文移动端最贴近的参照）；[HarmonyOS Design](https://developer.huawei.com/consumer/cn/design) 仅在决定上鸿蒙时启用 | 两者都能给中文场景的实战口径（字重、行高、密度） | 把 TDesign 视觉当默认皮肤；在没决定平台前就按鸿蒙规范设计 |

**许可纪律**：DiceBear 各 style 的许可不一致（CC0 与 CC-BY 混排），**逐款确认后再用**；
unDraw 免署名；Fraunces 为 OFL，随包带许可文件；Unsplash / Pexels 只作 demo 图源。

**协作工具的备选**：若 Figma 不可用，中文生态里的替代是即时设计 / 蓝湖（交付与标注），
但 **token 的事实来源仍在 `design/tokens/`**，工具换来换去不影响门禁。

---

## 18. 旧「心跳」→ 余烬 Ember 迁移对照

E-5 逐页迁移时照这张表换。左列的名字与值是**线上真实在用的**（`app/lib/core/theme/*.dart` 与
`web/src/styles/tokens.css`），不是凭印象写的。

### 18.1 先看这七处：会明显变

评审时只需要判断这七件事（其余都只是近似替换）：

| # | 变化 | 从 → 到 |
|---|---|---|
| 1 | **主色** | 荧光粉 `#FF2C55` → 朱砂 `#C93C22`（深色 `#FF9370`） |
| 2 | **渐变全部取消** | `gradientHeart` / `gradientSystem` / `heartSweep` → 实色 + `emberGlow` |
| 3 | **页面底色** | 冷灰 `#F6F7FB` → 暖纸 `#FBF7F3` |
| 4 | **页面水平内边距** | `16` → `20` |
| 5 | **标题字族与字号** | Space Grotesk 20px → **Fraunces 衬线 24px** |
| 6 | **正文行高** | `1.45` → `1.55` |
| 7 | **动效体系** | duration + curve → spring（手感会整体变「软」） |

### 18.2 色彩

| 旧 token | 旧值（浅 / 深） | 新 token | 新值（浅 / 深） |
|---|---|---|---|
| `brand` | `#FF2C55` / `#FF2C55` | `brand.default` | `#C93C22` / `#FF9370` |
| `bgPage` | `#F6F7FB` / `#0E1015` | `surface.page` | `#FBF7F3` / `#14110F` |
| `bgCard` | `#FFFFFF` / `#171A21` | `surface.card` | `#FFFFFF` / `#1E1916` |
| `divider` | `#EEF0F4` / `#262A33` | `border.divider` | `#EDE6DF` / `#2E2723` |
| `text1` | `#16181D` / `#F2F4F8` | `text.primary` | `#1C1714` / `#F6F1EB` |
| `text2` | `#8A8F9E` / `#9BA1AE` | `text.secondary` | `#6A5F55` / `#C4B9AD` |
| `text3` | `#B3B7C0` / `#6E7482` | `text.tertiary` | `#8F8478` / `#A39789` |
| `green` | `#12C48B` / `#22D89B` | `status.success` | `#10784A` / `#4FD69A` |
| `amber` | `#FFB020` / `#FFC04D` | `status.warning` | `#8A5F00` / `#FFC152` |
| `danger` | `#FA5151` / `#FF6B6B` | `status.danger` | `#A81E3C` / `#FF8FA3` |
| `violet` | `#7C5CFF` / `#8E72FF` | `status.info` | `#54409E` / `#B3A5FF` |
| `photoScrim` | `rgba(16,17,20,.87)` 两模式相同 | `overlay.scrim` | `#1C1714EB` / `#000000EB` |

**注意两处语义合并**（迁移时不要硬凑一对一）：

- `heartOrange #FF7A45` 只服务渐变终点 → **删除**。若某处确实要「第二个暖色强调」，用
  `accent.default`（`#B4610C` / `#FFC38F`），一个屏最多一处。
- `systemBlue #4F8CFF` 只服务「系统」渐变 → **删除**。系统 / 官方标识统一用 `status.info` 单色。

### 18.3 间距与圆角

| 旧 | 新 | 说明 |
|---|---|---|
| `space-xs/sm/md/lg` = 4/8/12/16 | `space.4/8/12/16` | 同名同值 |
| `space-xl` = 20 | `space.20` | |
| `space-xxl` = 24 | `space.24` | |
| （无） | `space.32` / `space.40` | 新增，供大区块留白 |
| `space-page-h` = 16 | `space.20` | **视觉变化** |
| `space-card-gap` = 12 | `space.12` | |
| `space-section-gap` = 24 | `space.24` | |
| `radius-card` / `radius-discovery-card` / `radius-sheet` = 20/24/24 | `radius.lg` / `radius.xl` / `radius.xl` | |
| `radius-input` = 16 | `radius.md` | |
| `radius-image` = 12 | `radius.sm` | |
| `radius-chip` = 8 | `radius.xs` | |
| `radius-bubble` = 18 | `radius.md` = 16 | **视觉变化**（气泡略方） |
| `radius-full` = 999 | `radius.pill` | |

### 18.4 字阶与字重

| 旧 | 新 | 说明 |
|---|---|---|
| `display` 32 / w800 | `font.size.display` 32 / w700，字族 **Fraunces** | 尺寸不变，字族与字重变 |
| `title` 20 / w700 | `font.size.title` **24** / w600，Fraunces | **+4px** |
| `subtitle` 16 / w600 | `font.size.subtitle` **17** / w600 | +1px |
| `body` 15 / w400–500 | `font.size.body` 15 / w400 | 行高 1.45 → **1.55** |
| `caption` 13 | `font.size.caption` 13 | |
| `micro` 12 / `badge` 11 | `font.size.micro` **11** | 两档合一，取更小的 11 |
| `weight-extrabold` 800 | 无 | Fraunces 没有 800 时退到最粗可用字重，不做假粗体 |
| `leading-tight` 1.2 | `display` 1.15 / `title` 1.25 | 按档位分开 |
| `text-emoji` 72 | 不入 token | 空态插图按 §8.2 的 72–96 取 |

### 18.5 动效与阴影

| 旧 | 新 |
|---|---|
| `motion-fast` 150ms / `base` 220ms / `medium` 320ms / `hero` 380ms | `spring.fast` / `spring.standard` / `spring.standard` / `spring.gentle` —— **没有一一对应**，按 §7.1 的「有位移用 spatial、只有透明度用 effects」重新选 |
| `cinematic` 1200ms（配对编排） | 保留为编排总时长，但每段过渡改用 `spring.gentle`，总长 900–1400ms |
| `easeOutCubic` / `easeOutBack` | **删除**，不再有 curve 常量 |
| reduced-motion 200ms 淡入 | **120ms** 线性淡入（`motion.reducedDurationMs`） |
| `shadow-card` `0 6px 18px rgba(22,24,29,.06)` | `elevation.1` `0 2px 8px rgba(28,23,20,.06)` |
| `shadow-floating-bar` `0 10px 24px rgba(22,24,29,.10)` | `elevation.2`（同结构，暖色阴影） |
| `shadow-primary-button`（粉色投影） | **`emberGlow`**（径向光晕，不是 box-shadow） |
| 深色模式仍用阴影 | **深色不用阴影**，改 `border.divider` + 表面色差（§5.3） |

### 18.6 Web 专属派生色：**目前没有对应物，不要自己造**

`web/src/styles/tokens.css` 里有一批「派生色」，新规范**尚未定义**（规范只管到 §3.3 那二十项）。
E-3 接线时按这个口径处理，任何一种都不允许在页面里写裸 `rgb()`：

| 旧变量 | 处理 |
|---|---|
| `--color-focus-ring` | 改用 §8.4 的焦点环口径：2px `brand.default` + 2px 间隙 |
| `--hover-overlay` / `--hover-overlay-strong` | 暂用 `surface.sunken`；若确认要半透明叠加，按 §11.1 加 token（不许页面内联） |
| `--focus-glow` | 用 `brand.default` @12% 的 token 值（当前由组件层算，不入 token） |
| `--tint-brand` | 同上（brand @8%） |
| `--glow-online` | `status.success` + 呼吸动画（§8.2 头像行） |
| `--overlay-on-photo` | 保留语义，作为照片叠字专用 token 候选，E-3 决定是否入 `design/tokens` |
| `--scrim-strong` | `overlay.scrim` 的不透明度变体（当前先复用 `overlay.scrim`） |
| `--sidebar-*` / `--chatlist-*` / `--feed-card-max` / `--form-card-*` / `--bubble-max-ratio` | **保留**：是布局比例，不是视觉 token，不进 `design/tokens` |
