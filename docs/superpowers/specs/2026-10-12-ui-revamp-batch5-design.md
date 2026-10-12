# UI 整改批次⑤:广场(设计)

日期:2026-10-12 · 状态:设计已获用户批准(逐节确认);spec 自审后修正 4 处(见文末「自审更正记录」);整卡 Hero 机制经实现前 SDK 核查修正(§5,用户确认「状态切换双保」)
上游:「心跳」设计规则 `2026-09-15-ui-design-language-design.md`(**常驻规则,一切视觉细节以它为准,本文件不重复抄录**);批次①②③④已交付(278 测试绿);本批执行实施顺序 **⑤ 广场**。

## 背景与目标

批次④交付后,四个 Tab 主页只剩「广场」仍是微博式旧版式:`AppBar` 系统标题、`#F7F3F5` 旧页底、方形头像(40 R6)、九宫格 R6/间距 4、灰字空态、裸 `SnackBar`,全页约 20 处裸硬编码。动态详情页(`AppBar` + 方形评论头像 28 R4)与我的动态页同样停在旧形态。

本批整改这三个页面,**并落地 §6.2 点名的第二处 Hero 转场「动态卡 → 动态详情」**(批次④只做了「头像 → 他人资料页」那一路)。

**范围界定**(用户已确认):

- **本批做「看」的部分**:广场 Tab(`square_page.dart`)、动态详情(`post_detail_page.dart`)、我的动态(`my_posts_page.dart`)、共用层 `widgets/post_card.dart`、`widgets/post_images.dart`、`post_actions.dart`(仅提示通道换 Toast)。
- **发动态页(`post_compose_page.dart`)不动**,留批次⑥——它是表单页,与编辑资料/设置/登录/引导一起按统一表单控件规范改,避免返工(沿用批次④把「编辑」留给⑥的先例)。

## 已定关键决策(用户确认)

| 决策点 | 结论 | 落选理由 |
|---|---|---|
| 信息流形态 | **单列卡片流**(微博/朋友圈式密度) | 双列瀑布流把九宫格/长文压成封面图,需新写流式布局与高度预估,复杂度和测试量翻倍;混合流版式不统一 |
| 整卡 Hero | **做**,整卡飞到详情 | 仅图片 Hero 需重排详情页且长文无图可飞;不做则规则点名的转场继续欠着 |
| 发动态页 | 留批次⑥ | 表单页,⑥统一表单控件规范一次定 |

## 交付物

### 1) 广场页(`features/square/square_page.dart`)

- **页壳**(与发现页/消息页同构,§5.2):去 `AppBar` → `SafeArea(bottom: false)` + `Column`:顶部大标题「广场」`AppText.display`(32/w800,`text1`),内边距 `EdgeInsets.fromLTRB(AppSpacing.pageH, AppSpacing.lg, AppSpacing.pageH, AppSpacing.md)`;`Expanded` 包内容;底色 `bgPage`(替换 `#F7F3F5`)。
- **FAB 改样式**:渐变圆钮 56(`gradientHeart` 底 + `add_rounded` 白 24 + 主按钮阴影 `AppShadows.primaryButton`),key `square.fab` 与 `/posts/compose` 跳转不变。它是本页唯一渐变高音,引导视线到「发动态」。
- **列表**:白卡流,水平外边距 `AppSpacing.pageH`、卡间 `AppSpacing.cardGap`;`ListView` 的 `padding.bottom` 预留 **96**(悬浮底栏 64+10 上方留量)。
- **空态** → `AppEmptyState` + `HeartRipple`(附录 A.3 空态大号元素,「心跳在找、暂时没有回音」语义适用于空广场)+ 标题「还没有动态」+ 说明「发一条,让大家认识你」+ 次按钮「发布第一条」(key `square.compose`,→ `/posts/compose`)。**文案从「还没有动态,发一条吧」改掉**;HeartRipple 是无限动画,受影响测试改有限推进(见「既有断言与测试适配」A)。
- **加载** → 新组件 `SquareSkeleton`(`widgets/square_skeleton.dart`):3 张卡骨架(圆头像块 40 + 两条文字条 + 图片块 + 操作行条),复用 `AppSkeleton` 呼吸节奏,key `square.skeleton`。
- **错误** → `AppErrorView`(key `square.retry`,原因取 `apiMessageOf(error)`,重试 = `ref.invalidate(squareProvider)`),替换裸文本 + FilledButton。
- **提示通道**:页内 `SnackBar` 全部换 `AppToast`(规则 §7 组件;含点赞失败/删除成功提示;`AppToast` 已有组件与单测,广场系是首个页面接入)。`post_actions.dart` 的举报成功/失败提示同步换 `AppToast`(广场/详情/我的动态三页共用,全在本批范围内);**删除确认 `AlertDialog` 保持不动**(通用弹窗,留给⑥统一)。
- **刷新指示器**:保留 `RefreshIndicator`,`backgroundColor: AppColors.bgCard`、`color: AppColors.brand`。
- 行为不变:分页加载(loadMore 触发逻辑)、`presenceProvider.track('square', …)`、拉黑/封禁遮罩(在 home_shell 层)。

### 2) 动态卡(`widgets/post_card.dart`,重构)

- **卡体**:`AppCard`(白底 R20、内边距 16、按压 scale .98);整卡可点进详情(onTap 保持现状)。
- **头像**:`AppAvatar` **40 圆形**(`fallbackText: nickname`,附录 B.7 首字占位)+ `showOnlineDot`(替换现 40 **方形** R6 自绘 `_Avatar`;内部在线点是 `BreathingDot` 呼吸点——§5.3「在线点 = green + 呼吸光晕」的正统实现,与消息页一致);删除 `_Avatar` 私有类与 `OnlineDot` 依赖;**全仓不再有 `OnlineDot` 引用 → 删除该类**(顺带清掉其裸 hex `#34C759`,§2.1 green 应为 `#12C48B` 的违规残留)。
- **文字**:昵称 `AppText.subtitle`(16/w600);时间 `AppText.micro`/`text3`;正文 `AppText.body`(15) `text1`。
- **九宫格 `PostImages`**(`widgets/post_images.dart`,重构):
  - 1 张 = 通栏大图:宽撑满卡内、**固定高 240**,`BoxFit.cover`,R12;
  - 2–9 张 = 统一 **3 列**方格,间距 `AppSpacing.sm`(8),R12,每格 `AspectRatio(1)` 正方;2–4 张不再两列混排(与微信九宫格行为一致,卡高更可预测);
  - 图加载失败 → `divider` 底 + `image_rounded`(`text3`,内容占位非空态,同发现卡 person 处理)。
  - key `post.image.{i}` 保留。
- **操作行**:点赞 `favorite_rounded` / `favorite_border_rounded` 20(已赞 `brand`,未赞 `text3`)+ 计数 `AppText.caption`/`text3`;评论 `mode_comment_outlined` 同规格。**点首次赞加心跳脉冲 1→1.25→1(`AppMotion.base`,§6.2 微交互)**——取消赞不脉冲。
- **`···` 菜单**:图标换 `more_horiz_rounded`(20,`text3`);菜单项、key、行为全不变。
- **key 契约全保留**:`post.card.{id}` / `post.avatar.{id}` / `post.nickname.{id}` / `post.like.{id}` / `post.more.{id}` / `post.menu.delete` / `post.menu.report` / `post.image.{i}`。

### 3) 动态详情页(`post_detail_page.dart`)

- **顶栏**(自绘,不套 Material `AppBar`):`SafeArea` 内高 52(§5.2 二级页);返回 `arrow_back_ios_new_rounded` 22 `text1`(key `post.back` 新增,`context.pop()`);标题「动态详情」17/w600 `text1` 居中。
- **正文区**:顶部动态卡与列表卡同构(同组件同参数),白卡流(水平外边距 16);评论区行嵌在卡下方。
- **评论行**(`_CommentTile`):头像 `AppAvatar` **28 圆形** + `fallbackText`(替换方形 R4 自绘);昵称 13/w600 `text2`;正文 `AppText.body`/`text1`;时间 `AppText.micro`/`text3`;行间 1px `divider`。评论区**不带在线点**(踩坑册口径:在线点只在广场作者头像)。
- **空态**:「还没有评论」灰字 → `AppEmptyState` emoji(`💬`)+ 说明「来抢沙发」;无按钮。
- **底部输入栏**:白底 + 顶部 1px `divider`;输入框 R16、1px `divider` 描边、聚焦 1.5px `brand` + 光晕 `rgba(255,44,85,.12)`(附录 B.4 同源);高 **44**(附录 B.4 聊天场景 44 例外的**延伸**——「紧凑输入场景 44」,回填附录 D);发送 = 纯图标 `send_rounded` 24:空文字 `text3`、有字 `brand`(B.4 同款)。key `post.comment.input` / `post.comment.send` 保留。
- **加载** → 新组件 `PostDetailSkeleton`(`widgets/post_detail_skeleton.dart`:动态卡骨架 + 2 条评论行骨架,key `post.skeleton`);**错误** → `AppErrorView`(key `post.retry`;既有「动态不存在」测试断言的是错误文案本身,`AppErrorView` 照常渲染 message,不受影响)。
- **SnackBar → AppToast**(评论失败/删除提示)。

### 4) 我的动态页(`my_posts_page.dart`)

- 顶栏:同详情页规格(返回 key `myPosts.back` + 「我的动态」标题居中)。
- 列表复用改版后 `PostCard`(heroTag 传 null,不参与 Hero——从我的页进来无飞行源)。
- 空态 → `AppEmptyState` + emoji(`📝`)+「还没发过动态」文案**保留** + 次按钮「去发布」→ `/posts/compose`(**行为新增**:原空态无动作;既有测试只断言文案,不断言无按钮,零断言改动)。
- 加载 → 复用 `SquareSkeleton`(key `myPosts.skeleton` 独立,避免 IndexedStack/栈下共存时 `findsOneWidget` 撞 key);错误 → `AppErrorView`(key `myPosts.retry`);SnackBar → `AppToast`。

### 5) 整卡 Hero(§6.2 第二处转场;机制经实现前核查修正)

**两个 SDK 硬约束(实现前核查 `flutter/packages/flutter/lib/src/widgets/heroes.dart` 得出,设计定稿时不知道):**

1. **Hero 不可嵌套**(`heroes.dart:412` 运行时断言 `A Hero widget cannot be the descendant of another Hero widget.`):整卡 Hero 包在卡外、卡内头像 Hero 在其内 → debug 直接崩。**同一张卡同一时刻只能有一个 Hero**。
2. **扫描时机只此一次**(`heroes.dart:961-973`):push 后仅在**下一帧末**扫描一次目标路由找配对 Hero;`postDetailProvider` 是 autoDispose,详情页首帧必然是骨架屏 → 目标侧没有 Hero → **push 不会飞**。

**修正后的机制(用户确认「状态切换双保」):**

- **点卡身时状态切换**:广场页维护 `_cardHeroPostId`(当前处于整卡 Hero 态的动态 id)。点卡 → `setState` 把该卡切到整卡态(**头像 Hero 让位**:卡内 `heroTag` 传 null、卡外套 `CardHero`)→ `await context.push('/posts/{id}', extra: PostDetailArgs(...))` → pop 完成后 `finally` 还原普通态(头像 Hero 回归)。飞行源四处(批次④三处头像 + 本批整卡)全部保留。
- **extra 携带 seed**:`PostDetailArgs { String heroTag; Post seed }` 经 go_router `extra` 传入;详情页在 provider 仍 loading 且有 seed 时**直接用 seed 渲染真卡**(首帧即有带相同 tag 的 `CardHero`)→ push 必飞;fetch 完成后切到服务器数据(内容一致)。深链/我的动态进入 `extra == null` → 无 Hero、骨架起步(附录 C.7 同款纪律)。
- **Hero 互斥不变式**(每张卡任意时刻至多一个 Hero):
  - 广场列表普通态:`PostCard(heroTag: 'avatar-post-{id}', cardHeroTag: null)`;
  - 广场列表整卡态(仅其详情在栈顶期间):`PostCard(heroTag: null, cardHeroTag: 'card-post-{id}')`;
  - 详情页顶卡:`CardHero(tag: heroCardTag)` 内 `PostCard(heroTag: null)`(**必须 null**,否则嵌套断言崩);
  - 我的动态/深链:两端都无 Hero。
- **新组件 `CardHero`**(`core/widgets/card_hero.dart`):与 `AvatarHero` 并列(参数 `tag` / `child`),`tag == null` 或 `MediaQuery.disableAnimationsOf` → 直接返回 child;shuttle 用 Hero 默认实现(飞行中渲染目标侧 child = seed 真卡,位置/尺寸由框架插值)——两端同为 R20 白卡、同水平边距,无需 `AvatarHero` 那样的圆角插值。
- **快速连点防护**:`_openDetail` 入口 `if (_cardHeroPostId != null) return;`(整卡态进行中忽略新点击,避免飞行中卸载 Hero)。
- tag 规约:`card-post-{postId}`(**不用** `card-post-{userId}`,同作者多卡会同屏重复,理由同 C.7);详情页顶栏返回键行为不变(`context.pop()`),pop 飞行由同一对 tag 自动反向发生。

### 6) 顺手清理(§2.3 对照表)

`#F7F3F5` ×3 页、`#999999` / `#C9CDD4` / `#FF2C55` / `#EFE3E7` / `#BBBBBB` / `#34C759`(随 OnlineDot 删除)等广场系约 20 处裸硬编码全部换 token 或删除;新代码零裸 hex / 裸字号 / 裸间距 / 裸圆角;确需新值在组件内定义具名常量并注明附录条款。

## 不做(Non-goals)

- 发动态页(`post_compose_page.dart`)改版 → 批次⑥;
- 删除确认 `AlertDialog` 重绘 → 批次⑥(通用弹窗,不单广场用);
- 后端接口、数据模型、provider 结构、路由路径 → 零变化;
- 详情页评论加在线点(口径不变)、深色模式、golden 测试、卡片手势。

## 既有断言与测试适配(本批全部影响面,自审后核定)

**改断言(4 组)**:

| # | 位置 | 现状 → 改后 | 原因 |
|---|---|---|---|
| A | `square_page_test.dart:48`、`home_shell_test.dart:35` | 「还没有动态,发一条吧」→「还没有动态」;两处用例的 `pumpAndSettle` **改有限推进 `pumpFrames`** | 新空态文案变化 + `HeartRipple` 是无限动画,`pumpAndSettle` 永不收敛(批次②同款处理) |
| B | `square_page_test.dart:152` 起(在线点断言 + import) | `find.byType(OnlineDot)` → `find.byType(BreathingDot)` | 头像换 `AppAvatar`(内部呼吸点),`OnlineDot` 类删除 |
| C | `square_page_test.dart:61`、`:64` | `Icons.favorite` / `Icons.favorite_border` → `*_rounded` 变体 | §4「一律 rounded 变体」;颜色断言值不变(brand 同值) |
| D | `square_page_test.dart:107`(代码侧) | 空态「刷新」按钮及 key `square.refresh` **删除**(无测试引用) | 新空态按钮是「发布第一条」(`square.compose`);错误重试走 `square.retry` |

**不受影响(自审核对过)**:`find.text('动态详情') findsNothing`(square_page_test:149)是「没进详情页」的负断言,详情页**加标题**后依然成立;`find.text('已收到举报,我们会尽快处理')`(square_page_test:86)——`AppToast` 渲染同文案,`pumpAndSettle` 假时钟只推进到入场动画完成(~300ms),不会触发 2s 自动消失;「动态不存在」文案断言(`AppErrorView` 照常渲染 message);「我的动态」空态文案保留;`post.comment.*` / `post.card.*` / `post.avatar.*` 等 key 全保留。

**新增测试(预估 +8~10 例)**:广场页壳(大标题/骨架有限 pump/空态新文案+发布按钮跳转/错误重试)、九宫格(1 张通栏 / 2–4 张 3 列 / 5–9 张 3 列 / 加载失败占位)、点赞心跳脉冲(有限 pump 断言 scale 峰值 >1)、整卡 Hero(列表侧 `CardHero` tag = `card-post-{id}`;进详情 tag 一致;同作者多卡唯一;`extra == null` 不包 Hero;`disableAnimations` 不包 Hero)、评论行 28 圆头像 + fallbackText、我的动态空态按钮跳发布页。

**门槛**:

```bash
cd app
../flutter/bin/flutter.bat analyze   # 零告警
../flutter/bin/flutter.bat test      # 278 基线 + 新增全绿
```

`npm run test:run`(web)回归:本批**不动 `tokens.css`**(全部用既有 token,无新增视觉 token),理论上零牵连;执行中如确需新 token,同一次改动内同步 web 侧并跑双向比对(`tokens.spec.ts` / `fonts.spec.ts`)。

**手测**(计划阶段出清单,模拟器 release 包):页壳大标题/骨架/空态/错误重试;FAB 渐变圆钮;列表滚动不被悬浮底栏挡住;下拉刷新;圆形头像 + 在线呼吸点;九宫格 1/3/9 张布局;点赞脉冲;整卡 Hero 飞行顺滑、图片不中途换图、返回反向飞行、我的动态进入不飞;评论输入栏聚焦光晕与发送钮变色;系统「减弱动态效果」降级;窄屏(360dp)九宫格不溢出;封禁账号回归。

**文档同步**:

- 规则文档升 **v1.4**:新增附录 D「广场页落地补充(批次⑤)」——卡片规格、九宫格 3 列参数、操作行与点赞脉冲、整卡 Hero tag 规约 `card-post-{postId}`(§6.2 第二处)、紧凑输入场景输入框 44(修订 B.4 适用范围);正文 §6.2 清单第 2 条「动态卡→动态详情」转完成态;
- CLAUDE.md 里程碑表加批次⑤行 + 下一步改「⑥ 二级页」;
- `docs/pitfalls/frontend.md` 广场分节改:在线点口径 `OnlineDot → AppAvatar/BreathingDot`、整卡 Hero 与头像 Hero 嵌套纪律、`AppToast` 页面接入先例、九宫格 3 列与 key 保留口径。

## 自审更正记录(2026-10-12,设计呈现后)

1. **详情页标题断言撤回**:呈现时称 `find.text('动态详情') findsNothing` 需改 `findsOneWidget`——自审核对该断言在「自己的动态点头像不打开资料页」用例里,是「没进详情页」的负断言,加标题后依然成立,**无需改**;
2. **在线点类型波及补录**:设计呈现漏了「`AppAvatar` 内部是 `BreathingDot`」与既有 `OnlineDot` 类型断言的冲突,补为断言改动 B,并决定删除孤儿类 `OnlineDot`(顺带清裸 hex 违规);
3. **点赞图标变体波及补录**:测试内两处 `byIcon(Icons.favorite*)` 需随 §4 rounded 化同步(断言改动 C);
4. **空态 HeartRipple 的测试代价补录**:HeartRipple 无限动画会让空态用例的 `pumpAndSettle` 永不收敛,补为断言改动 A 的有限推进部分(批次②先例)。

5. **整卡 Hero 机制修正(用户确认「状态切换双保」)**:设计呈现时称「同页双 Hero 嵌套不冲突」——SDK 源码核查证伪(运行时断言禁止 Hero 嵌套,`heroes.dart:412`);且 Hero 扫描只在 push 后下一帧末进行一次(`heroes.dart:961-973`),详情页首帧是骨架屏、目标侧无 Hero,原机制 push 时根本不会飞。修正为「点卡时状态切换 + extra 携带 seed」,详见 §5。
