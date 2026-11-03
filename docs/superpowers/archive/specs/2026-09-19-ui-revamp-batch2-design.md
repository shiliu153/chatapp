# UI 整改批次②:发现页(设计)

日期:2026-09-19 · 状态:设计已获用户批准(2026-09-19,浏览器模拟图逐项确认),本文件待用户终审
上游:「心跳」设计规则 v1 `2026-09-15-ui-design-language-design.md`(**常驻规则,一切视觉细节以它为准**);批次①(底座+底栏) `2026-09-18-ui-revamp-batch1-design.md`(已交付,220 测试绿);本批执行实施顺序 **② 发现页**,是首个页面级整改批次,产出可被后续页面批次参照的范式。

## 背景与目标

批次①交付了 token 底座、8 个通用组件与悬浮胶囊底栏,页面内部仍为旧样。本批整改发现页全页(页壳 + 滑卡卡面 + 操作区 + 配对弹层 + 资料未完善引导),**行为零变化,只动视觉层**;模拟图逐项评审已通过(卡面选「沉浸照片版」,操作区选「圆形双钮」,指示点选「胶囊点」,空态选「渐变涟漪」,配对弹层做完整 cinematic)。

## 交付物

### 1) 页壳(`discovery/discovery_page.dart`)

- **去 AppBar**:`SafeArea(top)` + 页面内大标题「发现」(`AppText.display`,32/w800,左对齐),内边距 `EdgeInsets.fromLTRB(16, 16, 16, 12)`(§5.2);标题常驻,状态区在其下方 `Expanded` 内居中。
- **加载统一为卡片骨架屏**:profile 加载与 deck 加载**都**渲染 `DeckSkeleton`(新文件),替换现有两处 `CircularProgressIndicator`。形态:与卡面等大的 R24 呼吸块(`divider` 色,复用 `AppSkeleton` 的呼吸节奏),块内底部叠三条文字骨架条(宽 62%/38%/84%)与两个小标签块,块下两个 44px 圆点(操作钮位置)。
- **错误态统一为一个 `_ErrorView`**(profile 与 deck 复用):标题「没能加载出来」(17/w600)+ `ApiException.message` 原文(非 ApiException 兜底「加载失败,稍后再试」,13 `text2`)+ `AppButton.secondary`「重试」。**不再显示裸异常串**(现为 `'$error'`);「重试」文案不变,两处分别调 `profileProvider.reload()` / `discoveryProvider.reload()`。
- **空态**:`AppEmptyState(mark: HeartRipple())` + 标题「附近暂时没有新的人了」+ 说明「过会儿再来看看吧」+ `AppButton.primary`「刷新」(key `discovery.refresh` 不变)。替换现有灰色 `Icons.people_outline`(规则 §7 禁止灰色图标占位)。
- **资料未完善**:`AppEmptyState(mark: HeartRipple())` + 「完善资料后就能开始滑卡」+「还差:{missing_fields}」+ `AppButton.primary`「去完善」(key `discovery.goOnboarding`,跳 `/onboarding` 不变)。
- 行为不变:presence `track`、`_decide` 回调、配对弹层触发、错误 SnackBar、路由跳转。

### 2) 滑卡卡面(`discovery/widgets/profile_card.dart`)

| 项 | 新规格 | 旧值 |
|---|---|---|
| 圆角 | 24(`AppRadius.discoveryCard`,新增 token) | 16 |
| 名字+年龄 | `AppText.display`(32/w800)白;单 Text,「昵称,年龄」拼接格式不变 | 22/bold |
| 在线 | **8px 呼吸绿点 + 「在线」**(`AppText.micro`,白 88%) | 绿色文本「● 在线」 |
| 离线 | `presenceLabel` 文本(如「5 分钟前在线」),`AppText.caption` 白 72% | 同行白 70% |
| 城市 | `AppText.caption` 白 72% | 白 70% 13px |
| 简介 | `AppText.body` 白 93%,2 行截断 | 白 14px |
| 标签 | `AppText.micro`,白 22% 底、圆角 8、padding 3×8 | 白 24% 底、圆角 12、12px |
| 照片指示 | **胶囊点**:6px 圆点、间距 5、当前张 18×6 R3 胶囊(白/白 45%);key `card.dots` 保留 | 8px 圆点(白/白 38%) |
| 无照片占位 | `AppColors.divider` 底 + `Icons.person_rounded` | `black12` + `person_outline` |
| 照片 scrim | 底渐变 transparent → `AppColors.photoScrim`(新增常量,rgba(16,17,20,.87)) | `Colors.black87` |

不变:左右点击切照片区(56px,key `card.prevPhoto`/`card.nextPhoto`)、单张不显示切换与指示、`didUpdateWidget` 重置逻辑、`ValueKey('card.photo.{id}')`。

### 3) 操作区(`discovery/widgets/swipe_deck.dart`)

- **跳过**:56 圆钮,白底 + 1.5px `divider` 描边,`Icons.close_rounded` 24 `text3`,`AppShadows.card`。
- **喜欢**:64 圆钮,`AppGradients.heart`,`Icons.favorite_rounded` 24 白,`AppShadows.primaryButton`。
- 间距 44;按压 scale .96(`fast`);**点喜欢时脉冲 1→1.25→1**(§6.2,`base`,与飞出动画并行,**不增加点击到飞出的延迟**)。
- 布局:卡组区 `EdgeInsets.fromLTRB(16, 8, 16, 0)`,操作区高 88、底部留白 16。
- 不变:拖拽物理(阈值 0.25、旋转 ±0.3)、飞出时长 250ms、inflight 状态机、key(`deck.topCard`/`discovery.pass`/`discovery.like`)、第二张 0.95 缩放预览。

### 4) 配对情感时刻(`discovery/widgets/match_overlay.dart` + 新增 `match_particles.dart`)

遮罩:深底 `AppColors.text1.withValues(alpha: .94)`(token 派生,不留裸 hex)。

**编排**(单一 `AnimationController`,总时长 ~1100ms,`Interval` 分段):

| 段 | 时间 | 内容 |
|---|---|---|
| 光晕扩散 | 0–550ms | 双头像位置的渐变光晕由小扩大(easeOutCubic) |
| 头像相向 | 150–550ms | 双头像自 ±56px 相向滑入,重叠 ~18px 定格(easeOutCubic) |
| 碰撞爆发 | 500–800ms | 光环 ring 扩散淡出 + 心形 0.6→1.1→1 弹出(easeOutBack) |
| 粒子飘散 | 600–1100ms | 约 24 个 2–5px 粒子自碰撞点向四周飘散渐隐(CustomPainter;色取 brand/orange/white/amber) |
| 文案按钮 | 800–1100ms | 「你们已互相喜欢」+「和 {昵称} 打个招呼吧」+ 两按钮淡入上移 8px |

- 头像:`AppAvatar(96, halo: true)`。
- 完成帧:文案与按钮文案、key(`match.goChat`/`match.continue`)全部不变;「去聊天」= `AppButton.primary`,「继续滑卡」= `AppButton.secondary`。
- **可跳过**:点击任意处 → 直达完成帧(controller 置 1);`MediaQuery.disableAnimations` 为真 → 初始即完成帧。
- **全程无循环动画**(测试 `pumpAndSettle` 的硬约束);`showMatchOverlay` 签名与 `showGeneralDialog` 调用方式不变。

### 5) 通用层改动(`core/`)

| 文件 | 改动 |
|---|---|
| `core/widgets/heart_ripple.dart`(新增) | `HeartRipple({size = 96})`:中心渐变光点带光晕 + **双波循环扩散环**(自光点诞生、0.2→1.0 倍扩散渐隐,2.4s,无静态底环;减弱动效时仅剩光点)——两轮手测反馈定型(先由静态改为动效,再去掉静态底环避免重叠),可见它的测试用有限 `pump`。 |
| `core/widgets/breathing_dot.dart`(新增) | 把批次① `AppAvatar` 私有的 `_BreathingDot` 提炼为共享组件 `BreathingDot({size, borderColor, key})`;AppAvatar 改用它(**`Key('avatar.onlineDot')` 由 AppAvatar 传 key 保持**,现有测试不动);发现卡在线点复用(传 `Key('card.onlineDot')`,白描边 2px,与头像在线点同规格)。 |
| `core/widgets/app_empty_state.dart` | `emoji` 改可空 + 新增 `mark`(Widget?);渲染优先级 mark > emoji;两者皆空时不渲染元素(标题/说明/按钮照常)。现有调用处(emoji)零改动。 |
| `core/theme/app_radius.dart` | +`discoveryCard = 24` |
| `core/theme/app_colors.dart` | +`photoScrim = Color(0xDE101114)`(rgba(16,17,20,.87),照片叠字 scrim;`scrimTop` 直接用 `Colors.transparent`) |

### 6) 「心跳」规则文档回填(§9 边界流程,先于代码)

`2026-09-15-ui-design-language-design.md` 升 **v1.1**,新增「附录 A:发现页落地补充」,记录本批新场景与参数:

- 滑卡操作钮规范(圆形 56/64、图标 24、喜欢=渐变+光晕、跳过=白底描边、脉冲 1→1.25→1、按压 .96)
- 照片 scrim 常量(0xDE101114)与用法(叠字区渐变起点 transparent)
- 涟漪空态元素(HeartRipple 96,静态)
- 照片切换指示:胶囊点(6px / 当前 18px)
- 配对情感时刻编排分段参数与遮罩 94%

## 关键决策

| 决策 | 结论 | 理由 |
|---|---|---|
| 卡面版式 | 沉浸照片版(照片全出血 + 底部 scrim 叠字) | 照片情感冲击最大、改动最小;浏览器评审 A 通过 |
| 操作钮形态 | 圆形双钮(56/64) | 滑卡是 dating app 手势语言,圆钮认知成本为零;胶囊双钮会跟卡片抢视觉重心 |
| 切换指示 | 胶囊点(圆点 + 当前张拉长) | 位置感像圆点、辨识度像分段条;评审通过 |
| 空态元素 | 渐变涟漪(不用爱心/emoji) | 与「心跳光晕」签名一脉相承,避开爱心滥调;Emoji 各机型字形不可控 |
| 配对弹层深度 | 完整 cinematic(含粒子) | §6.2 全片唯一情感时刻;编排骨架两种方案都要写,完整版边际成本仅粒子层 |
| 涟漪动画 | 循环扩散波纹(弹层保持无循环) | 手测反馈:涟漪「不动的」名不副实,加双波循环;测试纪律随之改为有限 `pump`(见 pitfalls/testing.md) |
| BreathingDot 提炼 | 从 AppAvatar 私有类提升为 core 组件 | 发现卡在线点需要同一视觉,避免复制 30 行呼吸逻辑;两处消费,非过早抽象 |
| 距离显示 | 不做 | 后端候选接口无位置字段;模拟图中「距离你 3 公里」为示意,正式版 meta 行仅城市 |
| AppEmptyState 扩展 | 保留 emoji 参数、新增 mark | 其他未改造页面仍用 emoji 形态,零迁移成本 |

## 非目标(本批不做)

- 距离/位置能力(需后端加字段,另立项)
- 其他页面迁移(广场/消息/我的/二级页按顺序后续批次);核心契约、路由、接口零改动
- 任何新功能与交互行为变化;golden 视觉回归;深色模式
- 旧视觉专项(微信式聊天/抖音式消息页/微博式广场)不恢复

## 测试与验收

更新(语义不变,视觉层变化同步选择器/断言):

- `test/features/discovery/profile_card_test.dart`:「在线」用例由 `find.text('● 在线')` 改为断言在线点(byKey `card.onlineDot`)+ `find.text('在线')`;无照片占位断言 `person_outline` → `person_rounded`。离线「x 分钟前在线」「未知不显示」断言不变。
- `test/features/discovery/discovery_page_test.dart`、`swipe_deck_test.dart`、`match_overlay_test.dart`:断言不动的尽量不动;若因动画结构调整需改,只改推进方式(有限 pump),不改断言语义。

新增:

- `HeartRipple`:渲染三环 + 中心点(结构断言);波纹有限推进后不透明度变化;`disableAnimations` 时不渲染波纹。
- `DeckSkeleton`:渲染冒烟(**有限 pump,禁 pumpAndSettle**)。
- 配对弹层:「点击任意处 → 立即出现完成帧(文案 + 按钮)」;「`disableAnimations` → 初始即完成帧」;「正常编排结束后完成帧可见」。
- 卡面:「在线点随 presence 出现/消失」;操作钮:「点击喜欢触发脉冲(峰值 1.25 后回落)」。
- `AppEmptyState`:mark 参数优先于 emoji;两者皆空不崩。

门槛(每步全绿再进下一步):

1. `flutter analyze` 零告警
2. 全量 `flutter test` 绿(既有全部用例 + 更新 + 新增)
3. 模拟器手测(开发侧截图 + 用户亲测,连测试服务器 `http://<SERVER_IP>/api/v1`):四态(骨架/空态/错误/引导);卡面(胶囊点、在线点、标签、叠字对比度);操作钮脉冲;配对编排全流程与点击跳过;系统「减弱动态效果」下直达完成帧;封禁账号整屏不受影响。

## 风险与观察点

- **`find.text('发现')` 双命中**:新增大标题后,页面标题与底栏 tab 文案相同。实现前 grep 现有测试中直接 `find.text('发现')` 的用法,若有则改为范围限定(沿用 `navTab` helper 的 descendant 写法)。
- **无限动画与 `pumpAndSettle`**:卡面在线点为无限呼吸,涉及态(在线)的用例只能有限 `pump`;加载骨架同理。批次① `app_avatar_test` 已有先例,照此执行。
- **照片叠字对比度**:scrim 基于深色,浅色照片下名字区仍有保障;若手测发现极端浅色照片可读性差,只调 `photoScrim` 常量透明度,不动结构。
- **窄屏(360dp)排版**:名字(32/w800)+ 在线点同行在超长昵称下可能换行,手测确认;必要时名字行加 `maxLines: 1 + ellipsis`。
- **配对编排时长与测试**:总时长 ~1100ms 属有限动画,`pumpAndSettle` 可达完成帧;跳过路径需保证 controller 停在终态、无残余帧调度。
- **规则文档先行**:滑卡圆钮/scrim/涟漪/胶囊点属 §9 未覆盖场景,先回填 v1.1 附录再写对应代码。
