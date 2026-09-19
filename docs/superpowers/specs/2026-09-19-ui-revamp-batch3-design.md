# UI 整改批次③:消息页 + 聊天页(设计)

日期:2026-09-19 · 状态:设计已获用户批准(2026-09-19,浏览器模拟图逐项确认)
上游:「心跳」设计规则 v1.1 `2026-09-15-ui-design-language-design.md`(**常驻规则,一切视觉细节以它为准,本文件不重复抄录**);批次①②已交付(220→233 测试绿);本批执行实施顺序 **③ 消息/聊天**。

## 背景与目标

批次①交付 token 底座/组件/底栏、批次②交付发现页。本批整改消息页(会话列表)与聊天页(会话),**行为零变化,只动视觉层**;两处已批准的小例外:去掉聊天顶栏与「点名字」重复的「⋯」按钮;聊天页空态补副文案。浏览器模拟图评审已通过:横滑条保留重制(方案 A)、聊天顶栏两行居中(方案 A)、发送钮纯图标可变色(方案 B)、空态渐变双气泡插画(方案 B)、共享层提炼两项(方案 B)。

## 交付物

### 1) 消息页(`features/chat/chats_page.dart`)

- **页壳**:去旧 `TextStyle(fontSize: 20, bold)` 标题 → `AppText.display`(32/w800)「消息」,`EdgeInsets.fromLTRB(16, 16, 16, 12)`(§5.2 Tab 主页),与发现页同构。
- **加载统一为 `ChatsSkeleton`**(新文件 `features/chat/widgets/chats_skeleton.dart`):IM 连接中与 `conversationsProvider` loading **都**渲染行骨架(约 6 行:48 圆头像块 + 两条文字条,复用 `AppSkeleton` 呼吸节奏),替换现有两处 `CircularProgressIndicator`。
- **错误统一为 `AppErrorView`**(见 §4):标题「没能加载出来」+ 原因(IM 失败取 `ImException.message`;会话拉取失败取 `ApiException.message`,非 ApiException 兜底「加载失败,稍后再试」,**不再显示裸 `'$error'`**)+ `AppButton.secondary`「重试」。两处错误态互斥渲染,retry key 均沿用 `chats.retry`(IM 失败 → `imStatusProvider.notifier.retry()`;会话失败 → `conversationsProvider.notifier.reload()`)。
- **横滑条重制**(保留,`Key('chats.strip')`/`chats.stripItem:{peerId}` 不变):
  - `AppAvatar` 48(新增 `fallbackText`,无图显示昵称首字)+ 在线 `BreathingDot` 11 白描边;名字 `AppText.micro`/`text2`、宽 56 居中截断;高 88、间距 14、水平内边距 16。
  - 保留:`take(10)`、不含系统通知、无会话整条隐藏、点击 `context.push('/chat/{peerId}')`。
- **系统通知行**(`Key('chats.systemNotice')` 不变):圆头像 = `gradientSystem` 渐变底(§2.1 系统/官方专属)+ `Icons.notifications_rounded` 24 白;「官方」标 = violet 描边 1px、10/w500、R8、padding 1×6;标题/预览/时间角标同下。
- **会话行**(`Key('chats.tile:{peerId}')` 不变):高 72;`AppAvatar` 48;名字 `AppText.subtitle`;预览 `AppText.caption`/`text2`;右侧列 = 时间 `AppText.micro`/`text3` + `AppBadge`(渐变角标替换旧红底 `_UnreadBadge`,≥100 自动「99+」);分隔线 `AppColors.divider`。
- **空态**:`AppEmptyState(mark: ChatBubblesMark())` + 「还没有消息」+ 「互相喜欢之后就能开聊了」;替换灰色 `Icons.chat_bubble_outline`(§7 禁止灰色图标占位)。
- 行为不变:presence `track('chats', ids)`、系统通知置顶排序、路由跳转、全部 data key。

### 2) 聊天页(`features/chat/chat_page.dart` + `widgets/`)

- **顶栏**(自绘,不套 Material `AppBar`;`SafeArea(top)` 内高 62——§5.2 二级页 52 的例外,记附录 B):
  - 左:返回 `Icons.arrow_back_ios_new_rounded` 22 `text1`(行为 = 原 `Navigator.pop`);右:无按钮(**删除原 `chat.more`「⋯」**,与点名字重复)。
  - 中:两行居中——名字 17/w600(`AppText.subtitle.copyWith(fontSize: 17)`,key `chat.title` 保留在名字上,点击进 `/users/{id}` 不变);状态行 `AppText.micro`:`presence.online` → `BreathingDot` 8(`Key('chat.onlineDot')`) + 「在线」`text2`;离线 → `presenceLabel` 的「x 分钟前在线」(`text2`);presence 未知 → 不渲染状态行、名字单行居中。**不改 `presenceLabel` 本身**(发现卡与资料页仍消费「● 在线」)。
- **时间条**:`AppText.micro`(12)/`text3`、上下边距 12(§7);key `chat.time` 不变。
- **消息气泡**(`widgets/message_bubble.dart` 重做):
  - 头像:圆形 `AppAvatar` 40(`fallbackText` 首字;废除微信式方头像 `_SquareAvatar`)。
  - 自己:brand 实底白字;对方:白底 `text1`;**R18,靠头像侧上角 6**(替代 R10/下角 2);内边距 12/14;最大宽 `MediaQuery.width * 0.72`(原 0.66);文字 `AppText.body`。
  - 图片消息:140×140、R12(§7 内容图);失败兜底 = `divider` 底 + `Icons.image_rounded` `text3`。
  - 发送失败:`Icons.error_rounded` 20 `danger`(key `chat.retry` 不变);pending 透明 .6 不变。
  - notice(配对/封禁,key `chat.notice` 不变):居中 pill = `divider` 底、`text2` 字、全圆角、padding 6×12、`AppText.micro`;文本不变。
- **输入栏**(`_InputBar`):
  - 输入框:高 44(聊天场景对 §7「输入框 52」的例外,记附录 B;手测反馈由 40 上调)、R16、1px `divider` 描边、聚焦 1.5px `brand` + 光晕;hint「说点什么…」、key `chat.input`、发送键/onSubmitted 行为全不变。
  - 图标:`emoji_emotions_rounded` 24 `text2`(key `chat.emoji.button`)、`add_circle_rounded` 24 `text2`(key `chat.more.button`)。
  - **发送钮**:纯图标 `send_rounded` 24(无底),输入为空 `text3`、有字 `brand`;仍始终可点、空发无效(行为不变);key `chat.send` 不变。
- **面板**:`emoji_panel.dart` / `more_panel.dart` 改白底 + 顶部分隔线(1px `divider`);表情面板高 220、8 列不变,emoji 24 不变;＋面板高 160 不变,「相册」块 = 56 R16、`brand` 12% 透明底、`photo_library_rounded` 26 `brand`、标签 `AppText.micro`/`text2`;切换逻辑与 key 全不变。
- **空态**:`AppEmptyState(mark: ChatBubblesMark())` + 「打个招呼吧」+ 「发条消息,开始你们的故事」(副文案为已批准新增)。
- **加载**:`ChatSkeleton`(新文件 `features/chat/widgets/chat_skeleton.dart`,约 4 行左右交错的气泡骨架块 + 头像圆块,`AppSkeleton` 呼吸节奏),替换 `CircularProgressIndicator`。
- **错误**:`AppErrorView` + 「重试」→ `ref.invalidate(chatProvider(peerId))`(已批准的小行为新增:此前错误态是死路,无任何可操作项)。

### 3) 新组件

| 文件 | 内容 |
|---|---|
| `features/chat/widgets/chat_bubbles_mark.dart`(新增) | `ChatBubblesMark({size = 118})`:渐变大气泡(`gradientHeart`)+ 白色小气泡(错落叠放,各带小尾巴),静态 CustomPaint;用于消息页与聊天页空态 |
| `features/chat/widgets/chats_skeleton.dart`(新增) | 消息页行骨架(见 §1) |
| `features/chat/widgets/chat_skeleton.dart`(新增) | 聊天页气泡骨架(见 §2) |

### 4) 共享层改动(`core/`)

| 文件 | 改动 |
|---|---|
| `core/widgets/app_error_view.dart`(新增) | `AppErrorView({title = '没能加载出来', required message, onRetry, retryKey})`:标题 17/w600 + 消息 13 `text2` 居中 + `AppButton.secondary`「重试」(可选) |
| `core/widgets/app_avatar.dart` | +`fallbackText`(String?):无图且非空时,占位改「首字 + 柔色底」——底为 `brand`/`violet`/`green`/`amber` 各 12% 透明度、按名字内容稳定映射;字色 `text1`;为 null 时保持现「divider 底 + person 图标」(零回归) |
| `features/discovery/discovery_page.dart` | 删除私有 `_ErrorView`,换用 `AppErrorView`(文案/行为/两个重试入口不变) |

### 5) 「心跳」规则文档回填(§9 边界流程,先于代码)

`2026-09-15-ui-design-language-design.md` 升 **v1.2**,新增「附录 B:消息/聊天页落地补充」:

- **B.1 最近联系人横滑条**:高 88;头像 48(首字占位 + 在线呼吸点 11 白描边);名字 12/`text2` 截断;间距 14;无会话整条隐藏
- **B.2 聊天页顶栏**:高 **62**(§5.2 二级页 52 的例外);返回 22 `text1`;标题两行居中(名字 17/w600 + 状态行 12;在线 = 8 绿点 +「在线」,离线 = 「x 分钟前在线」,未知不显示);无右侧按钮
- **B.3 聊天气泡**:自己 brand 实底白字 / 对方白底 `text1`;R18 + 靠头像侧上角 6;内边距 12/14;最大宽 **72%**;头像 40 圆形;图片 140×140 R12;失败 = `error_rounded` 20 `danger`
- **B.4 聊天输入栏**:布局 `[表情] [输入框] [＋] [发送]`(表情在输入框左侧),四元素同为 44 方块同高对齐;输入框高 **44**(§7 输入框 52 的聊天场景例外)、R16、1px `divider`、聚焦 1.5px `brand` + 光晕;发送 = 纯图标 24(空 `text3` → 有字 `brand`);emoji/＋ = rounded 24 `text2`
- **B.5 时间条与灰条**:时间条 12 `text3` 上下 12;灰条(配对/封禁)= `divider` 底 + `text2` + 全圆 + 6×12
- **B.6 空态插画「渐变双气泡」**(ChatBubblesMark):≈118,渐变大气泡 + 白色小气泡 + 双小尾,静态;消息/聊天空态默认
- **B.7 系统通知行**:圆头像 `gradientSystem` + 白铃铛 24;「官方」标 = `violet` 描边、10/w500、R8
- **B.8 头像首字占位**:柔色底(4 色 token 12% 透明度,按名字稳定映射)+ 首字 `text1`

## 关键决策

| 决策 | 结论 | 理由 |
|---|---|---|
| 横滑条去留 | 保留,按「心跳」重制 | 用户选 A:保留「快速回到最近聊过的人」入口;去掉会丢已有能力 |
| 聊天顶栏 | 两行居中(高 62) | 用户选 A:在线状态是产品招牌信息,不想丢;两行给状态留足空间 |
| 发送钮 | 纯图标,有字变 brand | 用户选 B:聊天页已有气泡高音,发送保持克制 |
| 空态元素 | 渐变双气泡插画(新增) | 用户选 B:消息语义直白;HeartRipple 留给发现页,避免签名元素滥化 |
| 顶栏「⋯」 | 删除 | 与「点名字进资料页」完全重复 |
| 共享层 | 提炼 `AppErrorView` + `AppAvatar.fallbackText` | 用户选 B:错误态已到第三份拷贝、头像首字是消息列表观感基础;第三份时提炼 |
| 聊天错误态 | 新增「重试(invalidate)」 | 原为死路,无任何可操作项;小行为新增,随本批批准 |

## 非目标(本批不做)

- 看大图页 `photo_viewer`(聊天/资料共用,留 ⑥ 二级页);长按菜单样式(系统 `showMenu`,留后续统一)
- 广场(⑤)/我的+资料(④)/二级页(⑥)的整改;任何其他行为/路由/接口变化;golden 视觉回归;深色模式
- `presenceLabel` 文案本身不动(发现卡/资料页继续用「● 在线」)

## 测试与验收

更新(语义不变,选择器/断言随视觉调整):

- `test/features/chat/chats_page_test.dart`:在线点断言 `find.byType(OnlineDot)` → `BreathingDot`(2 处);其余(昵称 ×2、预览、未读 ×2、系统通知置顶与「官方」、空态、跳转、presence 查询)全部不动。
- `test/features/chat/chat_page_test.dart`:在线用例 `find.text('● 在线')` → 断言 `Key('chat.onlineDot')` + `find.text('在线')`;离线/未知/缓存为空等用例不动。确认无用例引用被删的 `chat.more`「⋯」。
- `test/features/discovery/*`:发现页换 `AppErrorView` 后重试用例(byKey/key 或文案)保持通过。

新增:

- `ChatBubblesMark` 渲染冒烟(结构存在);消息页骨架、聊天页骨架(**有限 pump,禁 pumpAndSettle**)。
- 聊天页:`disableAnimations` 无关;错误态显示重试且点击后触发 `chatProvider` 重新拉取(fake 断言 fetchHistory 次数)。
- `AppEmptyState` 已覆盖 mark 优先;`AppAvatar.fallbackText`:无图显示首字、有图不显示首字、默认(不传)仍为 person 图标。
- `AppErrorView`:渲染标题/消息/重试回调。

门槛(每步全绿再进下一步):

1. `flutter analyze` 零告警
2. 全量 `flutter test` 绿(233 既有 + 更新 + 新增)
3. 模拟器手测(用户亲测,连测试服务器):消息页四态(骨架/空态/错误/正常)、横滑条与在线点、系统通知行、未读角标;聊天页顶栏(在线/离线/未知)、气泡与灰条、输入栏三态(空/有字/发送)、表情与＋面板、图片消息与长按菜单、发送失败重发;系统「减弱动态效果」下无异常;封禁账号整屏不受影响

## 风险与观察点

- **`find.text('消息')` 双命中**:新增大标题后与底栏 tab 文案相同;实现前 grep 测试中裸 `find.text('消息')`,有则范围限定(沿用 `navTab` helper 思路)。
- **无限动画与 `pumpAndSettle`**:骨架屏、在线呼吸点均为无限循环;涉及的用例一律有限 `pump`(见 `docs/pitfalls/testing.md`,批次②已有先例)。
- **`OnlineDot` 仍有其他消费方**(广场 `post_card`,批次⑤才改),本批只迁移 `chats_page`,不删组件。
- **头像首字取色稳定性**:按名字内容映射(不依赖 `hashCode` 跨版本稳定性,如 codeUnits 求和取模),保证同一人始终同色。
- **顶栏 62 / 输入框 44 与规则正文的数值差异**:均属 §9 边界,先回填附录 B 再写代码。
- **发送钮变色依赖输入状态**:包 `ValueListenableBuilder(_input)` 即可,不得改变「始终可点、空发无效」的行为与 key。
- **窄屏(360dp)**:横滑条 10 人与顶栏两行在长昵称下的表现,手测确认;必要时名字行 `maxLines: 1 + ellipsis`。
