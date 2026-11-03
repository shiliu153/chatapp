# UI 整改批次⑥:二级页(设计)

日期:2026-10-12 · 状态:设计已获用户批准(逐节确认「可以」);范围经用户拍板为**一批做完**(9 页 + 控件规范);spec 自审后修正 5 处、写实施计划时回改 1 组(见文末「自审更正记录」)
上游:「心跳」设计规则 `2026-09-15-ui-design-language-design.md`(**常驻规则,一切视觉细节以它为准,本文件不重复抄录**);批次①②③④⑤已交付(296 测试绿);本批执行实施顺序 **⑥ 二级页**。

## 背景与目标

四个 Tab 主页与聊天/广场已全部整改完毕,但**低频二级页仍整体停在旧形态**:`AppBar` 系统标题、`FilledButton`/`OutlinedButton`/`SegmentedButton`/`FilterChip` 等 Material 默认件、裸 `SnackBar`、`CircularProgressIndicator`、`OutlineInputBorder`、`Colors.red`/`Colors.black26` 裸色。批次④/⑤ 已把「编辑」「发动态」「通用弹窗」显式留给本批。

本批整改这 10 个页面,**并一次性定死「表单控件规范」**(批次④/⑤ 反复提到的欠账),使 App 端从「Material 默认件拼装」彻底切换到「心跳自有组件」。

**范围界定**(用户已确认「一批做完」):

- **本批做**:登录页、启动页、引导页、设置页、黑名单页、编辑资料页、想找的人页、发动态页、协议页、封禁页;
- **横切**:`AlertDialog` → `AppDialog`(5 处)、`ScaffoldMessenger` → `AppToast`(7 处);
- **顺手抽共享**:`my_posts_page._SubPageBar` 与 `post_detail_page._DetailBar` 两份私有副本 → `AppSubPageBar`(纯去重,视觉不变)。

## 已定关键决策(用户确认)

| 决策点 | 结论 | 落选理由 |
|---|---|---|
| 批次粒度 | **一批做完**(9 页 + 控件规范) | 用户选:一次到位、不用两次验收;控件规范一次定死不留返工 |
| 发动态「发布」按钮位置 | **顶栏右侧文字按钮**(`brand` 15/w600;禁用 `text3`) | 微博/微信写作页习惯,正文区不被压缩、键盘弹出不挤;备选「底部全宽渐变主按钮」更重且吃高度 |
| 编辑资料/想找的人「保存」 | 同样放**顶栏右侧文字按钮** | 与发布页一致;§7 文字按钮是合规主操作表达 |
| 设置页「退出登录」 | 独立分组卡内**单行居中 `danger`**(无图标、无 chevron) | iOS/微信设置页通行样式;比独立危险按钮更轻,不抢主视觉 |
| 品牌 mark 是否带动画 | **静态**(无 `HeartRipple`/呼吸) | 登录/启动页有大量 `pumpAndSettle` 用例,常驻无限动画会让它们永不收敛(批次⑤踩坑) |

## 交付物

### 1) 新增 core 组件:表单控件规范(本批一次定死)

全部落 `app/lib/core/widgets/`,全部只吃既有 token(§2/§5/§6/§7),**不新增 token**。

| 组件 | 文件 | 规格与接口 |
|---|---|---|
| `AppSubPageBar` | `app_sub_page_bar.dart` | §5.2 二级页顶栏:高 **52**、返回 `arrow_back_ios_new_rounded` 22 `text1`、标题 17/w600 `text1` 居中。`AppSubPageBar({required String title, Key? backKey, VoidCallback? onBack, Widget? trailing, bool showBack = true})`;`onBack` 默认 `Navigator.of(context).maybePop()` |
| `AppBrandMark` | `app_brand_mark.dart` | 品牌 mark:72 圆角方 `gradientHeart` 底 + 白 `favorite_rounded` 32 居中;**静态无动画**(登录/启动页有 `pumpAndSettle` 用例)。`AppBrandMark({double size = 72})`,key 由调用方传(`login.brand` / `splash.brand`) |
| `AppTextAction` | `app_text_action.dart` | §7 文字按钮的**紧凑形态**:`brand` 15/w600,无 52 高、无 24 水平内边距,因此能塞进输入框 `suffix` 与顶栏 `trailing`;`onPressed == null` 时 `text3`。`AppTextAction({required String label, VoidCallback? onPressed, bool danger = false})` |
| `AppTextField` | `app_text_field.dart` | §7 输入框:白底 `bgCard`、R16、描边 1px `divider`、聚焦 1.5px `brand` + 光晕 `brand.withValues(alpha: .12)`(规则里写作 rgba(255,44,85,.12));单行高 **52**。`AppTextField({TextEditingController? controller, String? label, String? hint, String? errorText, TextInputType? keyboardType, int? maxLength, int maxLines = 1, int? minLines, ValueChanged<String>? onChanged, Widget? suffix, bool enabled = true, FocusNode? focusNode, TextInputAction? textInputAction})`;`maxLength != null` 时右下角渲染 `x/y` 计数(`micro` `text3`),**不用** `InputDecoration.counterText` |
| `AppOption<T>` / `AppOptionGroup<T>` | `app_option_group.dart` | 单选分段(性别 / 想找的人):白底 `bgCard` R16 描边 1px `divider` 容器内嵌等宽胶囊;**选中 = `gradientHeart` 填充 + 白字 15/w600**;未选中 = 透明底 + `text2` 15/w500。`AppOption({required T value, required String label})`;`AppOptionGroup({required List<AppOption<T>> options, T? value, required ValueChanged<T> onChanged})`。语义对齐现 `SegmentedButton`(不可取消选中,同现状) |
| `AppPickerField` | `app_picker_field.dart` | 点击唤起选择(生日):外观同 `AppTextField`(白底 R16 描边 1px 高 52);未选显示 `placeholder`(默认「请选择」)`text3`,右侧 `expand_more_rounded` 20 `text3`。`AppPickerField({required String label, String? value, String placeholder = '请选择', required VoidCallback onTap})` |
| `AppRangeField` | `app_range_field.dart` | 区间选择(年龄 18–99):标题行 `subtitle` `text1` + 双滑块(轨道高 4 R2 `divider`;选中段 `gradientHeart`;滑块 24 白底圆 + `AppShadows.card`)。`AppRangeField({required String title, required RangeValues values, required double min, required double max, int? divisions, required ValueChanged<RangeValues> onChanged})`;标题文案由页面拼 |
| `AppChipGroup<T>` | `app_chip_group.dart` | 多选标签:胶囊 R-full、描边 1px `divider`、白底;未选字 `text2`;**选中 = `brand@12%` 底 + 1px `brand` 描边 + `brand` 15/w600 字**;间距 8/8。`AppChipGroup({required List<AppOption<T>> items, required Set<T> selected, required ValueChanged<Set<T>> onChanged})`(复用 `AppOption`) |
| `AppSectionCard` | `app_section_card.dart` | 表单分组卡:白卡 R20 + `AppShadows.card` + 内边距 `AppSpacing.lg`;可选分组标题 `subtitle` `text1`(与字段 label `caption` `text2` 形成层级);子项按 `gap`(默认 `AppSpacing.lg`)竖排。`AppSectionCard({String? title, required List<Widget> children, double gap = AppSpacing.lg})` |
| `AppRowGroup` | `app_row_group.dart` | 行分组卡:白卡 R20 + `AppShadows.card` + **无内边距**(行自带 16 水平内边距);可选分组小标题(带 16 内边距);行间 1px `divider`。`AppRowGroup({String? title, required List<Widget> children})` |
| `AppListRow` | `app_list_row.dart` | §5.2 列表行:高 **64**;左槽 `icon`(20 `text2`,或 `avatar` Widget 覆盖);标题 `body` `text1`;副标题 `micro` `text3`;右槽 `trailing` 或默认 `chevron_right_rounded` 20 `text3`;`danger` 变体(图标/文字 `danger`);`centerTitle` 变体(居中、无槽,给「退出登录」);按压 scale .98。`AppListRow({IconData? icon, Widget? avatar, required String title, String? subtitle, Widget? trailing, VoidCallback? onTap, bool danger = false, bool showChevron = true, bool centerTitle = false})` |
| `AppDialog` / `showConfirmDialog` | `app_dialog.dart` | 统一对话框:白底 R24、标题 17/w600 `text1`、正文 `caption` `text2`、按钮行(次 + 主,危险动作用 `dangerFilled`)。`AppDialog({required String title, String? message, Widget? content, required List<Widget> actions})` 供自定义内容(协议弹窗);`Future<bool> showConfirmDialog(BuildContext, {required String title, String? message, String cancelLabel = '取消', required String confirmLabel, bool danger = false, Key? confirmKey, bool barrierDismissible = true})` 供五处确认框 |
| `AppProgressBar` | `app_progress_bar.dart` | 分段进度(引导页 3 段):高 4 R2 胶囊,段间 4;第 `i` 段填充 iff `i <= current`(已过段 `gradientHeart`,未过段 `divider`)。`AppProgressBar({required int steps, required int current})`;key 由页面传(引导页 `onboarding.progress`) |
| `AppFormSkeleton` | `app_form_skeleton.dart` | 表单页加载骨架:每组「标签条 64×12 + 输入框块 通栏×52(`AppRadius.input`)」,默认 3 组。`AppFormSkeleton({int fields = 3})`;含无限呼吸动画,**可见它的用例只用有限 pump** |

**`AppButton` 新增变体**:`AppButtonVariant.dangerFilled` —— §7「危险按钮:`danger` 描边或实底(二次确认后)」的实底形态(`danger` 实底 + 白字 w700,不带阴影:同屏阴影层级不超过 2 种,且 `primaryButton` 阴影是 brand 色)。

**新增 feature 组件**

| 组件 | 文件 | 规格 |
|---|---|---|
| `ComposePhotoGrid` | `features/square/widgets/compose_photo_grid.dart` | 发动态选图:3 列 R12 正方格(与 `PostImages` 同视觉,间距 `AppSpacing.sm`);加号格 = `divider` 底 + `add_photo_alternate_rounded` 24 `text3`;已选图右上角删除钮(半透明深底 R-full + `close_rounded` 14 白)。key `compose.add` / `compose.picked.{i}` **保留** |

### 2) 逐页设计

**P1 登录页(`features/auth/login_page.dart`)**

- 结构:顶部品牌区(`AppBrandMark(key: Key('login.brand'))`,**静态无动画**)→ 「交友 Chat」`AppText.display` `text1` + 副标题「手机号登录 / 注册」`caption` `text2` → `AppSectionCard` 表单卡(手机号 `AppTextField`;验证码 `AppTextField` 的 `suffix` = `AppTextAction` `brand`,倒计时中 `text3` 禁用)→ 全宽 `AppButton.primary`「登录 / 注册」→ 开发模式提示 `micro` `text3`。
- 提示通道:`SnackBar` → `AppToast`(文案逐字不变:『请输入正确的手机号』『验证码已发送,请查看短信』『请输入 6 位验证码』『网络超时,可直接再次点击「登录」重试』及接口 message)。
- key:新增 `login.brand`;保留 `login.phone` / `login.code` / `login.sendCode` / `login.submit`。
- 行为零变化:60 秒倒计时 Timer、`_phonePattern` 校验、`is_new_user` 分流、`takeForceLogoutReason` 首帧提示。

**P2 启动页(`features/auth/splash_page.dart`)**

- 居中品牌区(`splash.brand`,静态)+ 「交友 Chat」`title` + 状态文案「正在启动…」`caption` `text2`(原 `CircularProgressIndicator` 去掉——常驻无限动画,且品牌区已是视觉主体)。
- 失败态 → `AppErrorView`(message 为 `SessionBootFailed.message`)+ 重试(key `splash.retry`,新增)。
- 拒绝协议态 → 说明文案(逐字不变)+ `AppButton.primary`「重新阅读」(key `splash.reread` 保留)。
- 协议弹窗 → `AppDialog`(见 P10)。

**P3 引导页(`features/onboarding/onboarding_page.dart`)**

- `AppSubPageBar(title: '完善资料', trailing: AppTextAction(label: '稍后再说'))`(「稍后再说」无 key,现状无 key,保持不变)。
- 进度:`AppProgressBar(steps: 3, current: _step)` + **保留原文案「第 N 步 / 共 3 步」**(`caption` `text2`),替换 `LinearProgressIndicator`。
- 三步内容换新控件:第 1 步 昵称 `AppTextField` / 性别 `AppOptionGroup` / 生日 `AppPickerField`;第 2 步 城市 `AppTextField` / 简介 `AppTextField(maxLines: 3)` / 标签 `AppChipGroup`;第 3 步 照片 `PhotoGrid`。
- 底部:「上一步」`AppButton.secondary` + 「下一步 / 完成」`AppButton.primary`(key `onboarding.next` 保留)。
- 提示通道 → `AppToast`(文案逐字不变:『请填写昵称』『请选择性别』『请选择生日』『未满 18 周岁,无法使用本应用』『请填写城市』『请填写简介』『至少上传一张照片』及接口 message)。
- 校验函数 `validateBasicStep` / `validateAboutStep` 签名与返回值**零变化**(纯函数单测不受影响)。

**P4 编辑资料页(`features/profile/profile_edit_page.dart` + `widgets/profile_form_fields.dart` + `widgets/tag_selector.dart` + `widgets/photo_grid.dart`)**

- `AppSubPageBar(title: '编辑资料', trailing: AppTextAction(key: Key('edit.save'), label: '保存'))`;`AppBar` 去掉。
- 三张 `AppSectionCard`:①「基本信息」= 昵称 `AppTextField` / 性别 `AppOptionGroup` / 生日 `AppPickerField` / 城市 `AppTextField`;②「关于我」= 简介 `AppTextField(maxLines: 3, maxLength: 200)` / 标签 `AppChipGroup`;③「照片」= `PhotoGrid`。
- `profile_form_fields.dart` 的五个具名组件(`NicknameField` / `GenderSelector` / `BirthdayField` / `CityField` / `BioField`)改为新控件的薄包装,**对外构造签名不变**(引导页共用);key `edit.nickname` / `edit.birthday` / `edit.city` / `edit.bio` 保留。
- `TagSelector` 内部换 `AppChipGroup`(对外签名不变);标签加载中 → 三个胶囊 `AppSkeleton`,失败 → 文案(逐字不变)。
- `PhotoGrid` 视觉整改:88 定宽 → **3 列自适应**正方格 R12(与九宫格同视觉);待审核/已驳回角标改 `amber` 底 + 白字 `badge`;删除钮统一半透明深底圆;加号格 `divider` 描边 + `add_photo_alternate_rounded`;key `photo.add` / `photo.delete.{id}` 保留。
- 删除照片确认 → `showConfirmDialog(danger: true)`(文案「删除这张照片?」「取消」「删除」逐字不变)。
- 加载 → `AppFormSkeleton`(key `edit.skeleton`);错误 → `AppErrorView` + `edit.retry`(新增)。
- 提示通道 → `AppToast`(『已保存』及接口 message)。

**P5 想找的人页(`features/profile/preference_page.dart`)**

- `AppSubPageBar(title: '想找的人', trailing: AppTextAction(key: Key('preference.save'), label: '保存'))`。
- `AppSectionCard`:①「我想找」= `AppOptionGroup`(不限/男/女,文案逐字不变);② 年龄 = `AppRangeField`(标题「年龄 18 – 99 岁」文案格式不变);③ 城市 `AppTextField`(key `preference.city` 保留,label「城市(留空 = 不限)」逐字不变)。
- 加载 → `AppFormSkeleton`(key `preference.skeleton`);错误 → `AppErrorView` + `preference.retry`(新增);提示 → `AppToast`。
- 行为零变化:`target_gender` 的 `'any' → null` 映射、`age_max` 的 `clamp(18, 99)`、保存后 `pop()`。

**P6 设置页(`features/settings/settings_page.dart`)**

- `AppSubPageBar(title: '设置')`。
- `AppRowGroup`:①黑名单(`block_rounded`,key `settings.row.blocks`)、用户协议(`description_rounded`,key `settings.row.agreement`)、隐私政策(`privacy_tip_rounded`,key `settings.row.privacy`),三行均 `chevron_right_rounded`;②「退出登录」单行 `centerTitle: true` `danger: true`(key `settings.logout`)。
- 退出确认 → `showConfirmDialog(title: '退出登录?', message: '退出后需要重新用手机号登录', cancelLabel: '取消', confirmLabel: '退出', danger: true)`(文案逐字不变)。

**P7 黑名单页(`features/settings/blocked_users_page.dart`)**

- `AppSubPageBar(title: '黑名单')`。
- 行:`AppListRow(avatar: AppAvatar(size: 44, imageUrl: …, fallbackText: nickname), title: nickname, subtitle: '拉黑于 YYYY-MM-DD', trailing: AppTextAction(key: Key('unblock.{id}'), label: '解除'))`;`_dateLabel` 逻辑零变化。
- 加载 → 新 `BlockedUsersSkeleton`(3 行:`AppSkeleton` 圆 44 + 两条文字条,key `blocked.skeleton`);空态 → `AppEmptyState`(emoji `🙈` —— §7 允许「渐变几何图形或 emoji」,这里选 emoji 以免为本页单独造一个几何 mark + 「还没有拉黑任何人」文案**保留** + 说明「被你拉黑的人不会再出现在发现页」,key `blocked.empty`);错误 → `AppErrorView` + `blocked.retry`(新增)。
- 解除确认 → `showConfirmDialog(danger: false, confirmLabel: '解除', confirmKey: Key('unblock.confirm'))`(标题「解除对 X 的拉黑?」、正文「解除后你们将重新互相可见」、取消文案逐字不变)。
- 提示通道 → `AppToast`(『已解除拉黑』及接口 message);key `unblock.{id}` 保留。

**P8 发动态页(`features/square/post_compose_page.dart`)**

- `AppSubPageBar(title: '发布动态', trailing: AppTextAction(key: Key('compose.submit'), label: '发布'))`(禁用态 `text3`)。
- 正文:`AppTextField` 无边框变体(多行 6 行、17/1.5 `text1`、hint「分享新鲜事…」`text3`、`maxLength: 500`)+ 右下角 `x/500` 计数(key `compose.counter`,新增);输入时 `setState` 刷新「发布」可用态。
- 选图:`ComposePhotoGrid`(3 列 R12);`compose.add` / `compose.picked.{i}` 保留。
- 提示通道 → `AppToast`(『最多 9 张图片』『单张图片不能超过 5MB』及接口 message)。
- 行为零变化:`_maxBytes` / `_maxCount` 常量、`pickImages` 注入点、成功后 `pop(true)` + `invalidate(squareProvider)`。

**P9 协议页(`features/legal/legal_page.dart`)**

- `AppSubPageBar(title: _title, backKey: Key('legal.back'))`(新增 key)+ `AppSectionCard` 包长文(`body` `text1`、`height: 1.6`、`SingleChildScrollView` 内边距 `AppSpacing.pageH`)。
- `legal_texts.dart` **一字不动**;构造 `LegalPage.agreement` / `LegalPage.privacy` 不变。

**P10 封禁页 + 协议弹窗**

- `banned_page.dart`:整屏居中 96 圆 `danger.withValues(alpha: .12)` 底 + `block_rounded` 40 `danger`(§7 禁止灰色图标占位;清掉裸 `Colors.red` / 裸 `fontSize: 20` / `Colors.black54`);标题 `title` `text1`「账号已被封禁」、原因行「原因:{banReason}」`caption` `text2`、说明「封禁期间所有功能暂停使用」`caption` `text2`、「如有疑问请联系客服」`micro` `text3`——**文案逐字不变**;按钮 `AppButtonVariant.dangerFilled`「退出登录」(key `banned.logout` 保留)。
- `agreement_dialog.dart`:改用 `AppDialog`(自定义 `content` = 引导语 + 两个协议链接 `AppTextAction`;`actions` = 「不同意」`AppButton.secondary` + 「同意并继续」`AppButton.primary`);`barrierDismissible: false` 保持;key `agreement.accept` / `agreement.decline` 保留;**文案逐字不变**。

### 3) 横切:弹窗与提示通道统一

- **`AlertDialog` → `AppDialog` / `showConfirmDialog`(5 处)**:首启协议弹窗、退出登录确认、解除拉黑确认、删除照片确认、删除动态确认(`features/square/post_actions.dart`,key `post.delete.confirm` 保留)。
- **`ScaffoldMessenger.showSnackBar` → `AppToast`(7 处)**:`login_page` / `onboarding_page` / `profile_edit_page` / `preference_page` / `post_compose_page` / `photo_grid` / `blocked_users_page`(`post_actions.dart` 批次⑤已换)。
- 举报底部弹层 `ReportSheet` **不动**(bottom sheet,规则 §7 已合规);`AppTheme` 的 `snackBarTheme` **保留**(聊天等未整改页仍在用)。

### 4) 顺手清理(§2.3 对照表)

本批 10 个页面内所有裸 hex / 裸字号 / 裸间距 / 裸圆角清零,典型:`banned_page` 的 `Colors.red` / `fontSize: 20` / `Colors.black54`;`photo_grid` 的 `Colors.black26` / `Colors.black54` / `borderRadius: 8` / `fontSize: 11`;`post_compose_page` 的 `Colors.black26` / `borderRadius: 8` / `88` 定宽;`login_page` 的 `SizedBox(height: 60)` / `EdgeInsets.all(24)` 等硬编码留白改 `AppSpacing`。

## 不做(Non-goals)

- 后端接口、数据模型、provider 结构、路由路径、`legal_texts.dart` 文案 → **零变化**;
- 举报底部弹层(`ReportSheet`)重绘、长按菜单样式(系统 `showMenu`);
- 聊天系(`more_panel` / `emoji_panel` / `photo_viewer`)与发现/消息/广场/我的四个主页(前批已交付);
- `tokens.css` / `app_theme.dart` 改动(**不新增 token**,故 web 侧纯回归);
- 深色模式、golden 视觉回归、`AppBar` 全局主题化(本批是逐页去 `AppBar`)。

## 既有断言与测试适配(本批全部影响面,自审后核定)

**改断言(2 类)**:

| # | 位置 | 现状 → 改后 | 原因 |
|---|---|---|---|
| A | `post_compose_page_test.dart:44`、`:48` | `tester.widget<FilledButton>(button).onPressed` → `tester.widget<AppTextAction>(button).onPressed` | 顶栏 `FilledButton` 换 `AppTextAction` |
| B | 见下表「AppToast 收尾」 | 触发过 `AppToast` 的用例收尾补 `await drainToast(tester)` | `AppToast` 2s Timer → *A Timer is still pending*(批次⑤ `733f8e5` 实测确认,`drainToast` 已在 harness) |

**AppToast 收尾清单(8 文件 13 用例,逐条核对过)**:

| 文件 | 触发 Toast 的用例 | 触发点 |
|---|---|---|
| `login_page_test.dart` | 「手机号格式不对 → 不发请求」「verify 网络两次都失败」「verify 业务错误(码过期)不重试」共 **3** 例 | 页内提示 |
| `kicked_offline_test.dart` | 两例全中(**2** 例) | 登录页 `initState` 首帧提示被顶原因 |
| `account_switch_test.dart` | 被顶号那例(**1** 例) | 同上 |
| `onboarding_page_test.dart` | 「第 2 步校验:缺城市」(**1** 例) | 『请填写城市』 |
| `profile_edit_page_test.dart` | 两例全中(**2** 例) | 『已保存』/ 接口 message |
| `preference_page_test.dart` | 「设置偏好并保存」(**1** 例) | 『已保存』(Toast 挂在根 Overlay,pop 后仍存活) |
| `photo_grid_test.dart` | 「超过 5MB → 本地拦截」(**1** 例) | 『图片不能超过 5MB』 |
| `blocked_users_page_test.dart` | 「列表 + 解除拉黑」(**1** 例) | 『已解除拉黑』 |

`login_page_test` 的「获取验证码 → 倒计时」例已用 `pumpWidget(const SizedBox())` 卸树取消 Timer,无需 drain(执行时实测确认)。

**不受影响(自审核对过)**:`onboarding_page_test`(「第 N 步 / 共 3 步」文案保留、`onboarding.next` key 保留、`validate*` 纯函数未动——仅上表 1 例补 drain)、`settings_page_test`(`find.text('退出登录')` / `find.text('退出')` 文案保留,退出流程不弹 Toast;新增 4 个 key 断言)、`banned_page_test`(三条文案逐字保留 + 新增 `block_rounded` 断言)、`preference_page_test` 的断言本身(`find.text('女')` + `preference.save` 保留)、`startup_flow_test`(无 Toast)、`agreement_gate_test`(`agreement.accept` / `agreement.decline` key 与文案保留;启动页改静态后其 `:11` 注释「启动页在转圈(无限动画)」过期,顺手更新注释,`pumpUntilDialog` 保持有限 pump 不动)、`photo_grid_test` 的 key 断言(`photo.add` / `photo.delete.{id}` 保留)、`my_profile_page_test` / `home_shell_test` / `square_page_test`(不涉本批改动,批次⑤已适配;`square_page_test:57` 仅注释过期)。

**新增测试(预估 +35 例,296 → 约 331)**:

- **14 个 core 组件单测**:`app_sub_page_bar` / `app_brand_mark` / `app_text_action` / `app_text_field` / `app_option_group` / `app_chip_group` / `app_picker_field` / `app_range_field` / `app_section_card` / `app_row_group` / `app_list_row` / `app_dialog`(含 `AppButton.dangerFilled` 一例)/ `app_progress_bar` / `app_form_skeleton`;
- 页面级:登录页品牌区存在;启动页失败态重试;引导页进度段数与文案;编辑资料分组标题;想找的人「不限」映射;设置页四个新 key;黑名单骨架/空态/错误重试;发动态字数计数;协议页 `legal.back`;封禁页 `danger` 视觉;
- 共享抽取代价:详情页/我的动态页既有测试须继续绿(`AppSubPageBar` 纯替换)。

**门槛**:

```bash
cd app
../flutter/bin/flutter.bat analyze   # 零告警
../flutter/bin/flutter.bat test      # 296 基线 + 新增全绿
```

`npm run test:run`(web)回归:本批**不动 `tokens.css`、不动 `app_colors.dart`**(全部用既有 token;聚焦光晕/淡底走 `withValues` 派生,与 `app_avatar.dart:98`、`post_detail_page.dart:410`、`more_panel.dart:35` 同口径),web 侧应零牵连;执行中如确需新 token,同一次改动内同步 web 侧并跑双向比对。

**手测**(计划阶段出清单,模拟器 release 包):登录页品牌区与倒计时;启动页/协议弹窗同意与拒绝;引导页三步表单与进度;编辑资料分组与照片网格(含待审核角标、删除确认);想找的人滑块与「不限」;设置页四行与退出确认;黑名单空态/列表/解除确认;发动态字数计数与九宫格选图;协议页长文滚动;封禁页视觉;系统「减弱动态效果」;窄屏(360dp)表单不溢出;键盘弹出不遮输入框。

**文档同步**:

- 规则文档升 **v1.5**:新增附录 E「二级页/表单控件落地补充(批次⑥)」——表单控件规范表(11 个组件)、二级页顶栏 52 的共享实现、品牌 mark 静态纪律、弹窗 R24 与 `AppDialog` 口径、协议页排版;
- `docs/pitfalls/frontend.md` 新增「二级页与表单控件(`features/auth,onboarding,profile,settings,legal,shell`)」分节:品牌区禁常驻动画、`AppTextField` key 放包装件与 `enterText` 的 `matchRoot` 关系、Toast 收尾 `drainToast`、`AppSubPageBar` 取代两份私有副本;
- CLAUDE.md 里程碑表加批次⑥行 + 下一步改「上线合规轨(批次①–⑥ 已收官)」。

## 自审更正记录(2026-10-12,设计呈现后)

1. **分组卡拆成两个组件**:呈现时只说「`AppSectionCard` 分组卡(子行间 1px divider)」。自审发现两种用法内边距互斥(表单内容需 16 内边距、列表行需 0 内边距且行自带 16),硬塞进一个构造会引入 `padding`/`gap`/`divided` 三个互斥开关;改为 `AppSectionCard`(表单)+ `AppRowGroup`(行组)两个小件。视觉结论不变。
2. **登录/启动页品牌 mark 明确静态**:呈现时未指定动效。自审发现 `login_page_test` / `startup_flow_test` / `account_switch_test` / `kicked_offline_test` 全用 `pumpAndSettle`,常驻无限动画(如 `HeartRipple`)会让它们永不收敛(批次⑤实测坑);写入「已定关键决策」表并作为实现硬约束。
3. **引导页进度条保文案**:呈现时说「进度 = `AppProgressBar`」。自审发现 `onboarding_page_test` 两处断言 `find.text('第 N 步 / 共 3 步')`;改为「进度条 + 保留原步骤文案」,零断言改动。
4. **`drainToast` 影响面被严重低估**:呈现时说「登录/编辑资料/黑名单 3 个文件补 drain」。自审逐文件核对后修正为 **7 文件 12 用例** —— 漏掉的是 `kicked_offline_test` / `account_switch_test`(登录页 `initState` 的「被顶下线原因」提示也走 `AppToast`)与 `preference_page_test`(『已保存』Toast 挂在根 Overlay,页面 pop 后仍存活)。
5. **启动页去转圈的副作用**:`agreement_gate_test.dart:11` 的注释断言「启动页在转圈(无限动画)」;改静态后注释过期,列入顺手更新(测试逻辑不变)。
6. **写实施计划时回改 spec(组件清单与两处口径)**:① 组件从 11 个补到 **14 个** —— 新增 `AppBrandMark`(登录/启动共用)、`AppTextAction`(顶栏与输入框内嵌的紧凑文字按钮;原计划直接用 `AppButton.text`,但它 52 高 + 24 水平内边距,塞进 52 高的输入框会把盒子撑到 76)、`AppFormSkeleton`(编辑资料/想找的人/引导三页共用);② `AppButton` 新增 `dangerFilled` 变体(原计划用 `danger` 描边,但确认框里两个描边按钮并排语义不清;§7 明文允许「实底(二次确认后)」);③ 顶栏动作与登录页验证码按钮统一为 `AppTextAction`(故 `post_compose_page_test` 的类型断言目标是 `AppTextAction` 而非 `AppButton`);④ 分组标题定为 `subtitle`/`text1`(原写 `caption`/`text3` 会比字段 label 更弱,层级倒挂);⑤ 黑名单空态用 emoji(§7 允许「渐变几何图形或 emoji」,不为单页造几何 mark);⑥ `photo_grid_test` 的『图片不能超过 5MB』也是 Toast,收尾清单从 7 文件 12 例修正为 **8 文件 13 例**。
