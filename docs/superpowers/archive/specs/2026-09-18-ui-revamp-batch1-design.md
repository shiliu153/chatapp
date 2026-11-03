# UI 整改批次①:底座 + 底栏(设计)

日期:2026-09-18 · 状态:设计已获用户批准(2026-09-18),本文件待用户终审
上游:「心跳」设计规则 v1 `2026-09-15-ui-design-language-design.md`(**常驻规则,一切视觉细节以它为准,本文件不重复抄录**);立项粒度:一批一立项(用户选 A)

## 背景与目标

「心跳」规则(2026-09-15)已定稿,但 App 尚未整改:全局仍是 Material 默认粉(`app.dart` 里 `colorSchemeSeed: Colors.pink`)、页面散落旧硬编码色值、底栏是 Material `NavigationBar`。本批执行规则 §8 实施顺序的 **① 底座(tokens/theme/widgets)+ 底栏 shell**,路线:方案一「一步到位」(用户选 1)。

批次完成后:全局字体/主题/底栏即新版;四个主页面与二级页内部布局维持旧样,由各自批次整改(**过渡态已与用户确认接受**)。

## 交付物

### 1) `app/lib/core/theme/`(新增 8 文件)

| 文件 | 内容(对应规则章节) |
|---|---|
| `app_colors.dart` | §2.1 全部色值常量 `AppColors.xxx` |
| `app_gradients.dart` | `AppGradients.heart`(135°, #FF2C55→#FF7A45)、`AppGradients.system`(135°, #7C5CFF→#4F8CFF) |
| `app_typography.dart` | §3.2 六档字阶为命名 TextStyle 常量 `AppText.xxx`(display 32/w800、title 20/w700、subtitle 16/w600、body 15/w500、caption 13/w400、micro 12/w400;角标专用 11/w700) |
| `app_spacing.dart` | §5.1 间距:4/8/12/16/20/24;页面水平 16、卡间 12、区块 24 |
| `app_radius.dart` | §5.1 圆角:大卡 20、次级容器 16、小标签 8、弹层 24、全圆 |
| `app_motion.dart` | §6.1 五档(fast 150 / base 220 / medium 320 / hero 380 / cinematic 900–1400)+ 曲线常量 |
| `app_shadows.dart` | §5.1 三档:浮卡 / 悬浮底栏 / 主按钮 |
| `app_theme.dart` | `buildAppTheme()`:colorScheme 从 `brand` 派生(fromSeed);textTheme 接入 AppText;全局 `fontFamily: 'SpaceGrotesk'` + `fontFamilyFallback: ['PingFang SC','MiSans','HarmonyOS Sans','sans-serif']`;`scaffoldBackgroundColor = bgPage`;SnackBar 主题贴近 §7 Toast(深色浮层 rgba(22,24,29,.92)、R16、白字 13);输入框等组件主题按 §7 |

### 2) `app/lib/core/widgets/`(新增 8 组件)

| 组件 | 职责(按 §7 组件规范) |
|---|---|
| `AppButton` | 主/次/文字/危险四型;高 52;按压 scale .96;禁用态 |
| `AppAvatar` | 圆形;尺寸档 28/32/40/48/56/96;可选光晕环(gradientHeart 2.5px)与在线点(11,green 呼吸) |
| `AppBadge` | gradientHeart 渐变角标;min 18×18 R9;11/w700 白;≥100 显示「99+」 |
| `AppCard` | 白底 R20 内边距 16;浮卡阴影;可选 onTap 按压 scale .98 |
| `GradientIcon` | ShaderMask 渐变着色图标 |
| `AppSkeleton` | 呼吸骨架块(divider 色,透明度 .5↔1,1.2s 循环) |
| `AppEmptyState` | 大号彩色元素 + 标题 17/w600 + 说明 13 `text2` + 可选主按钮 |
| `AppToast` | 深色浮层 Toast(底栏上方 12;淡入+上移 8px;2s 消失) |

本批只交付组件本身 + 组件级测试,**不迁移任何页面对它们的既有用法**(页面批次执行)。

### 3) 字体资源

- 下载至 `app/assets/fonts/`:`SpaceGrotesk-{Regular,Medium,Bold}.ttf` + `OFL.txt`
- 来源(2026-09-18 已验证 200):`https://cdn.jsdelivr.net/gh/floriankarsten/space-grotesk@master/fonts/ttf/static/SpaceGrotesk-{Regular,Medium,Bold}.ttf` 与同仓 `OFL.txt`
- `pubspec.yaml`:声明 `family: SpaceGrotesk`(weight 400/500/700);assets 含 OFL.txt

### 4) 全局接入与底栏

- `app.dart`:`buildAppTheme()` 替换 `ThemeData(colorSchemeSeed: Colors.pink)`。
- `home_shell.dart`:Material `NavigationBar` → 自绘 `AppBottomBar`(新文件 `app/lib/features/shell/app_bottom_bar.dart`)。
  - 形态(§7):白底 R22 高 64;左右外距 12、底外距 10;悬浮阴影(§5.1)
  - 未选中:rounded 系描边图标 22、`text3`;文字 10
  - 选中:渐变胶囊(高 40 R20)内白图标 20 + 白字 10/w700;胶囊位移 medium(320ms)+ 图标弹跳 base(220ms)
  - 4 tab(发现/广场/消息/我的),顺序不变
  - 「消息」未读角标用 `AppBadge`(渐变换掉现 Material `Badge.count`);数值来源 `unreadTotalProvider` 不变
  - 尊重 `MediaQuery.disableAnimations`:为真时切换降级为直接跳转
  - 图标字形:取 Flutter `Icons` 中实际存在的 rounded 系(选中填充/未选中描边),以观感统一为准
- 行为零变化:IndexedStack、`banned_heavy` 整屏逻辑、tab 索引语义均不动。

## 关键决策

| 决策 | 结论 | 理由 |
|---|---|---|
| AppBottomBar 槽位 | 仍走 `Scaffold.bottomNavigationBar`,悬浮感靠外边距+圆角+阴影 | 四个页面零改动、风险最小 |
| 测试辅助 `navTab()` | 只改 `harness.dart` 内部 finder(`NavigationBar`→`AppBottomBar`),调用处不动 | 12+ 处 `navTab('消息')` 等全部继续可用 |
| SnackBar | app_theme 主题级统一为深色浮层(贴近 Toast 规范);页面调用代码不动 | 旧页面立刻受益,零迁移成本 |
| 在线点 | `AppAvatar` 内建;现有 `OnlineDot` 保留不动 | 页面批次再统一迁移到 AppAvatar |
| 硬编码清理 | 仅清 `home_shell` 的 `#FF2C55`(§2.3 对应项) | 其余页面硬编码随各自批次清理 |
| AppBottomBar 归属 | `features/shell/` 而非 `core/widgets/` | app 专属组件,非通用 |

## 非目标(本批不做)

- golden 视觉回归(单人开发 + 每批手测验收;Windows 字体渲染不稳,维护成本 > 收益)
- 深色模式(v1 规则明确不做)
- 任何页面内部布局改动;页面级 SnackBar/空态/骨架屏迁移
- 旧视觉专项(微信式聊天/抖音式消息页/微博式广场)不恢复

## 测试与验收

更新(语义不变,仅选择器变化):
- `test/support/harness.dart` 的 `navTab()` finder 改为新底栏类型
- `find.byType(NavigationBar)` → `AppBottomBar`:`home_shell_test.dart`(1 处)、`kicked_offline_test.dart`(2 处)、`login_page_test.dart`(2 处)

新增:
- `AppBottomBar` 行为测试:4 tab 渲染;点击切换(IndexedStack 索引变化);未读角标显隐与数字;`disableAnimations` 下正常切换
- 8 个核心组件的最小组件级测试(渲染 + 关键交互/状态,不测像素)
- `buildAppTheme()` 关键值断言(fontFamily/色板)最小集

门槛(每步全绿再进下一步):
1. `flutter analyze` 零告警
2. 全量 `flutter test` 绿(既有全部用例 + 新增)
3. 模拟器手测(开发侧截图 + 用户亲测):四 tab 切换与动画;消息角标(有/无未读);封禁账号整屏不受影响;四页面可正常进出;字体全局生效(数字/拉丁明显变化);系统「减弱动态效果」开启时无异常

## 风险与观察点

- **过渡态观感**:全局字体切换后个别旧页面可能局部错位/截断——只记录、不修(页面批次处理)。
- **图标字形**:若个别 rounded 字形缺失,用最接近变体并在实现说明中记录。
- **底栏高度变化**(新 64 + 底外距 10 vs 旧 Material 默认高度):页面 body 可用高度略变,预期无害,手测确认。
- **呼吸类动画组件的测试推进**:用有限 `pump` 而非 `pumpAndSettle`(见 `docs/pitfalls/testing.md`)。
- **底栏标签字号取 10**(§7 组件规范),与 §3.3「最小字号 11」的张力按「组件规范优先」处理,不修改规则文档。
