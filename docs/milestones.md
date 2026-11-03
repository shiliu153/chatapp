# 里程碑时间线

> 本文件是项目的**完整交付时间线**,从 `CLAUDE.md` 外迁而来(2026-11-03),以控制 CLAUDE.md 的体积。
> 每条里程碑对应一份已归档的 spec + plan,见 [`docs/superpowers/README.md`](superpowers/README.md) §4 归档清单;
> 代码级证据以 `git log` 为准。
>
> **当前待办**见 [`docs/backlog/2026-11-03-todo.md`](backlog/2026-11-03-todo.md)。

## 阶段总览

M0–M3 与后续七次追加均已交付(各有 spec+plan);当前处于 M4(上线运营)。

| 阶段 | 一句话 |
|---|---|
| M0–M2 | 地基 / 后端全量 / 前端全量(登录→卡片→配对→IM 聊天) |
| M3 | 合规:审核台 / 举报拉黑 / 重封禁 403 / 协议弹窗 / 签名 APK |
| 后 M3 ①–③ | ops 审核台 / 封禁系统消息+消息页改版 / 微信式聊天+资料页(IM 昵称同步) |
| 后 M3 ④–⑦ | 单设备登录+造数 / 举报处理通知 / 广场页(动态流)/ 在线状态(自建 presence) |
| **M4 第一步** | **服务器跑通**(宝塔全托管,IP:80 测试,双模拟器手测通过) |

## 详细时间线

| 日期 | 交付内容 |
|---|---|
| 2026-09-15 | 「心跳」UI 设计规则 v1(常驻强制,见下节) |
| 2026-09-18 | UI 整改批次①「底座+底栏」交付(Space Grotesk/主题 token/8 组件/悬浮胶囊底栏;220 测试绿) |
| 2026-09-19 | UI 整改批次②「发现页」交付(页壳/卡面/圆钮/配对情感时刻/涟漪空态;233 测试绿) |
| 2026-09-19 | UI 整改批次③「消息/聊天」交付(消息页四态/横滑条/通知行/会话行;聊天页顶栏 62/气泡/输入栏/双气泡空态/骨架/错误重试;提炼 AppErrorView 与 AppAvatar 首字占位;247 测试绿) |
| 2026-09-21 | 接口文档体系交付(`docs/api/` 十册 · 32 接口 · 腾讯云风格;`ApiDocsCoverageTests` 双向门禁强制「改接口必改文档」) |
| 2026-10-05 | 网页端(PC Web)立项:实测否决 Flutter Web → 改 Vue 3;T1–T8 交付(壳层/鉴权/资料/发现配对/聊天/广场/设置) |
| 2026-10-12 | 网页端收尾 T9–T10:覆盖率门槛(85.6/81.0/81.2/87.4)、Playwright 端到端 8 条、Web CI、web 踩坑分册、部署核对单;期间修两个真 bug(新用户不进引导页 / `account_import` 清空 IM 昵称头像) |
| 2026-10-12 | UI 整改批次④「我的 + 他人资料页」交付(我的页身份卡+完成度环/行数 8→5;资料页照片头图+透明顶栏+相册 R12;**首次落地 §6.2 Hero 转场**——tag 按来源自身 id 派生经路由 `extra` 传递,接入广场卡/详情作者/详情评论/聊天顶栏四处;聊天顶栏补头像 32 修订附录 B.2;资料页接入在线状态;规则文档升 v1.3 附录 C;278 测试绿) |
| 2026-10-12 | UI 整改批次⑤「广场」交付(页壳大标题+涟漪空态+骨架+渐变 FAB/动态卡圆头像+九宫格 3 列+点赞脉冲/详情页自绘顶栏+44 评论栏/我的动态;**落地 §6.2 第二处 Hero「动态卡→动态详情」**——SDK 禁 Hero 嵌套 + 扫描只一次 → 状态切换双保 + `extra` 带 seed 直出真卡;删孤儿 `OnlineDot`;规则文档升 v1.4 附录 D;296 测试绿) |
| 2026-10-12 | UI 整改批次⑥「二级页」交付(**表单控件规范一次定死**:14 个 core 组件 + 2 个 feature 组件;10 页 = 登录/启动/引导/设置/黑名单/编辑资料/想找的人/发动态/协议/封禁;`AlertDialog`→`AppDialog`、`SnackBar`→`AppToast` 全量统一;抽共享 `AppSubPageBar` 取代两份私有顶栏副本;规则文档升 v1.5 附录 E;329 测试绿) |
| 2026-10-13 | 上线合规轨 T-17「账号注销入口」交付(`DELETE /users/me` = 手机号二次确认 + 立即硬删除全部数据 + 释放手机号;IM 侧新增 `account_delete` 与删号任务;App/Web 双端入口;隐私政策补注销路径、双端协议版本升 2;后端 360 / App 336 / Web 308 测试绿;PR #6 squash 合并 `f686bc2`;用户模拟器 + Web 手测通过)。同批顺带修既有偶发:`seed_fake_users` 会造出未满 18 岁账号(生日取「age 年前的随机月/日」,今年生日未过时 `calculate_age` 算成 age-1;概率约 2.2%/轮,曾把 CI 卡红) |
| 2026-10-20 | P1-1「喜欢我的人」交付(`GET /discovery/likes` + `/count`,口径与候选池共用 `likes_received_queryset`;App 发现页入口+列表页,Web `/likes` + store;回喜欢复用 `swipe`;接口 32→34,后端 392 / App 347 / Web 315 测试绿;PR #8 squash 合并 `b606f3e`) |
| 2026-10-20 | P1-2「设置页补齐」交付(新 `feedback` app + `POST /feedback` + ops 意见反馈队列;App/Web 设置页三段式 + 意见反馈页 + 通知设置只读骨架 + 关于页;版本号 App 常量守卫 / Web Vite 注入;接口 34→35,后端 409 / App 355 / Web 320 测试绿) |
| 2026-10-20 | P1-3「关系出口」交付(`DELETE /matches/{user_id}` = `Match` 软删除 + `unmatch_blacklist` 双向 IM 拉黑 + 滑卡防复活;App/Web 聊天页「⋯」+ 资料页入口 + 被解除后横幅/输入禁用;2 分钟内撤回消息(SDK 原生,双方置灰);接口 35→36,后端 420 / App 375 / Web 336 测试绿。**已读回执挂起**:腾讯 IM 旗舰版专享,当前体验版做不了) |
| 2026-10-20 | 广场评论「楼中楼」交付(`PostComment` 自引用 `parent` + `reply_to`,服务层把「回复的回复」归一到顶级评论;列表内嵌前 2 条回复 + `GET …/replies` 展开 + `DELETE …/comments/{id}` 删楼;回复即 @,IM 灰条提醒被回复者(`post_replied` 任务);App 楼层/回复态/删除 + Web 组件同步;接口 36→38,后端 440 / App 380 / Web 340 测试绿;PR #12 squash 合并 `8c428c3`;用户模拟器 + Web 手测通过) |
| 2026-10-21 | 自建 IM 交付(C++20 `imserver/`:WS 首帧 JWT 鉴权 + 会话级 seq + 幂等 + 离线补拉 + 已读/撤回/拉黑 + 内部 HMAC API;Django `IM_BACKEND` 双跑与按账号灰度;App/Web 双实现与图片入口隐藏;`GET /app/config` 最小版本拦截;接口 38→39,后端 450 / App 385 / Web 341 测试绿) |
| 2026-10-22 | 自建 IM **上服务器**:镜像 `imserver:ea8a91d` 容器化(`network_mode: host`,127.0.0.1:9100/9101),建 `chatapp_im` 库并迁移 v1;Nginx `/im/ws`+`/im/api/` 反代;Django 同步到 `ea8a91d`(git bundle,含 P1 功能与 3 个迁移);灰度 `7,8` 端到端过(鉴权/收发/ack/历史/已读/撤回/离线补拉/未读),非灰度账号仍走腾讯;部署细节见 `docs/ops/imserver.md` 与 rollout 核对单) |
| 2026-10-22 | 自建 IM **500 连接压测**:稳态 50 msg/s 经 nginx ack p99 93ms、RSS 22MB(门槛 200ms/300MB);压测暴露并修复两处服务端问题——`im_user` 每消息两次 `INSERT ... ON DUPLICATE KEY UPDATE` 的间隙锁(改进程内缓存 + `SELECT 1` 优先)、冷启动新会话并发死锁(1213/1205 重试 3 次),复测 1000 条突发 0 失败;新增 `IM_MAX_CONN_PER_IP`/`IM_AUTH_RATE`/`IM_AUTH_BURST` 与压测脚本 `imserver/scripts/bench_ws.py`) |
| 2026-10-22 | 自建 IM **吞吐优化**:prepared statement 按连接缓存(写语句 3 次往返→1 次)、收发双方 unread 合并为一条多行 INSERT、去掉消息前 `client_msg_id` 预查、用户画像进程内缓存、在线 Redis 写入按 30s 节流;1000 条突发 9.4s→4.7s(106→215 msg/s)。**2C2G 天花板 ~200–250 msg/s**(MySQL ~2000 SQL/s ÷ 每消息 ~7 条),再往上需升配 4C8G+ 或应用层批量提交;完整记录见 `docs/ops/imserver-throughput.md` |
| 2026-10-26 | 自建 IM 灰度收尾 + **连接池事故修复**:三项手测脚本化(`imserver/scripts/verify_graylist.py`,17 条断言:互踢 4001/封禁 40301+4003/拉黑 40302,实跑生产全过);同时发现**池不校验存活**导致 MySQL `wait_timeout` 后 IM 永久失联(10-22 晚起约 3 天,仅灰度测试号受影响,重启即恢复),修复为「空闲 ≥`IM_DB_IDLE_PING_MS` 先 ping、失败重连 + 连接级错误丢弃 + `run_db` 兜异常」,新增 DB 测试 `PoolReconnectsAfterServerKill`;镜像 `imserver:a2332dd` 已上线,`KILL` 全部池连接后 `readyz` 仍 200。历史消息由产品确认接受「切换点之前不可见」(测试阶段) |
| 2026-10-26 | 自建 IM **图片二期**交付(全量门槛最后一项):Django `POST /im/images` + `im.ChatImage`(随机文件名/240px 缩略图/EXIF 方向校正/30 次每小时);imserver `kind=3` + `IM_MEDIA_PREFIX` 前缀校验(防伪造外链)+ 顺带修「灰条历史丢 `custom.type`」;App/Web `sendImage` 与解析、`capabilities.image=true`、聊天选图 1920/80;ops `/ops/chat-images/` 人工抽审 + 举报详情带最近 7 天图片;后端 464 / App 389 / Web 347 / imserver unit 13 + db 10 测试绿。**遗留**:图片无机器审核(人工抽审兜底,上线阻断项)、URL 公开可访问(后续可换签名 URL) |
| 2026-10-27 | 自建 IM **语音消息**交付:Django `POST /im/voices` + `im.ChatVoice`(`ffprobe` 校验 1–60 秒、ffmpeg 统一转 m4a/AAC 单声道 16kHz、限流 60 次/小时、签名 URL 与 30 天清理);imserver `kind=4`(前缀校验 + 读时签名,`sign_media` 通用化);App `record`+`audioplayers` 按住说话/上滑取消/60 秒自动停/气泡播放,Web `MediaRecorder`+`Audio` 同交互;ops `/ops/chat-voices/` 试听抽审 + 举报详情带最近 7 天语音;接口 42→43,后端 499 / App 405 / Web 369 测试绿;imserver unit 20 + db 15 绿。**遗留**:语音与图片一样无机器审核(上线阻断项);服务器需装 ffmpeg(缺失时语音上传 503+`50302`) |
| 2026-10-27 | 自建 IM **语音上服务器**:Alibaba Cloud Linux 3 无 apt、dnf 源无 ffmpeg → 用 BtbN 静态包(经 `gh-proxy.com` 加速)只装 `ffmpeg`/`ffprobe` 到 `/usr/local/bin`;本地构建 `imserver:72ae6ea` 后 `docker save`+`scp`+`docker load`(2C2G 上不编译),并同步 `/www/server/imserver/.env` 的 `IMSERVER_IMAGE`(不同步会继续拉旧镜像);Django `migrate` 到 `im.0003_chatvoice`,Web dist 与签名 APK(`chatapp-1.0.0.apk`)同步上线;`.env` 显式配 `MIN_APP_VERSION`/`LATEST_APP_VERSION`/`APP_DOWNLOAD_URL`。端到端实测:上传 201 → 签名 URL 200 → 无签名 403 → WS u7 发语音 ack → u8 历史读回 `kind=voice` + 读时签名;`readyz=200`、清理 dry-run 含语音。期间修两个 **mock 掩盖的 MIME bug**:Dio 对 `.m4a` 发 `octet-stream`、Web Blob 带 `;codecs=opus`,服务端改为按主类型匹配 |
| 2026-10-27 | **聊天记录搜索**交付(`GET /im/api/search`):imserver `like_pattern` 关键词转义 + 迁移 v2(`im_conversation.user_b` 索引)+ `MessageRepo::search` / `MessageService::search` + 限流;App 搜索页 + 聊天页定位到消息,Web 同步实现;imserver unit/DB 测试补齐 |`n
| 2026-10-27 | 自建 IM **全量切换**:`IM_SELF_GRAYLIST=7,8` → `all` 并重启 web+celery;观察 30 分钟(18:06–18:35)30 次采样 `readyz=200`/`health=200`/`im_err=0`/`http5xx=0` 全绿,合成流量 u9→u8 **40/40 ack 成功**、RTT avg 45.4ms / p95 53.4ms,imserver 零 error;非灰度账号 u9 已返回 `backend=self` 且收发正常。回退方式:`IM_SELF_GRAYLIST` 改回 `7,8` + 重启 web/celery |
| 2026-10-28 | **安全审计整改 P0+P1 交付**(`fix/security-remediation`):S1/H2 短信按产品决定不修;H3 IM token 绑定 `sv` + `im_user.session_version` + 登录/`user_sig` 双同步;H4 `im_pair` 配对校验(未配对 40302、目标必须存在、每分钟配额、`known_` 上限)+ `im_sync_pairs` 回填命令;H6 后台登录锁定 + TOTP + IP 白名单;M1 `NUM_PROXIES`、M3/M4/L5 统一图片校验与 EXIF 剥离、M6 媒体签名 fail-closed、M10/M11/M12、L1/L2/L4;H5 生产默认 `AUTO_APPROVE=0`;H1/B8 HTTPS 开关与 nginx 安全基线。后端 545 / imserver unit 22 + db 18 + 集成全绿 |
| 2026-10-28 | **令牌硬化交付**(`fix/security-remediation`,审计 H1 剩余 + L8):Web 的 refresh 改走 `HttpOnly; SameSite=Strict; Path=/api/v1/auth/` Cookie(响应体不再返回 refresh、access 只留内存、新增 `POST /auth/logout`、60 秒轮换宽限防多标签互踢);App 令牌换 `flutter_secure_storage`(Keystore/Keychain + 老用户一次性迁移 + 失败降级);App 证书绑定 ISRG Root X1+X2 覆盖 HTTPS 与 WSS(release 默认 enforce,`tool/verify_pinning.dart` 对生产域名握手 200)。后端 573 / Web 371 / App 412 测试绿;**H1、L8 关闭** |
| 2026-10-28 | **M7 存储配额 + 候选池交付**(审计 M7):四类媒体单账号配额(`USER_STORAGE_QUOTA_MB` 默认 200,超限 413 + `41301`,检查在落盘前);`Photo.bytes`/`PostImage.bytes` + `media_bytes_backfill`;候选池改 `Profile.shuffle_key` 预计算随机列 + 池内抽样,不再 `ORDER BY RAND()`,新增 `refresh_shuffle_keys` 轮换;`media_cleanup` 清资料图/广场图孤儿、`media_disk_report` 磁盘告警(`--fail-over`)。后端 592 测试绿;**M7 关闭** |
| 2026-10-29 | **第二轮安全整改**(PR #20 squash 合并 `80340e7`):H-1/H-2/H-3 + M-1/M-2/M-3/M-6/M-7/M-8 + L-1/L-2/L-4/L-5/L-6/L-7;镜像 `imserver:80340e7` 已上线;运营首次进 `/ops/` 需重绑一次 TOTP(预期行为) |`n
| 2026-11-01 | **「谁看过我」交付**(`feat/profile-visits`):新表 `users.ProfileVisit`(`(viewer, owner)` 唯一、每人一行)+ `Profile.visits_hidden`;`GET /users/{id}` 顺带落库(Redis 30 分钟窗口去重 + 内层 savepoint 防毒化事务,失败只记日志不影响响应);`GET /discovery/visits` + `/count` 与「喜欢我的人」同口径(已配对的人由「我已划过」天然排除,不 join `Match`);App/Web 发现页双入口 + 访客页(行内可回喜欢)+ 设置页隐身开关;隐私政策补「访问记录」、双端协议版本 2→3;接口 43→45,后端 640 / App 431 / Web 379 测试绿;PR #21 squash 合并 `92e3194`。**已于 2026-11-01 上线**(`migrate` + `purge_profile_visits` 计划任务 03:50 + Web dist + 1.0.2 APK;版本号 PR #23 合并 `7f2d1ec`) |
| 2026-11-01 | **Docker Compose 一键部署脚本**入仓(`deploy/oneclick.sh` + `deploy/docker/` 全套),作为宝塔形态之外的第二条部署路径;后续第三轮整改在此基础上做非 root / 网络隔离 / 资源限制加固 |`n
| 2026-11-01 | **语音录音交互打磨**(PR #22 `c300582`):Web 改**点击式录音**(点开始 → 再点发送,可取消 / Esc)+ 补齐权限被拒 / 无设备 / 太短 / 发送失败四条错误路径;App 保留按住说话,录音逻辑抽成 `VoiceRecordController`;修掉四个缺陷(指针拖出后停不下来、失败静默、入口凭空消失、离页把没录完的语音发出去) |`n
| 2026-11-03 | **可观测性 + 容量工程 + 削峰**(PR #28 `7e2c684`):`/metrics`(只按路由模板打标签、令牌 + 回环限定)+ Prometheus / Grafana / Alertmanager / 企业微信 relay + 9 条告警 + MySQL 看门狗;JSON 日志 + Loki profile;候选池缓存(版本号失效 + 空值哨兵/单飞/抖动三防)+ 队列分级与 notify 限速;广场列表 10 万条 **3354ms → 77ms**;imserver 冷启动建会话死锁修复(旧实现 24–29/320 失败 → 0) |`n
| 2026-11-03 | **第三轮安全整改交付**(`fix/security-round3`,PR #30):C-1 部署默认值(`--allow-dev-sms` 默认关闭、公网/TLS 强制 `--admin-phone`、staff/superuser 禁短信登录 + `SMS_ALLOW_STAFF_LOGIN` 逃生阀);H-1 imserver `IM_INTERNAL_ALLOW`(来源网段 + HMAC,容器内回环假设不再成立);H-2 nginx 固定 `172.28.0.10`,可信代理不再信任整个 `/16`;M-1 维护加 `purge_profile_visits`;M-2 访客只对「完善 + 过审照片」落库 + 单 owner 上限 500;M-3 `visits` 120/h、`visits/count` 240/h;M-4 备份 `umask 077`+`600`;M-5 镜像非 root + `mem_limit`/`cap_drop`;M-6 `backend` internal 网络隔离 MySQL/Redis;M-7 域名白名单;L-1/L-3/L-6/L-9;顺带修 CI 缺 `packaging`(kombu redis transport 首次发任务即导入,缺它入队 503)。后端 693 / imserver 43+19 / Web 403 / App analyze 绿;PR #30 squash 合并 `c44035e`。**19:10–19:35 已上线生产**:后端 `bbc9206` + 新镜像 `imserver:bbc9206`(H-1/M-5 真正生效,日志 `internal_allow_ready rules=2`;无迁移,`migrate --check` 干净),脚本冒烟全绿(staff 短信 403、`/internal/send` 通、`im_sends_total{ok}` 计数、0 个 5xx)。**注意**:本轮 `imserver/src` 有改动,「只上后端代码」会漏掉 H-1;回滚点为代码 `0aded19` + 镜像 `imserver:8a7ef1a`(仍留在服务器上),记录见 `docs/superpowers/archive/plans/2026-11-01-security-round3.md` §H |
| 2026-11-03 | **压测写场景 + 2C2G 写路径基线**(PR #33 `f275e1a` / PR #34 `b4accaa`):`perf/run.py` 支持 `--headers-file` 多账号令牌与 `api_write` 场景(头的值不落盘)+ `manage.py perf_tokens` 库内签发;`POST /discovery/swipe` 20/50/100/200 并发 = **33.4 / 35.8 / 38.5 / 39.2 rps**、全程 0 个 5xx/429;同批记录**读基线漂移 −33%**(`app_config` 608 → 410 rps),`perf/baseline.json` 待重跑 |`n

| 2026-11-03 | **Web IM 断线静默修复**(backlog A-1 / 审查 N-1):服务端 75s 空闲踢出而 Web 只挂 `onFrame`,静置后前端仍显示 `ready`、对方新消息**静默丢失**;`SelfTransport` 加 `onClose`(挂 `ws.onclose`/`onerror`,本端主动关闭不上报)+ `SelfImClient` 25s 业务心跳(与 App 对齐)+ 独立 `disconnected` 事件(被顶号用 `suppressClose` 抑制,避免两标签互踢)+ 断线让挂起发送立刻失败;`stores/chat.ts` 1/2/4/8/16/30s 退避重连 + 重连后补拉会话与当前会话历史(`activePeerId`),`multiAccount`/`idle` 不重连、403 不重试;新增 7 条单测,Web 411 测试绿 + `vue-tsc`/`eslint` 零告警;PR #36 |

| 2026-11-03 | **社交列表索引整改**(backlog A-2 / 审查 N-2~N-5):`Swipe(target,action,-created_at,-id)` + `Match(user_b,unmatched_at)` + `Photo(status,user_id)` 三条索引(迁移 `discovery/0003`、`users/0007`);三处排除列表从「Python 拉 id 再 `__in`」改成 `NOT EXISTS`(`moderation.services.exclude_blocked`),`/matches` 改为先分页再组装。2 万用户实测:喜欢我 95.7→**32.0ms**、计数 92.0→**29.8ms**、访客 371.7→**105.0ms**(`type=ALL` 消失)、配对扫行数 2000→**101**(index_merge);查询预算门禁收紧(候选冷 18→13、配对 13→9)并新增「必须 EXISTS / 索引必须存在」两条断言;后端 703 测试绿;PR #37,数字与两个坑见 `docs/ops/scale-report.md` §6 |

| 2026-11-03 | **前端错误上报**(backlog A-4 / 审查 N-7):全仓此前 `sentry`/`bugsnag`/`rollbar` 零命中,白屏与 Flutter 崩溃在服务端指标里完全不可见。**没接第三方**(零成本、错误数据不出境),改为自建 `POST /api/v1/client-errors`(`telemetry` app,匿名可调 + 120 次/小时/IP + 字段长度上限)→ 单行 JSON 日志 `logger=chatapp.client_error` + `client_errors_total{platform}`;`request_id` 由响应头 `X-Request-Id` 串起前后端。Web 挂 `window.onerror`/`unhandledrejection`/Vue `errorHandler`(开关 `VITE_ERROR_REPORTING`,生产 1、开发/测试 0),App 挂 `FlutterError.onError`/`PlatformDispatcher.onError`(开关 `--dart-define=ERROR_REPORTING`,须早于 `runApp`);两端各 20 条配额 + 同 message 去重。实测一条报错 → 日志带 `request_id=demo-rid-123`、`/metrics` 出现 `client_errors_total{platform="web"} 1`;后端 709 / Web 422 / App 439 测试绿;PR #38 |

| 2026-11-03 | **封闭测试白名单关死注册面**(backlog B-1 / 审查 K-1「全项目第一风险」):现场确认生产 `.env` **连 `SMS_DEV_MODE` 这一行都没有**,`settings.py` 默认 `"1"` 静默接管 —— 运行时 `SMS_DEV_CODE=123456`,任何知道手机号的人都能登录该账号、读走全部聊天记录(30 个账号)。按「关死注册面」路线止血:`settings.SMS_PHONE_WHITELIST`(逗号分隔,**留空=不限制**)+ `accounts.services.ensure_phone_allowed()` + 新业务码 `40301`;`sms_send` 在发码前拦(不落码/不入队/不占 60 秒间隔)、`sms_verify` 再拦一次(纵深防御);文档同步 `docs/api/auth.md`、`conventions.md`、`.env.example`、`pitfalls/backend.md`。后端 715 测试绿。**已上线**:`.env` 显式 `SMS_DEV_MODE=1` + 白名单 30 个现有账号 → 部署 `c080e78`(连带 A-1/A-2/A-4,含 2 个纯索引迁移)→ 重启 web + worker;生产实测名单外发码/登录均 `403 + 40301`、名单内 `200`。**残余风险**:名单内仍是固定码,且 `403`/`200` 差异构成受 IP 限流约束的探测口子 —— 对外开放注册前必须做 B-1b(接真实短信商) | PR #39

## 怎么维护

- 新增一行:在该行对应日期位置插入,格式 `| YYYY-MM-DD | **主题**交付(关键文件 / 开关 / 测试数 / PR 号):一句话结论 |`;
- **同时**在 `docs/superpowers/README.md` §4 归档表补一行,并把 spec+plan `git mv` 到 `archive/`;
- CLAUDE.md 只保留「阶段总览」级别的摘要,不再堆砌细节。