# UI 整改批次④:我的页 + 他人资料页(设计)

日期:2026-10-12 · 状态:设计待用户终审
上游:「心跳」设计规则 v1.2 `2026-09-15-ui-design-language-design.md`(**常驻规则,一切视觉细节以它为准,本文件不重复抄录**);批次①②③已交付(247 测试绿);本批执行实施顺序 **④ 我的 + 资料页**。

## 背景与目标

批次③交付消息/聊天页后,四个主页面只剩「我的」仍是微信式设置列表;他人资料页(二级页)是「看别人」的落点,也仍停在微信「详细资料」形态。两页都不带任何「这是一张人的脸」的视觉中心。

本批整改这两个页面,**并首次落地 §6.2 的 Hero 转场**(头像 → 他人资料页;规则里点了名,批次②③ 都没做)。他人资料页改成照片头图后与发现卡同构,正是加它的时机。

**范围界定**:规则 §8 把「编辑」明确划给 ⑥ 二级页,故本批**只做「看资料」的两页** —— `my_profile_page.dart`(Tab 主页)与 `user_profile_page.dart`(二级页)。编辑资料、想找的人、设置、登录、引导页全部留 ⑥。

**两处行为新增**(已随本批批准,其余行为零变化):

1. **他人资料页接入在线状态**:`presenceProvider.track('user:{id}', [userId])`,叠字显示在线/离线。此前该页完全不查在线状态;从发现卡点进来会出现「在线信息断层」。
2. **聊天页顶栏新增头像 32**:批次③ 附录 B.2 定的是「右侧无按钮」、标题区两行居中,当时**没有头像**。要让聊天页参与 Hero 就得有可飞的源,故左侧改为「返回 + 头像 32」,点头像或名字都进资料页(点名字的行为不变)。

## 交付物

### 1) 我的页(`features/profile/my_profile_page.dart`)

- **页壳**:去 `AppBar` → `SafeArea(top)` + 页内大标题「我的」`AppText.display`(32/w800,`text1`),内边距 `EdgeInsets.fromLTRB(16, 16, 16, 12)`(§5.2 Tab 主页),与发现页/消息页同构。
- **身份卡**(`AppCard` 白底 R20 内边距 16),分两段(避免可点区域嵌套):
  - **身份区**(整段可点,key `my.card.identity` → `context.push('/profile/edit')`,**保留「点资料进编辑」语义**):
    - 左:`AppAvatar` **72 圆形**(`fallbackText: nickname`,附录 B.7 首字占位);
    - 右:昵称 `AppText.title`(20/w700,`text1`)+ `ID:u{userId}` `AppText.micro`(`text3`);
    - **72 是 §5.3 尺寸档(28/32/40/48/56/96)之外的新档** → 走 §9 边界流程,回填附录 C。
  - **完成度区**(仅 `!isComplete` 时渲染):上边 1px `divider`,内容 = 左侧**完成度环 44** + 右侧「还差:城市、简介」(`AppText.caption`/`text2`)+ `AppButton.text`「去完善」(key `my.goOnboarding` → `context.go('/onboarding')`,**行为与 key 均不变**)。
  - **完成度环**(新组件 `CompletionRing`):44×44,底环 3px `divider`,进度弧 3px **`gradientHeart`**(SweepGradient 着色),中央 `AppText.micro`/`text1` 显示「4/6」。它是本页唯一的渐变高音(§2.2),引导视线到「去完善」。
- **资料组**(白卡 R20):性别 / 生日 / 城市 / 简介 / 标签。
  - 行版式:**标签 13/`text2` 定宽 72 + 取值 15/`text1` + `chevron_right_rounded` 20/`text3`**;行高 56;行间 1px `divider`;水平内边距 16。
  - 空值仍显示「未填」(**测试语义不变**);key `my.row.{gender|birthday|city|bio|tags}` 全部保留;整行可点 → `/profile/edit`(不变)。
- **入口组**(白卡 R20):我的动态 / 想找的人 / 设置 —— 左侧新增 rounded 图标 22(`text2`,依次 `grid_view_rounded` / `favorite_rounded` / `settings_rounded`),右侧 `chevron_right_rounded`;key `my.row.{posts|preference|settings}` 保留,跳转不变。
- **收敛的三个 key**:`my.row.avatar` / `my.row.nickname` / `my.row.id` 合并进身份卡 → 统一为 `my.card.identity`(行数从 8 降到 5)。身份卡里 ID 以 `ID:u{userId}` 形式自带前缀(不再有行标签),与公开资料页的 `ID:u9` 格式统一。
- **加载** → `ProfileSkeleton`(新文件):身份卡骨架(72 圆块 + 两条文字条)+ 5 行行骨架,复用 `AppSkeleton` 呼吸节奏;替换 `CircularProgressIndicator`。
- **错误** → `AppErrorView`(原因取 `apiMessageOf(error)`,重试 = `profileProvider.notifier.reload()`),**不再显示裸 `'$error'`**(§7 / 附录 B.8)。
- 行为不变:封禁整屏在 `home_shell` 层、`profileProvider` 数据来源、全部路由跳转。

### 2) 他人资料页(`features/profile/user_profile_page.dart`)

- **照片头图**(新组件 `ProfilePhotoHeader`):首张已过审照片全出血,高 `min(屏宽 × 1.15, 420)`;`BoxFit.cover`。无照片 → `divider` 底 + `person_rounded` 64 `text3`(与发现卡同款**内容占位**,非空态)。
- **叠字 scrim**(与附录 A.2 完全同源):底渐变 `Colors.transparent → AppColors.photoScrim`,内边距 `(16, 46, 16, 14)`;叠字白系:
  - 昵称·年龄 `AppText.display`(32/w800)白,格式 `昵称,年龄`(**与发现卡一致**,无年龄时不带逗号);
  - 城市 `AppText.caption` 白 72%;
  - 在线:`BreathingDot` 11(白描边)+「在线」`AppText.micro` 白 88%;离线:不渲染该行(该页此前无在线信息,故**不做**「x 分钟前在线」,避免与发现卡文案口径分叉)。
- **透明顶栏**(自绘,不套 Material `AppBar`):`SafeArea` 内高 52(§5.2 二级页),返回 `arrow_back_ios_new_rounded` 22 白(key `user.back` 新增)+ 右侧 `more_horiz_rounded` 24 白(key `user.more` 保留、`user.report`/`user.block` 菜单项与行为全不变);照片区顶部叠一层 `transparent → 黑 45%` 的 scrim 兜底可读性。
  - **删除「详细资料」标题**(照片 + 名字已在头图里,标题冗余)。这是本批**唯一影响既有断言的视觉删减**,见「测试与验收」。
- **资料卡**(白卡 R20,上边距 12,水平外边距 16):个性签名 / 标签。
  - 标签 chip:`divider` 底、`text1` 12、R8、内边距 3×8(白卡上不用发现卡的白 22% 底);
  - 空值显示「未填」(`bio` 为空时),标签为空则整行不渲染。
- **相册**:3 列,间距 8、**R12**(§5.3 相册/照片网格;替换现 R4/间距 6);点击 → `openPhotoViewer`(行为不变,key `user.album.photo:{i}` 保留);无照片时该区块不渲染。
- **加载** → `UserProfileSkeleton`(新文件):头图等大骨架 + 3 行行骨架;替换 `CircularProgressIndicator`。
- **错误** → `AppErrorView`(key `user.retry` 保留,原因取 `apiMessageOf`;404「用户不存在」文案与「不区分不存在/双向拉黑/重封禁」的语义不变)。
- **新增在线状态**:`presenceProvider.track('user:{userId}', [userId])`,与广场/动态详情页写法一致(见「两处行为新增」)。

### 3) Hero 转场体系(§6.2 首次落地)

- **tag 命名**:由**来源自身 id** 派生,天然唯一 —— `avatar-post-{postId}` / `avatar-comment-{commentId}` / `avatar-chat-{peerId}`。
  - 为什么不用 `avatar-{userId}`:`Hero` 要求**同一路由内 tag 唯一**,用 userId 时同一作者的两条动态/两条评论会同屏重复 → debug 下直接抛 `There are multiple heroes that share the same tag`。用来源 id 派生后**零碰撞**,故可全量接入。
- **tag 传递**:跳转时 `context.push('/users/$userId', extra: <tag>)`;`/users/:id` 路由读 `state.extra as String?`。
  - `extra == null`(深链、无来源、从通知进入)→ 目标页**不包 `Hero`**,静默不飞、不报错(宽容模式)。
- **接入点**(全部 4 类来源):
  | 来源 | tag | 改动文件 |
  |---|---|---|
  | 广场动态卡头像 | `avatar-post-{post.id}` | `square_page.dart` 传 `PostCard(heroTag:)` |
  | 动态详情页作者头像 | `avatar-post-{post.id}` | `post_detail_page.dart` 传 `PostCard(heroTag:)` |
  | 动态详情页评论头像 | `avatar-comment-{comment.id}` | `_CommentTile` 新增 `heroTag` |
  | 聊天页顶栏头像(本批新增) | `avatar-chat-{peerId}` | `chat_page.dart` 的 `_ChatHeader` |
- **共享组件** `core/widgets/avatar_hero.dart`(新文件):`AvatarHero({required String tag, required Widget child, double radius = AppRadius.chip})`。
  - 内置 `flightShuttleBuilder`,用 `ClipRRect` 把**圆角从来源半径插值到 0**(目标头图是全出血直角矩形)。不这样做的话,默认 shuttle 取目标 child,飞行途中圆角会硬切。
  - `MediaQuery.disableAnimations` 为真 → 直接返回 `child`(不包 Hero,§6.3 降级)。
- **时长**:`AppMotion.hero`(380ms),不做额外曲线定制。
- **图片一致性(已实测)**:广场 `author_brief` 的 `avatar_url` 与 `GET /users/{id}` 的 `photos` **都取该用户第一张已过审照片**(`Photo.Meta.ordering = ["order", "id"]`),故飞行两端是**同一张图**,不会中途换图。
- **`PostCard` 新增可选参数 `heroTag`**:为 `null` 时不包 Hero —— 广场列表以外的一切复用方(如未来的「我的动态」)零影响。

### 4) 新组件

| 文件 | 内容 |
|---|---|
| `features/profile/widgets/completion_ring.dart`(新增) | `CompletionRing({required int done, required int total, double size = 44})`:底环 3px `divider` + 渐变进度弧 3px + 中央「done/total」`AppText.micro` |
| `features/profile/widgets/profile_skeleton.dart`(新增) | `ProfileSkeleton`:我的页骨架(身份卡 + 5 行) |
| `features/profile/widgets/user_profile_skeleton.dart`(新增) | `UserProfileSkeleton`:他人资料页骨架(头图 + 3 行) |
| `features/profile/widgets/profile_photo_header.dart`(新增) | `ProfilePhotoHeader({required photos, required nickname, age, city, online})`:照片头图 + scrim + 叠字;无照片走占位 |
| `core/widgets/avatar_hero.dart`(新增) | `AvatarHero`:带圆角插值 shuttle 的 Hero 封装(见 §3) |

### 5) 「心跳」规则文档回填(§9 边界流程,先于代码)

`2026-09-15-ui-design-language-design.md` 升 **v1.3**,新增「附录 C:我的/资料页落地补充」:

- **C.1 头像 72 档**:§5.3 尺寸档扩为 28/32/40/48/56/**72**/96(我的页身份卡)
- **C.2 身份卡**:白卡 R20 内边距 16;头像 72 圆形 + 昵称 20/w700 + `ID:u{id}` 12 `text3`;完成度环 44(底环 3px `divider`、进度弧 3px `gradientHeart`、中央 12 `text1`);不完整时补「还差:{缺项}」13 `text2` + 文字按钮「去完善」
- **C.3 我的页行版式**:行高 56;标签 13 `text2` 定宽 72;取值 15 `text1`;右侧 `chevron_right_rounded` 20 `text3`;行间 1px `divider`;入口行左侧 rounded 图标 22 `text2`
- **C.4 资料页照片头图**:全出血,高 `min(屏宽 × 1.15, 420)`;底部 scrim 同 A.2;叠字白系(名字 32/w800 白、城市 13 白 72%、在线 = 11 呼吸点 + 13 白 88%);顶部叠 `transparent → 黑 45%` scrim 供透明顶栏
- **C.5 资料页透明顶栏**:高 52;返回 22 白、右侧 `more_horiz_rounded` 24 白;**无标题**(照片+名字已承载身份)
- **C.6 相册网格**:3 列、间距 8、R12(§5.3「相册不是头像」的落地参数)
- **C.7 Hero 转场 tag 规约**:tag 由**来源自身 id** 派生(`avatar-post-{id}` / `avatar-comment-{id}` / `avatar-chat-{peerId}`);跨页经路由 `extra` 传递;无来源时两端都不包 Hero;圆角用 `flightShuttleBuilder` 插值到 0
- **C.8 聊天页顶栏补头像 32**:修订附录 B.2 —— 左侧改为「返回 + 头像 32(圆形,带 Hero)」,点头像或名字均进资料页;标题区仍两行居中;右侧仍无按钮

## 关键决策

| 决策 | 结论 | 理由 |
|---|---|---|
| 本批范围 | 只做「看资料」两页 | 用户选 A:规则 §8 已把「编辑」划给 ⑥,不越界;表单控件规范留给 ⑥ 一次做 |
| 我的页版式 | 身份卡 + 资料行 + 入口组 | 用户选 A:现状无任何「这是我自己」的视觉中心;行数 8→5 更紧凑 |
| 他人资料页版式 | 照片头图 + 叠字(与发现卡同构) | 用户选 A:从滑卡点进来观感连贯;照片存在感从「小网格」提到「整页头图」 |
| 完成度提示 | 并进身份卡 | 用户选 A:不再单独占一个横幅;渐变环成为本页唯一高音,直指「去完善」 |
| Hero 转场 | 本批做 | 用户选:§6.2 点名两处之一;资料页改头图后正是时机 |
| Hero tag | 由来源自身 id 派生 + `extra` 传递 | 用户选 A:userId 派生在同作者多卡时**必然崩**(重复 tag);来源 id 派生零碰撞,故可全量接入 |
| 聊天页顶栏头像 | 加(32 圆形) | 用户选 A:不加就没有可飞的源;顺带与微信/探探一致;修订附录 B.2 |
| 资料页在线状态 | 加 | 用户选:小行为新增,换掉「从发现卡点进来在线信息断层」 |
| 编辑入口 | 身份区 → `/profile/edit`;「去完善」→ `/onboarding` | 保住「点资料进编辑」的既有语义与测试;两个入口职责分明 |
| 「详细资料」标题 | 删除 | 照片+名字已承载身份;透明顶栏上再压标题会与头图抢焦点 |
| 离线文案 | 资料页不显示「x 分钟前在线」 | 与发现卡文案口径分叉会让人困惑;该页此前无在线信息,只补「在线」是净增而非回退 |

## 非目标(本批不做)

- 编辑资料页 `/profile/edit`、想找的人 `/preference`(留 ⑥ 二级页,与设置/登录/引导一起定表单控件规范)
- 设置页、黑名单页、登录页、引导页、协议页(⑥)
- 广场(⑤)/ 消息 / 聊天 的**静态视觉**整改(Hero 只触碰它们的头像包装,不改其版式)
- `viewer`(看大图页)重做、长按菜单样式统一
- 看大图页与资料页的 Hero(图片→全屏大图,规则未点名)
- 任何接口/路由/错误契约变化;golden 视觉回归;深色模式

## 测试与验收

**必须更新的既有断言**(共 4 类,语义不变、仅选择器/载体变化):

1. **`find.text('详细资料')` → 页面标识**(删标题的直接后果):`square_page_test.dart`(3 处:2 个 findsOneWidget + 1 个 findsNothing)、`post_detail_page_test.dart`(3 处)。改为 `find.byType(UserProfilePage)`(findsNothing 处改 `findsNothing` 同理)。
2. **我的页资料行 key 收敛**:`home_shell_test.dart`(1 处 `my.row.nickname`)、`profile_edit_page_test.dart`(2 处 `my.row.nickname`)→ 改 `my.card.identity`(语义同为「资料即编辑入口」)。
3. **我的页 ID 文案格式**:`my_profile_page_test.dart:28` 的 `find.text('u7')` → **`find.text('ID:u7')`**。身份卡里 ID 没有行标签,必须自带 `ID:` 前缀;这同时与公开资料页的 `ID:u9`(`user_profile_page_test.dart:70`)统一。同用例的 `find.text('u6') findsNothing`(不得拿 profile 主键冒充账号 ID)**保持不变**。
4. **行数变化后的 `ensureVisible`**:`settings_page_test.dart` / `my_posts_page_test.dart` 的 `ensureVisible` 保留即可(行数变少后它退化为无操作,不构成失败),不做删改。

**新增测试**:

- `CompletionRing`:渲染 done/total 文案;`done == total` 时满弧;`done == 0` 时不崩。
- `ProfilePhotoHeader`:有照片渲染图片 + 昵称·年龄/城市;无照片走占位;**在线时渲染呼吸点、离线不渲染**(有限 `pump`)。
- `ProfileSkeleton` / `UserProfileSkeleton`:渲染冒烟(**有限 `pump`,禁 `pumpAndSettle`**)。
- 我的页:不完整时显示「还差:…」+「去完善」→ 点击跳 `/onboarding`(key `my.goOnboarding`);完整时**不显示**完成度区;身份区点击 → 进编辑页。
- 他人资料页:错误态 `user.retry` 仍可重试;`⋯` 菜单三项行为(举报/拉黑)全部保持;`user.back` 可返回。
- `AvatarHero`:`extra` 为 null 时不包 Hero;有 tag 时渲染 `Hero`;`disableAnimations` 为真时不包 Hero。
- 跨页冒烟:广场点 `post.avatar.{id}` → 资料页出现,且两端 tag 一致(断言资料页存在 `Hero` 且 tag 等于来源 tag)。

**门槛(每步全绿再进下一步)**:

1. `flutter analyze` 零告警
2. 全量 `flutter test` 绿(247 既有 + 更新 + 新增)
3. 模拟器手测(用户亲测,连测试服务器):我的页(完整/不完整两态、完成度环、5 行、三入口);他人资料页(有照片/无照片、在线/离线、相册点开大图、举报/拉黑);Hero 转场四处(广场卡→资料、详情页作者→资料、评论→资料、聊天顶栏→资料);系统「减弱动态效果」下无异常;封禁账号整屏不受影响;窄屏(360dp)头图叠字不截断

## 风险与观察点

- **Hero 重复 tag**:已用「来源 id 派生」根除;但仍需注意**同一路由内不得出现两个同 tag 的 Hero** —— 若将来给广场列表加「同一条动态渲染两次」的逻辑(如置顶重排),需重新审视。
- **Hero 飞行中源被销毁**:广场列表是懒加载 `ListView`,若飞行期间列表项滚出被回收,飞行会中断(不崩、只是没有转场)。属可接受退化,不做额外处理。
- **`find.text('详细资料')` 删除面**:影响 2 个测试文件 6 处断言,已在上面逐条列出;这是本批唯一「视觉删减导致断言载体变化」的地方,实现时**逐条核对、不批量替换**。
- **无限动画与 `pumpAndSettle`**:骨架屏、在线呼吸点、完成度环若有动画,涉及态一律有限 `pump`(见 `docs/pitfalls/testing.md`,批次②③已有先例)。
- **`AppAvatar` 72 档**:超出 §5.3 尺寸档,按 §9 先回填附录 C.1 再写代码。
- **透明顶栏在浅色照片上的可读性**:靠顶部 scrim(黑 45%)兜底;若手测发现极端浅色照片仍看不清返回箭头,只调该 scrim 透明度,不动结构。
- **窄屏(360dp)**:头图高 414、叠字两行(名字 32/w800 + 城市)在超长昵称下可能换行;名字行加 `maxLines: 1 + ellipsis`,手测确认。
- **`my.goOnboarding` 现无测试引用**:实测 grep 全项目无该 key 的用例(只有 `discovery.goOnboarding`),故它可安全保留;新增用例会覆盖它。
- **规则文档先行**:头像 72 档、身份卡、行版式、照片头图、透明顶栏、相册网格、Hero tag 规约、聊天顶栏补头像**均属 §9 未覆盖场景**,先回填附录 C 再写对应代码。
