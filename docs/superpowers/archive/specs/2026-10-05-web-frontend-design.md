# 网页端(PC Web)设计

日期:2026-10-05
状态:已与用户逐节确认(见 §13 关键决策记录),待用户终审
上游:CLAUDE.md「核心契约与纪律」;`docs/api/`(32 接口);「心跳」设计规则 `docs/superpowers/specs/2026-09-15-ui-design-language-design.md`;`app/lib/core/theme/*.dart`(token 权威来源)
背景:用户提出「现在开始补充网页端」。经逐节确认:目的 = **功能对等的完整网页版产品**;设备 = **PC 浏览器优先**;节奏 = **不分批,一次做完**;登录 = **保持单设备、不改后端**。技术路线原定「Flutter Web 复用现有代码」,在动手前做构建验证时被**实测否决**(§2),改判为 **Vue 3 独立前端**。

## 1. 目标与范围

**目标**:交付一个面向**桌面浏览器**的完整网页端,覆盖 App 的全部业务能力(登录 / 引导 / 发现滑卡 / 配对 / 聊天 / 广场 / 我的 / 设置 / 举报拉黑 / 在线状态 / 协议),与 App 共用同一套 Django REST 接口。

**范围**:11 个业务模块(§8),对 `/api/v1` 全部**业务接口**的客户端侧接入——32 个接口中的 **30 个**(另 2 个 `/health`、`/readyz` 是运维探针,`docs/api/health.md` 明确「客户端不需要调用」)。

**硬约束**:

- `app/`(Flutter)与 `chatapp/`(Django)**零代码改动**;`docs/api/` 接口文档不新增、不修改(无接口变更,`ApiDocsCoverageTests` 不受影响)
- 「心跳」设计语言仍是唯一视觉权威,Web 端以 CSS 变量重建一份,**不接受走样**(§7)
- 上线时间受备案约束:备案期间域名不得开放网站访问,故分「IP 阶段 / 域名阶段」两段(§11)

**非目标(YAGNI)**:见 §15。

## 2. 为什么不用 Flutter Web(实测记录,2026-10-05)

原方案是「在 `app/` 里补 web 支持,复用 8.8k 行 Dart UI 与 247 个测试」。动手前做构建验证,**被实测否决**:

| 验证项 | 方法 | 结果 |
|---|---|---|
| 现状能否构建 Web | `app/` 下 `flutter build web` | ❌ 失败,**5147 条错误** |
| 真正卡在哪 | 过滤错误来源 | 全部来自 `tencent_cloud_chat_sdk`:`dart:ffi is not available on this platform`(15)、`'Pointer' isn't a type`(1723)、`'Void'/'Char'/'NativeFunction'/'Allocator'/'DynamicLibrary'` 等 FFI 类型大批缺失,以及 `V2TimMessage/*1*/` vs `/*2*/` 之类**同一类型被加载两份** |
| 根因 | 读插件源码 | 插件的 **models 文件无条件 import 原生实现**:`models/v2_tim_message.dart:11,24`、`models/v2_tim_image_elem.dart:7` 等 → `native_im/adapter/tim_c_enum.dart` / `native_im/tools.dart`(`tools.dart:2,4` 即 `dart:ffi` + `package:ffi`)。`manager/*.dart` 有 `if (dart.library.html)` 条件分支,但 models 没有 |
| 是否只有插件有问题 | 临时副本中把插件替换为桩实现后重新构建 | ✅ **成功(exit 0)** —— 其余全部代码(含 `message_bubble.dart:1,133` 的 `dart:io` / `Image.file`,它在 Web 上「能编译、运行时报错」)都能编到 Web |
| 升级能否解决 | 副本里升到当时最新版 `9.1.7818`(2026-09-20 发布) | ❌ **同样失败**(`'Pointer' isn't a type` 1725 次);其 pubspec 仍依赖旧 `js: ^0.6.4` |
| 排除误判:条件导入判据 | 最小复现:`dart:html` 用 dart2js 单独编译 | ✅ 通过;`dart.library.html` 与 `dart.library.js_interop` 在 Web 上**均为 true** → 不是判据问题 |
| 排除误判:wasm 预检 | 读构建输出 | 大段 `dart:html unsupported` 属 **`Wasm dry run` 警告**,非致命;唯一构建阻塞点是插件 |

**结论**:**腾讯云 IM 的 Flutter 插件在当前 Flutter 3.47.2 / Dart 3.13.2 下无法编到 Web,且上游最新版未修复;补丁需 fork 插件并改 20+ 个模型文件,不划算。** 而腾讯浏览器端的 IM 走另一条**官方主路径**并活跃维护:

| 包 | 版本 | 发布 | 说明 |
|---|---|---|---|
| `@tencentcloud/chat` | 3.6.7 | 2026-08 | 「Tencent Cloud Chat SDK for Web/Mini Program/uni-app/React Native」,**无头 SDK** |

**连带消失的两个坑**(若走 Flutter Web 则必须自行解决,现在都不存在):

| 坑 | 证据 | 影响 |
|---|---|---|
| CanvasKit 默认从 `www.gstatic.com` 拉取 | `flutter/packages/flutter_tools/lib/src/build_system/targets/web.dart:129-137`(`--no-web-resources-cdn` 可改为本地) | 国内白屏 |
| 中文字形默认从 `fonts.gstatic.com` 懒加载 | `flutter/bin/cache/flutter_web_sdk/lib/_engine/engine/font_fallback_service.dart:483`(基址见 `configuration.dart:363-365`;Noto Sans SC 共 101 个 woff2 分片) | 国内中文整片空白,且引擎拉不到就静默关闭字体服务 |

## 3. 技术选型

| 用途 | 选型 | 为什么 |
|---|---|---|
| 框架 | **Vue 3** `<script setup>` + **Vite** + **TypeScript** | 用户选定;中文文档质量最好,上手平缓;Vite 冷启动快、TS 编译期抓字段错误 |
| 路由 | **vue-router**(history 模式) | 对应 `go_router`;深链 `/chat/123` 可直达 |
| 状态 | **Pinia** | 对应 Riverpod:一领域一 store |
| 网络 | **axios** + 拦截器 | 对应 `dio` + `AuthInterceptor`;**401 刷新通道照搬**(单设备登录能落地的前提) |
| 样式 | **原生 CSS + CSS 变量(scoped)** | 「心跳」token 直接映射为 CSS 变量;**不用 Tailwind/Vue 组件库**——工具类与「禁止裸值」的 token 纪律冲突 |
| 组件测试 | **Vitest** + `@vue/test-utils` + **MSW** | 对应 App 的「真实 store + 假网络」:MSW 在网络层挡请求,组件树与 store 是真的 |
| 端到端 | **Playwright** | 打真后端跑真流程,亦是手测清单的自动化版 |
| 包管理 | **npm**(本机 Node 22.15 / npm 10.9) | 已装,不引新工具链 |

**目标浏览器**:Chrome / Edge(Chromium 内核)近两年版本为主,Safari 16+ 与 Firefox 近两年版本兼容;**不做 IE 与老旧内核**(不为此引入 polyfill)。

## 4. 工程结构(新建 `web/`,与 `app/`、`chatapp/` 并列)

```
web/
├── index.html
├── package.json / package-lock.json / tsconfig.json / vite.config.ts
├── .env.development / .env.production        # API 基址
├── src/
│   ├── main.ts / App.vue
│   ├── router/          # vue-router 路由表 + 守卫(未登录→登录、封禁→引导页、移动端→引导页)
│   ├── api/             # 一个模块一个文件:auth/users/discovery/im/feed/moderation/presence
│   │   ├── http.ts      #   axios 实例、错误契约解析、401 刷新通道
│   │   └── types.ts     #   接口 TS 类型(字段以 docs/api/ 与各 serializers.py 为准)
│   ├── stores/          # session / profile / discovery / chat / feed / presence
│   ├── im/              # @tencentcloud/chat 封装:登录、事件、发文本/图片、已读
│   ├── styles/
│   │   ├── tokens.css   #   「心跳」token(§7)—— 与 App 的 *_dart 一一对应
│   │   └── base.css     #   重置、字体、滚动条
│   ├── components/      # AppButton / AppInput / AppCard / AppAvatar / AppEmpty / AppErrorView / AppSkeleton / AppBadge
│   ├── layouts/         # DesktopShell(可拖拽侧栏)/ NarrowGuard(移动端引导页)
│   └── features/        # auth onboarding discovery chat square profile settings moderation legal
└── tests/
    ├── unit/            # Vitest:store、拦截器、token、UA 判定、侧栏几何
    ├── component/       # Vitest + @vue/test-utils + MSW
    └── e2e/             # Playwright
```

## 5. 架构与数据流

### 5.1 路由与守卫

- history 模式,路径与 App 对齐:`/login`、`/onboarding`、`/home`、`/chat/:peerId`、`/users/:id`、`/posts/:id`、`/posts/compose`、`/my-posts`、`/settings`、`/settings/blocks`、`/profile/edit`、`/preference`、`/legal/agreement`、`/legal/privacy`
- 守卫顺序:**移动端判定 → 会话态 → 封禁态**(对应 `app/lib/router.dart` 的 `redirect`)
  - 未登录 → `/login`(协议全文页 `/legal/*` 公开可访问)
  - `banned_heavy` → 引导页;`banned_light` 允许浏览,发现页操作处给提示
- 首启协议弹窗的「已同意」标记存 localStorage(对应 App 的 SharedPreferences)

### 5.2 网络层与鉴权

- 单一 axios 实例:`Authorization: Bearer <access>`;响应错误统一解析为 `ApiError { code, message, requestId }`(对应 `ApiException`),**业务代码不直接读 axios error**
- **401 → 刷新 → 重放原请求**,并发去重(同一时刻多个 401 只刷一次);刷新也用同一套轮换语义(响应同时给新 refresh)
- **`401 + 40101`(被顶号)→ 全屏提示**「你的账号已在其他设备登录」+ 清凭证回登录页。**非目标**:静默 toast(浏览器无推送,静默等于用户不知道)
- 写操作成功后失效相关 store(对应 App「写操作后检查 provider 失效」)

### 5.3 单设备登录(不变,后端零改动)

后端以 **账号级会话版本** 实现(`chatapp/accounts/views.py:89-104` 登录时 `session_version += 1`,`authentication.py` 比对)。因此:**网页登录会把手机 App 顶下线,反之亦然——这是刻意保留的现状**(用户选定)。

**同一浏览器的多标签页要分两个层面看**(2026-10-05 核对 SDK 类型定义后澄清,原稿只写了第一层):

| 层面 | 行为 |
|---|---|
| **REST 会话** | **不互顶**。会话版本只按账号计,标签页不算新设备;凭证存 localStorage,所有标签页共享 |
| **IM 连接** | **默认互踢**。`ChatSDK.login` 文档原文:「同一账号已在其他页面登录,会把那边踢下线」,触发 `KICKED_OUT` 事件(腾讯云控制台「在线 Web 实例数」默认为 1) |

**由此产生一条设计约束**(不是可选优化):Web 端必须按**踢出原因**分流 ——

- `multipleDevice`(多个端)/ `REST_API_Kick`(服务端踢)/ `userSigExpired`(签名过期)→ 视为真被顶号:全屏提示 + 清凭证
- `multipleAccount`(**同端第二个标签页**)→ **只重连 IM,绝不清凭证**。否则共享的 localStorage 被清空,会把**所有**标签页一起登出

控制台侧的另一条选择是把「在线 Web 实例数」调到 > 1(让多标签页共存),但这会与「单设备」的产品语义打架,故**不改控制台**,由前端分流承担。

### 5.4 IM 接入(`@tencentcloud/chat` 3.6.7,无头)

- 生命周期:`POST /api/v1/im/user_sig` → `{user_sig, sdkappid}`(`chatapp/im/views.py:31-32`,**SDKAppID 由接口返回,无需构建期配置**)→ `chat.login({ userID, userSig })`
- **`userID` 必须是 `u{user_id}`**(跨栈契约,与 `accounts/models.py::im_user_id` 一致),否则消息与 App 对不上
- 事件映射(对应 App 的 `ImEvent`):

| SDK 事件 | 对应 | 处理 |
|---|---|---|
| `OnMessageReceived` | `ImNewMessage` | 上屏 + 未读 + 会话置顶 |
| `OnConversationListUpdated` | `ImConversationsChanged` | 重拉会话列表 |
| `OnKickedOffline` | `ImKickedOffline` | 全屏提示 + 清凭证 |
| `OnUserSigExpired` | `ImSigExpired` | 重取 userSig 并重登 |

- 消息能力:文本、表情、图片(浏览器原生 `File`/`Blob` **直传**)、历史拉取、删除本地消息、会话已读清理、删除会话
- 复用后端已有的「配对灰条 / 封禁灰条 / 举报处理通知」自定义消息语义与文案
- 未读数、45 秒在线心跳阈值与 App 保持一致

## 6. 版式与交互

### 6.1 手机 / PC 判定:按设备,**不用像素断点**

读 `navigator.platform` + UA + `maxTouchPoints`(与 Flutter 的实现同判据,含「iPad 伪装 Mac」的处理,见 `flutter/bin/cache/flutter_web_sdk/lib/ui_web/ui_web/browser_detection.dart:150-187`):

- **移动端浏览器** → 引导页(见 6.5),**无论窗口多宽**
- **桌面浏览器** → PC 壳层,**无论窗口拖到多窄**(不再有像素断点拦人)

### 6.2 PC 壳层:可拖拽侧栏

```
┌──────────┬────────────────────────────────────────┐
│ ♥ 心跳    │                                        │
│ ▸ 发现    │        ┌──────────────┐                │
│ ▸ 消息 ③  │        │   照片卡片     │                │
│ ▸ 广场    │        └──────────────┘                │
│ ▸ 我的    │      ✕ 不喜欢      ♥ 喜欢              │
│ ⚙ 设置    │                                        │
│ ◉ 阿泽    │                                        │
└──────────┴────────────────────────────────────────┘
   ↑ 可拖拽          内容区吃满剩余空间
```

| 行为 | 规则 |
|---|---|
| 默认宽度 | 窗口宽 × 16%,夹在 **208–264px**(比例进 token) |
| 可拖范围 | **72–360px**;手柄在右边缘,悬停变 `resizeLeftRight` 指针 |
| 显示模式 | 宽度 **≥ 176px** → 图标 + 文字;不足 → **只显示图标**(悬停 tooltip 出名称) |
| 记忆 | 拖过的宽度存 localStorage,下次打开沿用 |
| 恢复默认 | **双击边缘** |

侧栏分四段:品牌区 / 导航四项 / 设置入口 / 我(头像+昵称)。**选中态是这一屏唯一高音**(brand 主色 + 浅色圆角底),其余走中性色。未读角标复用消息页样式。

### 6.3 自适应规则(全部随窗口,无固定画布)

| 区域 | 规则 |
|---|---|
| 内容区 | 吃满剩余空间,不居中留白 |
| 发现卡片 | 按**可用高度**算卡片尺寸(保持现有卡片比例),窗口矮则整体缩小 |
| 消息页 | 会话列表 = 窗口宽 × 22%(夹 264–360px);聊天区吃满剩余;**气泡最大宽沿用比例值 72%** |
| 广场 | **列数随宽度自适应**(单卡最大宽 ≈ 520px):1920 → 3 列,1440 → 2 列,更窄 → 1 列 |
| 登录 / 引导 / 资料编辑 / 设置 / 协议 | 居中卡片,宽度 = 窗口宽 × 32%(夹 420–520px) |

### 6.4 鼠标 / 键盘带来的交互升级(手机没有的维度)

| App(触屏) | Web(鼠标 + 键盘) |
|---|---|
| 长按消息出菜单 | **悬停出 ⋯ 按钮 + 右键菜单**(两种都提供) |
| 点名字看资料 | **悬停照片浮出「查看资料」** + 点名字(保留) |
| 拖动卡片滑卡 | 拖拽 **+ 键盘 `←`/`→`** + 点击两个圆钮(三种都提供) |
| 点照片全屏 | 灯箱:**点遮罩或 `Esc` 关闭** |
| — | 新增 **hover 态** token;键盘**焦点圈**用中性色 2px(**不用 brand**,避免一屏两个高音) |

列表滚动、文本选中复制、输入法、右键均为浏览器原生行为。**不做完整无障碍适配**(仅保证 Tab 可达 + Enter 激活),列为取舍。

### 6.5 移动端引导页

```
┌──────────────────────────┐
│         ♥ 心跳            │
│   请在电脑上打开网页版      │
│   手机上请使用「心跳」App    │
│   [ 下载 App · 敬请期待 ]  │  ← 禁用态;开关做成常量,商店上架后一行改
└──────────────────────────┘
```

## 7. 视觉纪律:「心跳」token 的双份维护

| App(Dart 常量,权威) | Web(CSS 变量) |
|---|---|
| `app/lib/core/theme/app_colors.dart` | `web/src/styles/tokens.css` → `--color-*` |
| `app/lib/core/theme/app_gradients.dart` | `--gradient-*` |
| `app/lib/core/theme/app_typography.dart` | `--font-*` / `--text-*` |
| `app/lib/core/theme/app_spacing.dart` | `--space-*` |
| `app/lib/core/theme/app_radius.dart` | `--radius-*` |
| `app/lib/core/theme/app_motion.dart` | `--motion-*` |
| `app/lib/core/theme/app_shadows.dart` | `--shadow-*` |

**纪律(与 CLAUDE.md 同步落条)**:

1. **改任何视觉 token,必须在同一次改动内改两份**(Dart 与 CSS),否则两端走样
2. Web 端新代码**禁止裸 hex / 裸字号 / 裸间距**;比例值也进 token(如 `--sidebar-ratio: 16%`)
3. 字体:Space Grotesk(拉丁/数字)+ 中文系统 fallback,与 App 一致;图标统一 Material `*_rounded`(Web 端用图标字体或 SVG,保持一致)
4. 动效三档与 reduced-motion 尊重:`prefers-reduced-motion` 替代 App 的对应开关

## 8. 功能对等清单(11 模块)

| 模块 | 内容 |
|---|---|
| 登录 | 手机号 + 验证码、60 秒重发倒计时(42901 带 `Retry-After`)、连错 5 次锁 15 分钟(42902)、首启协议弹窗 |
| 引导 | 资料完善(昵称/性别/生日/城市/简介/12 标签)、`missing_fields` 缺项提示、未满 18 岁拦截(400) |
| 发现 | 候选卡(默认 10/上限 20)、滑卡(拖拽/键盘/圆钮)、限流 300/小时提示、互喜**配对情感时刻**、配对列表分页 |
| 消息 | 会话四态(骨架/空态/错误重试/正常)、最近联系人横滑条、系统通知置顶、未读角标、被顶号全屏提示 |
| 聊天 | 历史消息、文本/表情/图片、时间条(间隔 > 5 分钟)、长按菜单(改右键)、失败重发、系统灰条、已读清理、删除会话 |
| 广场 | 动态流(自适应多列/分页)、发布带图、动态详情、评论(分页)、点赞/取消、我的动态、删除我的动态、举报动态 |
| 我的 | 资料查看与编辑、照片网格(最多 6 张 / ≤5MB / 审核状态)、择偶偏好(性别/年龄区间/城市) |
| 设置 | 设置页、拉黑列表(分页)、退出登录 |
| 举报拉黑 | 举报用户(20/天)、拉黑/解除拉黑、拉黑后双向不可见(资料 404) |
| 在线状态 | 在线光、`GET /presence` 批量查询(120 秒内有认证请求 = 在线);**心跳规则见下** |
| 协议 | 用户协议 / 隐私政策全文页,未登录可公开访问 |

**在线心跳规则(Web 与手机不同,必须明确)**:页面**可见时**每 45 秒发一次认证请求维持在线(与 App 阈值一致);`document.hidden` 时**暂停**心跳(不假装用户还在),重新可见时**立即补发一次**。理由:浏览器标签页常被长期挂在后台,若照常心跳会让「在线」失真,直接影响滑卡配对的可信度。

## 9. 与 App 的行为差异(完整清单)

1. 被顶号提示改为**全屏**提示(浏览器无推送渠道)
2. 消息菜单**同时支持右键**
3. 滑卡**支持键盘 `←`/`→`**
4. 聊天图片本地预览用 `URL.createObjectURL` 生成的 blob 地址,不涉及文件路径
5. 移动端浏览器访问 → **引导页**(不提供手机网页版)
6. 无推送通知:新消息只在页面内提示(未读角标 + 会话置顶)

## 10. 测试与门禁

| 层 | 内容 | 门禁 |
|---|---|---|
| 类型检查 | `vue-tsc --noEmit` | **零错误**(对应 `flutter analyze` 零告警) |
| 代码规范 | ESLint + Prettier | 零错误 |
| 组件/单元 | Vitest + @vue/test-utils + MSW | 全绿 |
| 端到端 | Playwright 打真后端 | 主干流程全过 |
| 后端 | **不跑、不改** | 无接口变更,`ApiDocsCoverageTests` 不受影响 |

**单元/组件测试覆盖重点**:401 刷新通道(含并发去重)、40101 被顶号、**IM 踢出原因分流(多端清凭证 / 同端多标签只重连)**、错误契约解析(含 `request_id`)、滑卡状态机、会话四态、未读聚合、UA/设备判定、侧栏拖拽几何与记忆、**token 对照测试**(解析 `app/lib/core/theme/*.dart` 的常量与 `tokens.css` 的变量,比对色值/间距/圆角数值是否一致)。

**Playwright 端到端场景**:登录 → 引导完善资料 → 滑卡 → 互喜配对 → 聊天发文本与图片 → 广场发布与评论 → 拉黑;另含:深链直开与 F5、中文渲染自检、窄屏/UA 引导页、被顶号全屏提示、**第二个标签页登录不清掉第一个标签页的登录态**(§5.3 的踢出原因分流)。

## 11. 部署

- 构建:`npm run build` → `web/dist`(纯静态)
- nginx(服务器目录与域名路径**上线时确认**):静态直出 + `try_files $uri $uri/ /index.html`(深链与 F5 不 404)+ 反代 `/api/v1`、`/media/`
- **同域部署 ⇒ 不需要 CORS**:`chatapp/config/settings.py:231-235` 现有 `CORS_ALLOWED_ORIGIN_REGEXES`(仅 localhost/127.0.0.1)保持不动,后端零改动
- 开发期:Vite dev server 代理到 `http://127.0.0.1:8000`,本地联调不涉及跨域
- **两段式上线**:备案前 `http://<SERVER_IP>/`(仅内部验收)→ 备案通过后切域名 + 证书;`/media/` 直出与 vhost 对齐一并补(此前排查已记录域名站点缺 `/media/` 直出)
- 已知外部约束:腾讯云 IM **体验版上限 100 用户**,商店上架前须采购专业版(既有上线流程表的约束,本设计不改变)

## 12. 实施分组与任务量

一个实施计划、**10 个组**、每组「类型检查零错误 + 测试全绿」再进下一组:

| 组 | 内容 | 估任务数 |
|---|---|---|
| T1 | 工程骨架 + **心跳 token 移植** + 基础组件(按钮/输入/卡片/头像/空态/错误态/骨架/角标) | 6–8 |
| T2 | 网络层 + 鉴权(401 刷新通道、错误契约、会话 store)+ 登录页 + 协议页 | 5–6 |
| T3 | 路由 + 守卫 + **PC 壳层(可拖拽侧栏)** + 自适应布局 + 移动端引导页 | 5–6 |
| T4 | 引导与资料(编辑 / 照片 / 偏好 / 我的) | 5–6 |
| T5 | 发现与配对 | 4–5 |
| T6 | 聊天(IM 接入 + 会话列表 + 聊天页) | 7–9 |
| T7 | 广场(流 / 发布 / 详情 / 评论 / 点赞 / 我的动态) | 5–6 |
| T8 | 设置 / 拉黑 / 举报 / 在线状态 | 3–4 |
| T9 | 测试补齐 + Playwright 端到端 + CI job | 4–5 |
| T10 | 部署手册补充 + `docs/pitfalls/web.md` + CLAUDE.md 立 token 双份纪律与目录说明 | 3 |

**合计约 47–58 个任务**;这是本项目至今最大的一块工作(与 App 端 8.8k 行 Dart 同量级)。

## 13. 关键决策记录

| 决策点 | 结论 | 依据 |
|---|---|---|
| 目的 | 功能对等的完整网页版产品 | 用户选(否决「只做分享落地页」「只做调试版」) |
| 设备 | PC 浏览器优先 | 用户选 |
| 交付节奏 | 不分批,一次做完;计划内部 10 个检查点 | 用户选 |
| 登录共存 | **保持单设备**,网页登录顶掉手机,后端不改 | 用户选(否决「按端隔离」「完全放开多设备」) |
| 技术路线 | 原定 Flutter Web → **实测否决 → 改 Vue 3** | §2 证据链 |
| 框架 | Vue 3 + Vite + TypeScript | 用户选 |
| IM | 无头 `@tencentcloud/chat`,**不用官方 UIKit** | 避免聊天页与「心跳」两张脸 |
| 移动端 | **不做手机网页版**,按设备判定给引导页;下载按钮「敬请期待」 | 用户选 |
| 布局 | 随窗口自适应,**不用像素断点**;广场自适应多列 | 用户明确要求 |
| 侧栏 | **可手动拖拽拉伸**,超过阈值显示图标+文字 | 用户明确要求 |
| 样式方案 | 原生 CSS + CSS 变量,**不用 Tailwind** | 与 token 纪律冲突 |
| 工程位置 / 包管理 | `web/` + npm | 用户确认 |
| 部署细节(目录/域名) | **上线时确认**,设计只约束 nginx 能力 | 用户确认 |

## 14. 改动面

| 文件 / 目录 | 动作 |
|---|---|
| `web/` | **新建**(整个前端工程) |
| `.github/workflows/web.yml` | 新建 CI:npm ci + vue-tsc + lint + vitest + build |
| `CLAUDE.md` | 新增「网页端」目录说明 + **token 双份维护纪律** + 常用命令 |
| `docs/pitfalls/web.md` | 新建:Web 端踩坑(逐步沉淀) |
| `docs/pitfalls/README.md` | 导航行补 `web.md` |
| `README.md` | 补网页端一节(技术栈、启动命令、部署) |
| `app/`、`chatapp/`、`docs/api/` | **零改动** |

## 15. 非目标 / 已知取舍与风险

**非目标**:手机浏览器适配;暗色模式;SSR / SEO / 分享卡片;Web 推送与离线消息;多设备同时在线;官方 IM UIKit;完整无障碍适配;音频/视频消息;英文版。

**已知取舍**:

- **token 双份维护**是换框架后的唯一长期成本,靠纪律 + 对照测试约束,不靠自觉
- 首屏比 Flutter Web 轻得多、且无 CanvasKit/中文字体问题,但**没有 SEO**(SPA)
- 单设备登录保持现状 ⇒ 用户在电脑上用网页时手机端会被顶下线,这是明确接受的产品行为

**风险**:

| 风险 | 应对 |
|---|---|
| 规模大(47–58 任务),中途易失焦 | 10 个检查组,每组门禁「类型检查零错误 + 测试全绿」才推进 |
| `@tencentcloud/chat` 与 Flutter 插件 API 有差异,聊天是最大不确定项 | **T6 第一个任务先做通路验证**:浏览器里完成 `登录 → 收到消息 → 发出消息`,通过再继续 |
| 两端视觉走样 | token 对照测试(§10)+ CLAUDE.md 纪律 |
| 备案未通过导致无法公开访问 | 两段式上线:先在 IP 上验收,域名阶段再公开 |
| IM 体验版 100 用户上限 | 属上线采购事项,不在本设计范围,但需在部署手册中标注 |

## 16. 验收标准

1. 11 个模块功能在 PC 浏览器上全部可用,主干流程走通(登录→引导→滑卡→配对→聊天→广场→拉黑)
2. `vue-tsc` 零错误、ESLint 零错误、Vitest 全绿、Playwright 主干场景全过
3. 深链直开与 F5 不 404;刷新后登录态保持
4. 中文字体、图标、动效正常;窗口拉伸下版式自适应无破版;侧栏拖拽与记忆正常
5. 移动端浏览器打开为引导页(用真机或 UA 覆写实测)
6. `app/`、`chatapp/`、`docs/api/` 无改动(`git diff` 可证);后端全量测试仍绿
7. 服务器 IP 上可访问并完成一轮手测;部署手册、`docs/pitfalls/web.md`、`CLAUDE.md`、`README.md` 更新完毕
