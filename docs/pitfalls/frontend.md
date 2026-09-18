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

- 页面:广场流 `square_page.dart`(卡片/九宫格/点赞乐观更新/滚底加载)、发布 `/posts/compose`(相册多选 + 一次 multipart)、详情 `/posts/:id`、我的动态 `/my-posts`(入口在「我的」页 `my.row.posts`);共用 `post_actions.dart`(删除确认 + 举报,复用 moderation 的 `ReportSheet`)。
- 作者可点:卡片与评论的头像/昵称 → 公开资料页(`/users/{id}`;自己的走空回调吞掉点击);作者头像在线绿点 `OnlineDot(size: 11)`,评论区**不带**绿点。
- 测试 keys:`post.avatar.{id}` / `post.nickname.{id}` / `post.comment.avatar.{id}` / `post.comment.nickname.{id}`。
- ⚠️ 我的页行变多后,点靠下行的测试(想找的人/设置)要先 `tester.ensureVisible`。

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
