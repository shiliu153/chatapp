# 踩坑手册 · 前端(Flutter / Riverpod)

> 索引见 [README.md](README.md)。UI 视觉规范以「心跳」设计规则(`specs/2026-09-15-ui-design-language-design.md`)为准。

## 核心约定(必须守)

- 分层:repository(纯 IO,JSON → 模型)→ Riverpod controller → widget;路由表 `lib/router.dart` 按 `SessionState`(sealed)重定向:splash → 登录页 → 主框架。
- 鉴权:401 只走 `AuthInterceptor` 通道(裸 Dio 静默刷新一次 → 重放原请求;再失败 `TokenStore.clear()` → `SessionController` 踢回登录页)。**别在页面里各自处理 401**。
- 错误:统一 `ApiException`(message 即后端中文提示);页面 SnackBar 展示。测试辅助函数别叫 `fail`(与 flutter_test 撞名)。
- 接口地址:`--dart-define=API_BASE=...`(桌面/Web `http://127.0.0.1:8000/api/v1`;模拟器 `http://10.0.2.2:8000/api/v1`;服务器 `http://<SERVER_IP>/api/v1`)。
- 封禁页:`home_shell` 检测 `profile.status == 'banned_heavy'` → 整屏封禁页(原因 + 「封禁期间所有功能暂停使用」+ 退出登录)。

## Riverpod 3

- `AsyncValue.valueOrNull` 已移除 → 用 `.value`(可空)。
- ⚠️ **build 失败的 provider 会被自动重试**(`ProviderContainer.defaultRetry`,200ms 起指数退避):页面上已有手动「重试」按钮时,在 provider 上 `retry: (count, error) => null` 关掉,否则错误界面一闪而过、测试断言不稳。
- ⚠️ **全局缓存 vs autoDispose**:
  - `AsyncNotifierProvider` 默认常驻 → 页面 B 写了页面 A 读过的列表,**写操作后必须 `ref.invalidate(该 provider)`**(M3 手测:拉黑后黑名单页仍显示空)。
  - 反向坑:『只在页面打开期间才该生效』的副作用(自动已读/事件订阅)必须 `.autoDispose`——聊天页 `chatProvider` 曾常驻,退出后仍自动已读、消息红点永不出现。
- ⚠️ **换号登录必须清按用户隔离的缓存**:`SessionController._resetUserScopedCaches()` 统一 invalidate(`profile`/`discovery`/`blockedUsers`/`userProfileProvider` 整族)。**别只挂在「设置→退出登录」上**:被顶号/心跳 40101 路径不经过设置页,漏清就串号(手测:被顶号后换号,我的页整屏还是上一个账号)。他人资料卡是公开数据但「能不能看到」随号主变(拉黑/重封禁),留旧缓存会让新号绕过可见性判断。会话列表/matchCache 随 IM 登录态自动重建,不用清。
- ⚠️ presence `track()` **绝不能同步改 state**(页面在 build 里调用,同步改触发 Riverpod 断言)。

## 发现卡片流(`lib/features/discovery/`)

- 行为:拖过屏宽 25% 判滑出(不到弹回);`decide` 先移卡(乐观),失败放回队首 + SnackBar;剩 ≤3 张且非整批拉取时自动续拉;拉空 → 空态 +「刷新」。手势动画全自绘,没引第三方卡组包。
- ⚠️ **续拉必须按 `userId` 去重**:`/discovery/candidates` 只排除「已划过」,**卡组里还没划的人会被再发回来**;直接追加会出现同一人的重复卡(后端幂等不报错,极难发现——2026-09-10 手测揪出)。
- ⚠️ **顶层卡拖拽手势必须 `behavior: HitTestBehavior.opaque`**:`GestureDetector` 默认 `deferToChild`,照片区没有命中目标,按在照片上拖不动。
- 手测配对动效需要两个资料完善且有已过审照片的账号互滑(单账号只能看到「卡片飞出」)。

## 广场(`features/square/`)

- 页面:广场流 `square_page.dart`(白卡流/九宫格/点赞乐观更新+脉冲/滚底加载/**整卡 Hero**)、发布 `/posts/compose`(批次⑥ 已改:顶栏发布文字按钮 + 无边框正文 + 三列选图)、详情 `/posts/:id`(自绘顶栏 + 评论流 + 44 紧凑输入栏)、我的动态 `/my-posts`(复用动态卡,不参与 Hero);共用 `post_actions.dart`(删除确认 + 举报,提示走 `AppToast`)。
- ⚠️ **整卡 Hero 与头像 Hero 互斥**(SDK 硬断言禁 Hero 嵌套,`heroes.dart:412`,debug 直接崩):列表卡普通态带头像 Hero;点卡进详情时该卡切整卡态(头像 Hero 让位),`await push` 返回后还原。**详情页顶卡在整卡态下 `PostCard.heroTag` 必须 null**。
- ⚠️ **Hero 扫描只在 push 后下一帧末进行一次**(`heroes.dart:961-973`):目标页首帧必须已有同 tag 的 Hero 才会飞 —— 详情页 `postDetailProvider` 是 autoDispose,首帧必为骨架屏,所以进详情的 `extra` 要带 `PostDetailArgs(heroTag, seed)`,provider loading 时用 seed 直出真卡。深链/我的动态(无 extra)不包 Hero。
- ⚠️ **在线点统一走 `AppAvatar(showOnlineDot:)`**(内部 `BreathingDot` 呼吸动画):旧 `OnlineDot` 静态点已删(它的 `#34C759` 也违反 §2.1 `green`);呼吸点可见的用例禁 `pumpAndSettle`。
- ⚠️ **`find.byX` 默认 `skipOffstage: true`**:被 push 盖住的页面在测试里默认找不到(要 `skipOffstage: false`);`CardHero`/`AvatarHero` 是恒在的包装 widget(tag 为 null 时只返回 child),判断「有没有 Hero」要看 `tag != null`,不能看 widget 类型。
- 测试 keys:`post.card.{id}` / `post.avatar.{id}` / `post.nickname.{id}` / `post.comment.avatar.{id}` / `post.comment.nickname.{id}` / `square.fab` / `square.compose` / `square.retry` / `post.back` / `myPosts.back` / `myPosts.compose`。
- ⚠️ 我的页行变多后,点靠下行的测试(想找的人/设置)要先 `tester.ensureVisible`。

## 二级页与表单控件(`features/auth,onboarding,profile,settings,legal,shell`)

- 页面:登录 `login_page.dart`(静态品牌区 + 表单卡)、启动 `splash_page.dart`(静态品牌区,无转圈)、引导 `onboarding_page.dart`(三步向导 + `AppProgressBar`)、编辑资料 `profile_edit_page.dart`(三张 `AppSectionCard`)、想找的人 `preference_page.dart`、设置 `settings_page.dart` + 黑名单 `blocked_users_page.dart`(两张 `AppRowGroup`)、发动态 `post_compose_page.dart`、协议 `legal_page.dart`、封禁 `banned_page.dart`。
- ⚠️ **品牌区禁常驻动画**:登录/启动页有 `pumpAndSettle` 用例(`login_page_test`/`startup_flow_test`/`account_switch_test`/`kicked_offline_test`/`agreement_gate_test`),`AppBrandMark` 做成纯静态;启动页原 `CircularProgressIndicator` 已移除。
- ⚠️ **表单组件的外层 `Column` 在宽松高度约束下会撑满整屏**:`AppTextField`/`AppPickerField` 的根是 `Column(mainAxisSize.max)`,直接放进 `Scaffold(body:)` 时高度 = 整屏,`tester.getSize(find.byKey(...))` 拿到的是整屏、`tester.tap(find.byKey(...))` 会落到盒子外(实测踩坑)。**按 key 取尺寸/坐标做断言或点击时,要点内部子件**(如 `find.text('请选择')`),或把尺寸断言指向内部盒子。放进 `ListView`/`Card` 等有界约束里则正常收缩。
- ⚠️ **`AppListRow` 的 `GestureDetector` 必须 `behavior: HitTestBehavior.opaque`**:默认 `deferToChild` 时,整行右侧空白区(标题文字之外)点不动 —— 设置页/黑名单行都会中招。
- ⚠️ **`AppTextField` 的 key 放包装件**:`tester.enterText(find.byKey(...))` 内部走 `find.descendant(..., matchRoot: true)`,能穿透到内部 `EditableText`;但**别在包装件和内部 `TextField` 上挂同一个 key**,否则 `find.byKey` 命中两个。
- ⚠️ **计数别用 `InputDecoration.counterText`**:会被 Material 默认样式接管,`AppTextField` 自己画 `x/y`(带 `counterKey`)。
- ⚠️ **`AppToast` 收尾**:触发过 Toast 的用例必须 `await drainToast(tester)`。容易漏的三处:① 登录页 `initState` 的「被顶下线原因」提示(`kicked_offline_test`/`account_switch_test`);② 保存成功后 pop 的页面 —— Toast 挂在根 Overlay,pop 不会取消它的 2s Timer(`preference_page_test`/`profile_edit_page_test`);③ `photo_grid` 的『图片不能超过 5MB』。
- ⚠️ **`AppToast.show(context, …)` 写在 async gap 之后会触发 `use_build_context_synchronously`**:`if (!mounted || files.isEmpty) return;` 这种**复合守卫 analyzer 不认**,要拆成两句 `if (!mounted) return;` + `if (files.isEmpty) return;`,并在每个 `await` 之后补 `if (!mounted) return;`(见 `post_compose_page.dart::_pick`)。
- ⚠️ **分组卡两种内边距**:表单内容用 `AppSectionCard`(内边距 16),行式列表用 `AppRowGroup`(无内边距、行自带 16、行间 divider),不要混用。
- 测试 keys:登录 `login.phone`/`login.code`/`login.sendCode`/`login.submit`/`login.brand`、启动 `splash.brand`/`splash.reread`/`splash.retry`、引导 `onboarding.next`/`onboarding.progress`/`onboarding.retry`、编辑资料 `edit.nickname`/`edit.birthday`/`edit.city`/`edit.bio`/`edit.save`/`edit.skeleton`/`edit.retry`、想找的人 `preference.city`/`preference.save`/`preference.retry`、设置 `settings.row.blocks`/`settings.row.agreement`/`settings.row.privacy`/`settings.logout`、黑名单 `unblock.{id}`/`unblock.confirm`/`blocked.empty`/`blocked.skeleton`/`blocked.retry`、照片 `photo.add`/`photo.delete.{id}`、发动态 `compose.text`/`compose.submit`/`compose.add`/`compose.picked.{i}`/`compose.counter`、协议 `legal.back`、封禁 `banned.logout`、弹窗 `agreement.accept`/`agreement.decline`/`post.delete.confirm`。
- 规则细则见 [设计规则附录 E](../superpowers/specs/2026-09-15-ui-design-language-design.md)。

## 在线状态前端(`features/presence/`)

- 共享 autoDispose `PresenceController`:页面 build 里 `track('owner', ids)` 登记,多页面**合并去重后一次请求**,45s 周期刷新;失败保留旧值不弹提示;间隔 `presenceRefreshIntervalProvider`(pumpApp 默认 override 成 null)。
- 文案 `presenceLabel()`:在线「● 在线」/ 离线「x 分钟前在线」(`formatLastActive`:刚刚/x 分钟前/x 小时前/x 天前)。
- 展示四处:消息列表头像绿点 / 聊天页标题小字 / 发现卡昵称旁 / 广场作者头像。
- 服务端语义、上限与分片细节见 [backend.md](backend.md)。

## UI 与构建环境(Windows)

- ⚠️ 照片上传用 `readAsBytes` + `MultipartFile.fromBytes`(Web 上 `XFile.path` 是 blob URL,不能用 `fromFile`);单张 ≤5MB 前端先拦。
- ⚠️ `pub add` 后提示 "requires symlink support" = 未开 Windows 开发者模式;**Android/Web 构建不受影响**,桌面 `-d windows` 需要开。
- ⚠️ **`app/android/gradle.properties` 的 `kotlin.incremental=false` 勿删**:pub 缓存在 C 盘、工程在 D 盘,Kotlin 增量编译缓存算跨盘相对路径会崩(`Could not close incremental caches ... different roots`);关掉增量是官方 workaround。
- `SystemNavigator` 在 `package:flutter/services.dart`(material 不导出)。

## 改完前端要生效

- ⚠️ **改代码后必须重打 APK 并覆盖安装**,模拟器/手机上旧包不会自己更新(2026-09-12 踩过:只改代码没打包,用户在旧包上复测以为没修好)。
