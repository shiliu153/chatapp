# 交友软件 MVP 设计文档

日期:2026-09-09
状态:已与用户逐节确认,待用户终审

## 1. 背景与目标

开发一款**轻约会 + 泛社交**交友 App(国内正式上架为目标)。MVP 核心闭环:

注册登录 → 完善资料 → 卡片浏览/喜欢/跳过 → 互相喜欢(配对)→ IM 聊天

匹配机制:**用户自设"想找的人"偏好**(目标性别/年龄区间/城市),未设置时随机推荐兜底。

### 非目标(本期不做)
动态广场、语音/视频通话、会员付费、礼物、距离定位推荐、复杂推荐算法、iOS 打包(Windows 环境无法构建,列入 M4 决策点)。

## 2. 约束条件

- 开发者状态:Solo,**Flutter/Django 均为新手**,需要教学式分步指引
- 资质现状:无任何账号资质,**边开发边办**(腾讯云 IM、短信、内容安全、域名备案等)
- 开发机:Windows 11,本机已装 MySQL
- 交流语言:中文
- 仓库内 `flutter/` 为 Flutter SDK 源码(3.47.2 stable,自带独立 git),不是应用代码

## 3. 架构方案(已选定:方案一)

**单体 Django 后端 + 腾讯云 IM 只做消息通道,业务数据全部自管。**

- 自己管:账号、资料、喜欢/跳过、配对关系、审核、封禁
- 腾讯云 IM 管:聊天消息收发、存储、未读数、会话、多端同步
- Flutter 端 IM SDK(tim_plus_flutter)**直连腾讯云 IM**,消息不经自有服务器
- 聊天是核心卖点,会话列表数据源 = IM 会话;配对成功以 IM 自定义消息(TIMCustomElem)在双方会话中插一条居中"灰条"引导,会话随之自动创建

## 4. 仓库布局

```
chat_app/                # git 仓库根(已 init)
├── app/                 # Flutter 应用(M0 用 flutter create 新建)
├── chatapp/             # Django 项目根(manage.py 所在层)
│   ├── config/          # settings.py / urls.py(django-admin startproject config .)
│   ├── accounts/ users/ discovery/ im/ moderation/   # 5 个业务 app
├── flutter/             # Flutter SDK 源码 — git 忽略,勿动
├── docs/superpowers/specs/   # 设计文档
├── .remember/           # Claude 会话日志 — git 忽略
└── CLAUDE.md
```

## 5. 技术选型

| 层 | 选型 |
|---|---|
| 后端 | Django 5.x + Django REST Framework + SimpleJWT |
| 数据库 | MySQL 8(开发/生产一致) |
| 缓存 | Redis(开发期仅验证码与限流用;如不愿装可先用缓存后端缓存代替,上线前必须 Redis) |
| 前端 | Flutter 3.47(Dart 3.13)+ Riverpod + go_router + dio + tim_plus_flutter |
| 本地存储 | shared_preferences(access/refresh token、userId、userID→资料缓存) |
| 照片 | MVP:上传到 Django(media/);预留接口,M4 前切腾讯云 COS 直传 + CDN |
| 短信 | 开发期模拟验证码(固定码+日志);上线接腾讯云 SMS |
| 图片审核 | 开发期 AUTO_APPROVE=True;上线接腾讯云内容安全 API |
| 密钥管理 | 全部环境变量(.env 不入库);App 端只持有公开 SDKAppID,userSig 每次向后端换取 |

## 6. 数据模型

### accounts
- `User`(自建,手机号唯一登录,`username` 不用,`IM userID = "u{id}"`):phone、created_at、is_active

### users
- `Profile`(1:1 User):nickname、gender、birthday、city、bio、status(新注册未完善 → complete → banned_light / banned_heavy)
- `Photo`(FK User,1~6 张):file、order、status(pending/approved/rejected,审核表见 moderation)
- `Tag`:名称 + icon(内置池,后端维护);`Profile.tags` M2M
- `Preference`(1:1 Profile):target_gender(可空=不限)、age_min/max、city(可空)
- 年龄规则:`birthday < 18 岁 → 拒绝注册`(合规底线,发生在首次资料引导填生日环节)

### discovery
- `Swipe`(swiper FK、target FK、action=like|pass、created_at;唯一约束 (swiper, target))
- `Match`(user_a、user_b 有序唯一、created_at)—— 互喜同事务创建

### im
- 无核心模型(IM 账号映射即 User.id);存 im_config 不入库 —— SDKAppID/Key 在 settings 环境变量
- 职责:userSig 签发、注册时 account_import、配对灰条消息发送、回调接收端点(预留)

### moderation
- `Report`(reporter、target、type=骚扰/色情/诈骗/其他、detail、status=待处理/已处理、处理备注)
- `Block`(blocker、blocked 唯一约束;拉黑同时调用 IM 黑名单接口,MVP 有 UI 层兜底)
- 封禁状态落在 User/Profile 上(轻:禁滑卡;重:拒签 userSig + 业务 403),带 reason 审计

## 7. 核心业务流

### 7.1 注册/登录(验证码式,无密码)
1. `POST /api/v1/auth/sms/send {phone}` — 开发期模拟验证码(固定 123456,配置开关);上线换真实短信
2. `POST /api/v1/auth/sms/verify {phone, code}` — 校验通过 → 无此号自动建 User → 返回 JWT(access 短 + refresh 轮换)+ is_new_user
3. 注册时异步调 IM REST `account_import` 导入 `u{id}`(失败不阻塞,记日志重试;控制台若开"自动注册"可省)
4. 聊天前 `POST /api/v1/im/user_sig` 取 userSig → IM SDK 登录;业务 JWT 与 IM 登录解耦,IM 掉线自动重登;封禁用户签发前被拦

### 7.2 资料完善(未完成禁止滑卡)
- 昵称/性别/生日/城市/简介 + 标签(多选,`GET /users/tags` 拉池)+ 上传 1~6 照片
- Profile.status 未 complete → 滑卡接口 403
- 登录态首页 Tab 仍可用(我的页),卡片 Tab 显示引导完善

### 7.3 滑卡与配对
1. `GET /api/v1/discovery/candidates` 批量候选(默认 10/批):排除自己、已 Swipe、已 Match、我拉黑的人;按 Preference 过滤(空则随机);响应含对方 id/昵称/年龄/城市/标签/照片
2. `POST /api/v1/discovery/swipe {target_user_id, action: like|pass}` → 记 Swipe(**同目标重复提交幂等**);like 且对方已 like 我 → 同事务创建 Match → `{matched: true}`
3. matched 瞬间:后端 IM REST API 以双方身份互发 `TIMCustomElem{type:"match_notice"}` → 双方聊天页渲染居中灰条"你们已互相喜欢,开始聊天吧";IM 会话自动创建并出现在双方会话列表
4. 开聊为标准 C2C 单聊,无需好友关系(控制台"非好友单聊"默认开启)

### 7.4 会话列表与聊天
- 会话列表数据源 = IM 会话(未读/最后消息由 IM);App 端用 `userId → {昵称, 头像}` 本地缓存渲染(启动 + 配对时预热,来源:`GET /api/v1/matches`)
- 聊天页 = tencent_cloud_chat_sdk 底层 API 自绘气泡(不用官方 UIKit:黑盒、定制成本高);客户端拦截 TIMCustomElem 渲染灰条,不进普通消息流
- 点头像 → `GET /api/v1/users/{id}` 公开资料卡,内含举报/拉黑入口

### 7.5 退出/切换账号
- 业务退出清 JWT ≠ IM 登出清 userSig;**切换账号必须先全清**(防 IM 串号:IM 账号绑定设备会话,登出不清会导致下一账号收到上一账号消息)

## 8. 审核与合规(MVP 必含)

- 图片:Photo.status 三态;开发 AUTO_APPROVE=True;上线:上传即调内容安全 API,通过才公开,驳回引导换图;审核服务不可用 → 降级"待审不公开 + 人工后台处理"
- 文本:昵称/简介过内置基础词库;上线前换腾讯云文本审核 API
- 人工后台:Django admin 定制审核台(照片通过/驳回、举报队列、封禁操作)
- 举报:用户页/聊天入口可举报(骚扰/色情/诈骗/其他)→ Report 队列
- 拉黑:业务 Block + IM 关系链黑名单(IM 侧拦截能力以腾讯云控制台当前配置为准,实施时对照官方文档确认,MVP 有 UI 兜底)
- 封禁两级:轻(禁滑卡)/ 重(拒签 userSig + 业务 403),带 reason
- 防未成年人:注册填生日,<18 拒绝
- 用户协议 + 隐私政策:MVP 提供文本草稿(收集手机号用途、照片审核说明),上架前核对修订

## 9. Flutter App 结构

```
app/lib/
├── main.dart / app.dart     # 入口、go_router 路由表、主题
├── core/                    # dio 实例(JWT 拦截器:401→refresh→重试一次)、
│                            # token 存取、环境配置(--dart-define: SDKAppID/API_BASE)、错误映射
├── im/                      # IM 抽象层(M2c 落地):im_client.dart 领域模型+ImClient 接口、
│                            #   tencent_im_client.dart 唯一 SDK 适配、im_repository.dart(userSig/matches)、
│                            #   im_manager.dart 登录生命周期与自动重登;测试用 FakeImClient
└── features/
    ├── auth/                # 手机号登录(验证码页)、启动鉴权
    ├── onboarding/          # 首次资料引导:昵称/生日/城市/标签/照片
    ├── discovery/           # 卡片流(滑动 like/pass)、配对成功动效、对方资料卡
    ├── chat/                # 会话列表、聊天页、match_notice 灰条、举报/拉黑
    ├── profile/             # 我的资料查看/编辑
    └── settings/            # 退出登录
```

主框架:底部三 Tab — 发现 | 会话(未读角标)| 我的。启动流程:本地 refresh token → 无:登录页;有:静默换 access → IM 初始化 → 主框架。

## 10. 错误处理与安全

- API 统一 `{code, message}`;客户端处置:401 静默刷新重试→失败踢回登录;403 提示(未完善资料/封禁);429 操作太快;网络失败引导重试
- 验证码:6 位、5 分钟有效、60s 重发间隔、5 次错误锁 15 分钟
- 敏感配置全部环境变量;隐私:喜欢/划过不可见、详情只回公开字段;IM 回调验签;上线 HTTPS
- 限流:django throttling 覆盖验证码与滑卡接口

## 11. 测试策略

- 后端(核心):注册登录流、滑卡幂等、**并发互喜配对只成功一次(事务+唯一约束)**、照片审核状态流转、封禁拦截;外部依赖(IM REST/审核 API)mock
- 前端:repository/状态单测(mock dio)、登录页与配对按钮 widget 测试;聊天 UI 靠双设备手动联调清单
- 纪律:每模块后 `python manage.py test` + `flutter analyze` 零告警

## 12. 里程碑(教学式分步,每个 M 结束都有可运行产物)

| 里程碑 | 内容 | 外联并行事项 |
|---|---|---|
| M0 地基(1 周) | git init ✓;Django + MySQL + 5 apps 骨架;`flutter create app/`;两端 /health 打通 | **立即注册腾讯云开通 IM 体验版拿 SDKAppID** |
| M1 后端全量 | accounts → users → im(userSig/导入/灰条消息)→ discovery;接口+测试全绿 | — |
| M2 前端全量 | 登录→引导→卡片→配对→会话→灰条聊天;双设备真机互滑互聊通过 | Apple 开发者账号、软著材料 |
| M3 合规收尾 | 审核台、举报拉黑联调、协议文本、封禁、<18 拒绝;Android 签名 APK 真机测试 | **ICP 备案提交(周期最长)** |
| M4 上线 | 服务器+域名部署;短信/内容安全/COS 接真;商店上架 | iOS 打包决策(Mac 或云打包) |

纯开发量估计 6~10 周(含新手余量)。

## 13. 风险与未决事项

- IM 黑名单/消息限制的最终能力取决于腾讯云控制台当前版本配置 → 实施该步骤时先查官方文档
- account_import 与"自动注册"二选一,以控制台实际可用为准
- iOS 上架需要 Mac 或云打包(如 Codemagic),M4 前决策;MVP 主攻 Android
- 内容安全、短信的申请与审核在腾讯云侧有时长,M4 任务不阻塞 M0-M3 开发(全部留开关与接口)
- 隐私政策/用户协议为草稿,M4 需按商店与法规核对
