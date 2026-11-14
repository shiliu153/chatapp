---
状态: 生效中
复核: 每次踩到新坑时
---

# 踩坑手册 · Web 端(Vue 网页端、构建与部署)

> 索引见 [README.md](README.md)。网页端与 App **共用同一套 Django 接口**,后端相关坑见 [backend.md](backend.md)、IM 相关见 [im.md](im.md)。
> 视觉规范同样以「心跳」设计规则为准(token 双份维护,见文末)。

## 为什么是 Vue 而不是 Flutter Web

1. **Flutter Web 走不通(实测否决)**:`tencent_cloud_chat_sdk` 的 models 无条件 `import 'native_im/...'`
   → 依赖 `dart:ffi`,Flutter 3.47.2 下编译出 **5147 条错误**;升到 9.1.7818 同样失败;
   把插件摘掉后能构建 → 结论是插件本身不支持 Web。故网页端改用 Vue 3(见 `specs/2026-10-05-web-frontend-design.md` §2)。
2. **`Wasm dry run failed` 那一大段是警告不是错误**:别把它当成构建失败的原因去排查。

## 环境与构建

3. **`.env.test` 不能漏**:vitest 的 mode 是 `test`,**不会**读 `.env.development`;
   漏了的症状是「本地 `npm run dev` 能跑,测试里 baseURL 是 `undefined`」。
4. **`vite preview` 不继承 `server.proxy`**:端到端要单独配 `preview.proxy`,
   否则 `npm run e2e` 里所有接口请求都是跨域失败(而 `npm run dev` 一切正常,极易误判)。
5. **TS 6 弃用了 `baseUrl`**(直接报 TS5101)→ tsconfig 里去掉它,`paths` 用相对路径;
   且 TS 6 要求副作用式 CSS import 有类型声明(TS2882)→ 需要 `src/vite-env.d.ts`。

## IM(网页端 SDK 与 App 插件差异大)

6. **图片消息必须先 `registerPlugin` 上传插件**,否则 `sendImage` 报 `code 2040 未检测到上传插件`。
   ⚠️ 而且**必须在 `login()` 之前**注册:上传模块在构造时就缓存了插件引用。
   另外包名是 **`tim-upload-plugin`** —— `@tencentcloud/upload-plugin` 在 npm 上**不存在(404)**。
7. **`login()` 的 Promise resolve 时 `isReady()` 仍是 `false`**:此时调其它 API 会拿到「未就绪」错误。
   真机症状是**聊天历史永远空白**。必须在 login 后等 `sdkStateReady`(带超时兜底)。
8. **踢下线要按原因分流**:`multipleAccount` = **同端多标签页**,只提示 + 手动接管,
   **绝不能清凭证**(localStorage 是共享的,清了会把所有标签页一起登出);
   `multipleDevice` / `REST_API_Kick` 才是真的被别处顶掉。
   ⚠️ 一开始按「multiAccount 就自动重连」实现,两个标签页会**互相踢**,实测 10 秒打了 27 次
   `POST /im/user_sig` 并被 IM 限流。
9. **新建会话的服务端摘要可能是残缺的**(`lastMessage` 只有 `payload.text`,`from/time/nick` 全空;
   `userProfile` 也空),而 **SDK 不会自己补全**(等 8 秒也没变)→ 会话列表要按 peerId **合并**,
   不能用残缺摘要覆盖本地已知的昵称;昵称未知时主动拉一次 `getUserProfile` 兜底。
10. **图片 URL 的权威字段是 `sizeType`(1=原图/2=缩略/3=大图),不是 `type`**:
    实测收到方向 `type` 是 0/1/2 且不可靠(有一条 `type=1` 的 URL 反而是空的);
    且 URL 有两个字段(`imageUrl` 是 https、`url` 是 http)→ 取 `imageUrl || url` 并**跳过空值**。

## 后端侧的坑(网页端联调时暴露)

11. ⚠️ **腾讯 `account_import` 会清空已存在账号的昵称与头像**(2026-10-12 修):
    它对**已存在**账号返回 `ErrorCode: 0`(**不是**文档说的 7015),并把 `Nick`/`FaceUrl`
    **覆盖**成传入值。原实现「先导入、7015 当成功」于是有两个后果:
    ① 每次 `POST /im/user_sig` 的首次 `ensure_account` 都把刚同步好的昵称/头像清成空串
    (会话列表显示成 `u43` 而不是昵称);② 7015 分支永远走不到,是假兜底。
    修法:`ensure_account` 先 `account_check` 问状态,已存在直接成功、不存在才导入;
    查询失败**不盲目导入**(导入是破坏性的),返回 False 让上层重试。
    **看到会话列表显示 `u43`,先怀疑这条。**

## 测试

12. **组件测试的 pinia 必须与预置状态的是同一个**:`mount(..., { global: { plugins: [createPinia()] } })`
    会新建一个与预置无关的 pinia,组件读到的永远是空 store。统一用 `tests/support/pinia.ts` 的 `freshPinia()`
    (它顺带 `setActivePinia`,所以**不要再手动调一次** `setActivePinia`,会拿到两个不同的实例)。
13. **E2E 的手机号必须 11 位**:后端 `accounts/serializers.py::PHONE_RE` 卡 `^1[3-9]\d{9}$`,
    拼成 10 位会在发验证码时直接 400。
14. **E2E 完善资料必须填「简介」**:后端完善判定是 nickname/gender/birthday/city/**bio** + ≥1 张过审照片,
    漏一项资料就是 `incomplete`、**永远不会进别人的候选卡**,主干流程会卡在滑卡那一步。
15. **E2E 不能假设「第一张卡就是对方」**:候选接口是 `order_by("?")`,且造数用户有 20+ 个。
    收窄办法:让双方都把「想找的城市」设成同一个**本用例专属城市**,候选池就只剩对方。
16. **首启协议弹窗会盖住登录表单**:每个新 context 都是干净 localStorage,必然出现;
    不先关掉,`fill` 会一直等不到可交互的元素。它还是**挂载时**读 localStorage 的 ——
    测试里清完 localStorage 必须重新加载才看得到。
17. **Playwright 定位器要防 strict mode**:`getByText('心跳')` 会同时命中标题与首启弹窗的
    「欢迎来到心跳」→ 用 `getByRole('heading', { name: '心跳', exact: true })`。

## 部署

18. **`/media/` 直出每个站点都要配**,漏了就是照片 404(2026-09-23 域名接入时踩到)。
19. ⚠️ **宝塔「反向代理」生成的 `proxy_cache` 键不含 `Authorization`**,且 `proxy_ignore_headers` 忽略 `Vary`
    → **跨用户缓存泄漏**(实测响应头出现 `X-Cache HIT`)。要么不开页面缓存,
    要么把 `Authorization` 加进 `proxy_cache_key`。**这是安全问题,不是性能问题。**
20. **`MEDIA_BASE_URL` 若还是安卓模拟器地址**(`http://10.0.2.2:8000`),
    同步给 IM 的头像地址在网页端加载不出来(它只影响 IM 头像,不影响 `/users/me`)。
    上线前改成对外地址并按 [README](../../README.md) 的「换域名后刷 IM 头像」重刷。
21. **根路径 `/` 必须有路由落点**(2026-10-26 生产手测):未登录时守卫会把「没匹配到路由」
    当成需要登录、重定向到 `/login`,所以看起来一切正常;**已登录时守卫直接放行,
    `RouterView` 渲染空白页**。修法是给 `/` 加 `redirect: { name: 'home' }`
    (`web/src/router/routes.ts`),由守卫再决定去登录还是首页。`routes-resolve.spec.ts`
    里有一条导航断言守着它。
22. **线上构建会静默落后**:2026-10-26 发现 `/www/wwwroot/chatapp-web` 还是 10-12 的产物,
    不含最小版本拦截与自建 IM,而服务端早已是 10-21+ 的代码。验证「功能是否真的上线」
    不要看仓库、也不要只看页面能打开,直接在产物里 grep 本次新增的字符串
    (如 `min_app_version`),或看 `index.html` 引用的 hash 是否是刚构建的。
23. ⚠️ **`MIN_APP_VERSION` 同时卡网页端**(2026-10-28 切域名时踩到):`web/src/main.ts`
    启动时读 `/api/v1/app/config`,用自己的 `__APP_VERSION__`(来自 `web/package.json`)
    跟 `min_app_version` 比;把 App 升到 1.0.1 而网页端还是 1.0.0 时,
    **整站会被「需要更新后才能继续使用」挡住**。所以**发版必须双端同版本**:
    改 `app/pubspec.yaml` + `app/lib/core/app_info.dart` 的同时改 `web/package.json`,
    并重新 `npm run build` 部署 `dist`(只改后端 `.env` 的 `MIN_APP_VERSION` 会让网页端立刻不可用)。

## 纪律

- **「心跳」token 双份维护**:改任何视觉 token 或字体,**必须在同一次改动内同时改**
  `app/lib/core/theme/*.dart` 与 `web/src/styles/tokens.css`
  (`web/public/fonts/*` 与 `app/assets/fonts/*` 保持一致);
  `web/tests/unit/tokens.spec.ts` 与 `fonts.spec.ts` 会双向比对,漏改即红。
- 改接口必须同步 `docs/api/`(双向门禁,`ApiDocsCoverageTests` 会红)。
- 网页端**只服务 PC 浏览器**,移动端按 UA 进引导页,不提供手机网页版。

## 令牌硬化(2026-10-28)

- **access 只在内存,refresh 在 HttpOnly Cookie**:`web/src/api/token-store.ts` 不再把任何令牌写 localStorage(只留 `hb.userId`)。页面刷新后 access 丢失是**预期行为**,`session.restore()` 直接请求 `/users/me`,由 401 拦截器用 Cookie 换新 access 再重放。
- **请求要带 `X-Client: web`**:后端据此把 refresh 放进 Cookie 而不是响应体。漏了这个头,登录响应里会出现 `refresh` 字段、Cookie 也不会下发 —— 表现成「刷新页面就掉线」。
- **刷新请求体必须是 `{}`**:空 body + `application/json` 会让 DRF 抛 `ParseError`(400)。`http.ts::refreshAccessToken` 传 `{}` 而不是 `null`。
- **多标签页同时刷新靠后端 60 秒宽限**:前端不做跨标签锁(轮询/加锁在后台标签被节流时不可靠),后到者拿旧 refresh 仍能拿到同一对新令牌。
- **退出登录必须调接口**:`session.logout()` 先 `POST /auth/logout` 清 Cookie,再清内存;接口失败也要清本地(否则用户卡在「退不出去」)。注销账号同理 —— 账号行删了拉黑必然失败,但 Cookie 能被清掉。
- **测试隔离要显式清内存令牌**:`localStorage.clear()` 清不到模块内的 `accessToken`,所以 `tests/support/server.ts` 的 `afterEach` 里要 `tokenStore.clear()`。组件测试若自建 `ProviderScope`,`flutter_secure_storage` 那条是 App 侧的事,Web 不受影响。
- **老用户升级会被登出一次**:旧版本写在 localStorage 的 `hb.access`/`hb.refresh` 在模块加载时直接删除,不回灌 Cookie(没有安全通道把旧 refresh 换成新会话)。发版说明里要提一句。

## 录音这类「有副作用的状态机」别写在组件里(2026-11-01)

- `ChatPage.vue` 原来把 MediaRecorder 生命周期直接写在组件里，`onUnmounted` 顺手调了 `finishRecording()` —— **离开聊天页会把正在录的语音发给对方**。同期还有三个洞：指针拖出按钮后 `pointerup` 丢失（录音停不下来，直到 60 秒自动发）、`getUserMedia` 失败静默 `return`、能力不支持时按钮直接消失。
- **规则**：凡是「开始 / 结束 / 取消 + 超时自动结束」的状态机，抽成 composable（Web `useVoiceRecorder`、App `VoiceRecordController`）并显式提供 `dispose()`；`dispose()` 的语义固定是**取消**，不是完成。测试里必须有一条断言「dispose 之后没有发送」。
- **置灰别用 `disabled`**：`disabled` 的按钮收不到 click，就没法「点击告知原因」。用 `aria-disabled` + 样式，保留 click 处理。

## Web IM 的断线感知(2026-11-03,审查 N-1)

- **服务端 75 秒没收到业务帧就关连接**（`imserver/src/net/ws_server.cpp` 的 `arm_idle_timer` + `do_close(1000)`），而 **WS 层的 keep-alive 救不了**：Beast 在协议层就消费掉了控制帧，`last_frame_` 只在业务帧的 `on_read` 里刷新。所以前端必须发**业务** `ping`（Web 与 App 都是 25 秒一次）。
- 反过来的坑更隐蔽：**浏览器不会告诉你连接已经关了**，除非你挂 `ws.onclose`。旧实现只挂了 `onFrame`，于是静置 75 秒后前端仍显示 `ready`，对方新消息**静默丢失**，服务端也没有 5xx（`do_close(1000)` 是正常路径）。
- **`disconnected` 与 `kickedOffline` 必须是两个事件**：被同端另一个标签页顶掉时服务端会先发 `kicked` 再用 **4001** 关连接，如果把这当成断线去自动重连，就变成两个标签页互相踢（实测 10 秒打了 27 次 `user_sig` 被限流）。`SelfImClient` 用 `suppressClose` 标记「已顶号」，随后的 `onclose` 不再上报。
- **重连成功必须补拉**：断线期间的消息服务端不会主动重放，`stores/chat.ts` 的 `refetchAfterReconnect()` 会重拉会话列表 + 当前会话历史（`activePeerId` 由 `openConversation` 维护），靠 `mergeMessages` 按 `msgId` 去重。
- **断线时挂起的发送要立刻失败**：否则每条消息都要干等 `10s × 3` 次重试，用户看到的「发送中」会挂 30 秒。`sendText/sendImage/sendVoice` 在 catch 里检查 `authed`，断线即抛，UI 直接出「重发」。
- 别在 `login()` 里 `await` 旧 transport 的 `close()`：多一个微任务会让「发 auth 帧」的时序整体后移（单测里 `transport.sent[0]` 会变成 `undefined`）。发起关闭即可，旧连接本来就已经断了。

## 端到端冒烟进 CI(2026-11-05,E-3)

- **只把「登录 → 完善资料 → 发现/广场列表」1 条放进 CI**(`web-e2e.yml` → `npm run e2e:smoke`):
  真 MySQL + Redis + Django(`runserver`)+ `vite preview`。全量 8 条要 imserver + Celery
  (发消息、灰条、已读、媒体上传),在 Actions 里起全栈的收益抵不过 flaky 风险,继续本地人工跑。
- **CI 环境变量有两个坑**:`SMS_PHONE_WHITELIST` 必须留空(空库 + 空种子时,测试环境走 `SMS_ALLOWLIST_STRICT` 的非严格分支放行;写进种子反而会让名单外的号 403);
  `AUTO_APPROVE=1`,否则新上传的照片是 `pending`,资料永远 `incomplete`,发现页永远空。
- **冒烟别去消息页**:会话列表走 imserver 的 `/im/api/conversations`,冒烟轨不起 imserver,
  只会看到「消息加载失败」。验证列表用**广场** `/posts`(纯 Django)或发现页候选。
- **Windows 本地 4173 可能起不来**:报 `EACCES: permission denied 127.0.0.1:4173` ——
  端口落在 Hyper-V 保留段(`netsh interface ipv4 show excludedportrange protocol=tcp` 可见)。
  `playwright.config.ts` 支持 `PLAYWRIGHT_PORT=5000 npm run e2e` 换端口,CI 不受影响。

## 前端错误上报(2026-11-03,A-4)

- **`window.onerror` 抓不到 Vue 组件里的异常**：Vue 会自己捕获渲染/生命周期错误，必须另外挂
  `app.config.errorHandler`（`src/main.ts` 已挂）。两个都挂才算齐活。
- **资源加载失败也会触发 `error` 事件**（图片/脚本 404），那种事件的 `event.error` 是 `undefined`、
  只有 `event.message`；不判空会往上报里塞一堆 `undefined`。
- **`PromiseRejectionEvent` 在 jsdom 里不存在**：单测要自己 `new Event('unhandledrejection')`
  再 `Object.defineProperty(event, 'reason', ...)`，别指望构造器。
- **上报请求要 `keepalive: true`**：白屏后用户刷新/跳转时，普通 fetch 会被中断，恰恰丢掉最该留下的那条。
- **开关必须走构建期变量**（`VITE_ERROR_REPORTING`，`.env.production` 为 `1`、开发/测试为 `0`）：
  否则本地每改一行代码都会往生产日志灌垃圾；单测用 `vi.stubEnv` 打开、`installClientErrorReporting({ enabled: true, sender })` 注入假发送器。
- **`request_id` 靠响应头 `X-Request-Id` 串起来**：`api/http.ts` 的响应拦截器把它记进
  `clientErrors.rememberRequestId()`，上报时带上，前后端日志就能按同一个 id 对上。


