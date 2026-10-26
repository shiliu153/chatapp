# 踩坑手册 · 腾讯云 IM 与聊天

> 索引见 [README.md](README.md)。动 IM / 聊天 / 消息页 / 单设备登录相关代码前,先过一遍本文件。

## 凭据与代码位置

- 凭据:`IM_SDKAPPID=1600161711`(公开,App 端也要用);密钥只在 `chatapp/.env`,**永不入代码/提交**。管理员账号 `administrator` 默认存在。
- userSig 生成:`chatapp/im/signature.py`(含 `decode_user_sig` 调试解码);REST 封装:`chatapp/im/client.py`(**对外永不抛异常**,失败返回 False 只记日志);副作用任务:`chatapp/im/tasks.py`。
- 客户端抽象:`app/lib/im/`(`tencent_im_client.dart` 是**全项目唯一 import SDK 的文件**)。

## userSig 生成(最大的坑)

腾讯用自家的 base64 变体,不是标准/URL-safe base64。正确流程:纯 JSON(ver/identifier/sdkappid/expire/time,sig 用**标准** base64 的 HMAC-SHA256)→ `json.dumps` → `zlib.compress` → 标准 base64 后替换 `+`→`*`、`/`→`-`、`=`→`_`;字符串会以 `*` `-` `_` 出现且不 strip 填充。2026-09-10 实测通过。

## REST 调用细节

- 格式:`https://console.tim.qq.com/v4/{service}/{command}?sdkappid=&identifier=&usersig=&random=&contenttype=json`(usersig 需 URL 编码)。
- ⚠️ `openim/sendmsg` 的 `identifier` **必须是管理员**(`administrator`),发送方靠 body 的 `From_Account` 指定;错用发送方身份 → `60010`。
- ⚠️ `im_open_login_svc/account_check` **别用来验签**:本应用下永远回 `70402 Invalid parameters`;验签一律用 `account_import`。
- ⚠️ 昵称同步接口是 `profile/portrait_set`(错名如 `profile_set_field` → `60008 request format error`);头像 Tag 必须是 **`Tag_Profile_IM_Image`**(写成 `Tag_Profile_IM_Url` → `40009 Invalid field`)。
- ⚠️ 管理员 kick:`im_open_login_svc/kick`(body `{"UserID": u}`),会作废该账号**所有历史 userSig** 并断开在线;**没有 `/logout` 接口**(调用回 60008)。

## 单设备登录(自研,不依赖腾讯)

- 产品规则:一个账号同时只允许一台设备在线,后登录的顶掉先登录的。腾讯控制台「单平台登录」实测**不可靠**(不下发踢信号),故自研。
- 后端:登录 `session_version+1` 写进 JWT claim,鉴权不一致回 **401 + `40101`**;重登写标记 `im:kick_pending:{uid}`(TTL 300s)+ 20s 兜底任务;`POST /im/user_sig` 见标记先**同步踢**再发新签名。
- ⚠️ **踢必须早于新设备建立 IM 会话**:做成「响应后异步踢」会把新会话一起踢掉,客户端误报「账号已在其他设备登录」(手测:登录后 1 秒内出现两次 `user_sig` = 被踢后静默重登)。不踢的话新设备 IM 登录被服务端拒绝(表现为 **6206**)。
- 客户端:`im_manager.dart` 对 **6206/70001** 重拉签名重试一次;被顶设备三条退出路径互为兜底——① `ImKickedOffline` 事件(即时,但腾讯下发不稳定)② 45s 登录态心跳 40101 ③ 下一次业务请求 40101。
- ⚠️ **40101 不能一刀切强退**:登录竞态中,旧令牌的在途请求会被拒——令牌 ≠ 本机当前令牌时,应**换新令牌重试**;凭证已空时收到 401 也要按被顶号收尾(否则前端兜底成「网络不给力」误导排查)。细节见 `app/lib/core` 与 [frontend.md](frontend.md)。
- 退出提示:`TokenStore.forceLogout(reason)` 记一次性原因,登录页首帧 SnackBar「账号已在其他设备登录,请重新登录」。

## 消息类型(自定义消息白名单)

- **配对灰条** `match_notice`:配对成功给双方各发一条,`Desc`=「你们已互相喜欢,开始聊天吧」;经 `im/tasks.py::send_match_notice` 队列发(同步发两条各 ~0.45s,配对弹窗被拖慢近 1s)。
- **封禁/解封** `ban_notice`(带 `level: light|heavy`)/`ban_lifted`:由 `moderation/services.py::log_ban_change` 入队;重封禁任务内**先发消息再踢下线**。
- **举报处理** `report_handled`:固定文案,不披露处罚细节;触发点 3 处(ops 已处理/快速封禁、admin save_model),全挂「首次处理」分支。
- **评论通知** `post_commented`:模板在 `im/client.py::POST_COMMENTED_TEMPLATE`;作者本人评论不入队。
- App 端拦截渲染:`tencent_im_client.dart::_kindOf` 白名单(归入系统通知灰条),**新增类型记得加**。

## Flutter SDK 客户端(tencent_cloud_chat_sdk 9.0.x)

- spec 早期写的 `tim_plus_flutter` 在 pub.dev **不存在**(已更正);只用底层 API,不引 `tencent_cloud_chat_uikit`。
- ⚠️ **构造 SDK 消息对象只能用 `V2TimMessage.fromJson({...})`**:默认构造函数会调 `TIMManager.getServerTime()` → 加载原生 dll → VM 测试直接崩。JSON 键名见 `test/im/tencent_im_client_test.dart`。
- ⚠️ **`V2TimImageElem.fromJson` 会读 `CommonUtils.appFileDir`**:VM 测试里构造图片消息前要 mock path_provider 通道 + `CommonUtils.init()`(见该测试文件 setUpAll)。
- 单聊 conversationID 前缀 `c2c_`;`sendMessage` 的 `id` 参数已废弃但 **web 分支只认它**,`id`+`message` 都传。
- 清未读用 `cleanConversationUnreadMessageCount`(`cleanTimestamp` 传最后一条的秒级时间戳 + `cleanSequence` 传 seq);废弃的 `markC2CMessageAsRead` 别用。
- `ChatMessage.timestamp` 统一毫秒(映射 SDK 秒 ×1000)。
- 该 SDK **无原生重发 API**:`ImClient.resend` 是默认实现 → 实现类必须 `extends ImClient` 而非 `implements`(implements 不继承具体方法)。
- 日志噪音:`E/imsdk ... community group not open |error_code:11000|` 无害(SDK 顺带拉群列表,本应用不用群),别当故障排查。
- 标题降级链:matchCache → IM 会话名(昵称同步后有效)→ 裸 id。

## 服务端资料同步(昵称 / 头像)

- 改昵称 → `im/client.py::set_profile_nick`(portrait_set);存量补 `python manage.py im_sync_nicknames`(幂等)。会话列表 `showName` 与聊天页标题兜底都靠它。
- 头像:照片过审(含 `AUTO_APPROVE=1` 上传即过审)→ `im/tasks.py::sync_profile(user, "avatar")`,绝对 URL 用 `MEDIA_BASE_URL` 拼。
- ⚠️ **改 `.env` / `im/tasks.py` 后 worker 必须重启**(env 与代码都只在进程启动时加载;踩过:runserver 自动重载而 worker 跑旧代码)。
- ⚠️ 换服务器/换域名后:改 `MEDIA_BASE_URL` → 重启进程 → 对全部有已过审照片的用户重刷一次头像(批量脚本见本节命令)。
- 系统通知账号 `system_notice`(昵称「系统通知」):新环境跑一次 `python manage.py im_setup_system_account`(幂等,已存在 7015 视为成功);缺失时封禁动作照常,只是消息发送失败记日志。

## 消息页 / 聊天页(前端细节)

- 消息页(2026-09-11 抖音式改版):最近联系人横滑条(前 10,不含系统通知)+「系统通知」置顶行 + 会话行;keys `chats.strip` / `chats.stripItem:{peerId}` / `chats.systemNotice` / `chats.tile:{peerId}`。`displayNameFor` 特判 `system_notice` →「系统通知」;**`systemNoticePeerId` 与后端 `im/client.py::SYSTEM_NOTICE_IDENTIFIER` 是跨栈契约,两边都别单改**。
- 聊天页(2026-09-12 微信式改版):方头像+气泡、时间条(`chat_items.dart::buildChatItems` 纯函数,间隔>5 分钟插一条)、长按菜单(复制/删除本机;**`showMenu` 定位必须用气泡自己的 context**——`ListView.builder` 的 itemBuilder context 是 sliver,要 `Builder` 包一层)、表情面板、＋面板发图、失败重发(不撤消息,红叹号 `chat.retry` 可点重发)。keys:`chat.time` / `chat.menu.copy|delete` / `chat.emoji.button|panel` / `chat.more.button|image` / `chat.retry` / `chat.image`。
- ⚠️ **ListTile trailing 里别用带 `alignment` 的 Container**:有界约束下会撑满整格宽,ListTile 直接断言崩溃;用 `Center(widthFactor: 1)` 或 SizedBox 包裹。

## 手测

- 代发消息:`python manage.py im_send --from uX --to uY --text "..."`(灰条 `--notice`,账号须已导入);重演配对 `dev_reset_pair --a u8 --b u12`(清滑卡+配对,**不清** IM 聊天记录)。
- 单设备登录手测:两台模拟器先后登同一账号 → 后登录端正常,先登录端应即时/≤45s 退回登录页带提示。
- 批量重刷 IM 头像(换服务器/换域名后 `MEDIA_BASE_URL` 变了才需要):直接调任务函数,不必等 Celery worker。

```bash
python manage.py shell -c "
from django.contrib.auth import get_user_model
from im.tasks import sync_profile
ids = list(get_user_model().objects.filter(photos__status='approved').distinct().values_list('id', flat=True))
for uid in ids:
    sync_profile.run(uid, 'avatar')
print('done', len(ids))
"
```

## 自建 IM(2026-10-20 起)

- **协议**:WS 首帧必须是 `auth`(token 放帧里,不放 URL);`send` 必须带 `client_msg_id`(1–64 字符),重发复用同一个,服务端靠 `UNIQUE(from_id, client_msg_id)` 去重。
- **seq 语义**:`seq` 是「一对会话」共享的单调序号,不是全局、也不是每用户;客户端按 `seq` 排序,不要用时间戳。
- **单设备互踢**:新连接先踢旧连接;被踢端收到 `kicked` 后**必须停止重连并强退**,否则两台设备会互相顶号。
- **灰度不能跨后端**:A 在自建、B 在腾讯时双方消息都收不到;灰度名单只能放隔离测试号,真实用户一次性全量。
- **Redis 不可用时鉴权 fail closed**:在线态可降级到进程内 Map,但封禁键查不到时拒绝新连接,避免封禁被绕过。
- **图片要两步,且 URL 有前缀白名单(2026-10-26 起)**:自建后端发图先调 `POST /api/v1/im/images` 落盘拿 `url/thumb_url`,再把它们放进 WS `send` 帧(`kind=image`);imserver 会校验两个 URL 都必须以 `IM_MEDIA_PREFIX` 开头,否则 `42201`。所以部署时 `IM_MEDIA_PREFIX` 必须等于 Django 的 `MEDIA_BASE_URL + /media/chat/`,且它是**必填项**(没配 imserver 起不来)。客户端按 `capabilities.image` 决定是否显示入口。
- **图片没有机器审核**:上传即发,靠 ops `/ops/chat-images/` 人工抽审 + 举报兜底;接云内容安全前,这是上线阻断项。
- **Nginx**:`/im/ws` 必须 `Upgrade` + `Connection: upgrade`,并设 `X-Real-IP`(服务端用它做限流);`proxy_read_timeout` ≥ 90s。
- **回退**:改 `IM_BACKEND=tencent` 只影响下一次登录;要立刻止血先停 imserver,再让用户重启 App。
- **连接池必须做存活探测(2026-10-26 事故)**:MySQL `wait_timeout=28800`(8h)会掐掉空闲连接;池若只管「借出/归还」、不 ping,死连接会被反复借出,之后**每条 SQL 都报 `Lost connection`**——`readyz` 503、发消息 50001、`/internal/blacklist` 变成 422(被 catch 包成「参数不合法」),而进程、WS、鉴权全都正常,极难从表面看出来。修法:`MysqlPool::acquire()` 在连接空闲超过 `IM_DB_IDLE_PING_MS`(默认 5000)时先 `mysql_ping`,失败就 `clear_stmt_cache` + 关掉 + 重连;`Lease::query` 遇到 2006/2013/2055 立即丢弃连接(放回空槽位,下次 acquire 重连)。
- **`readyz` 503 就是 DB 挂了**:它跑 `SELECT 1`,不是只看进程;上线后必须有人/有探针盯它(这次 503 挂了 3 天没人发现,因为没人监控)。
- **DB 线程池里的异常会 std::terminate**:`boost::asio::post(db_pool_, ...)` 的 lambda 一旦抛异常,进程直接死。所以统一走 `WsSession::run_db()`(捕获后回一条 50001),不要在 lambda 里裸调会抛的 DB 函数。

## 聊天图片签名(2026-10-26)

- **生产 nginx 没有 `secure_link` 模块**:宝塔的编译参数只有 `--with-http_auth_request_module`。照抄网上的 `secure_link` 配置会在 `nginx -t` 报 unknown directive;正确做法是 `auth_request` → Django `GET /api/v1/im/images/auth`(见 `imserver/deploy/nginx-media-sign.conf`)。
- **签名必须在读时生成**:把带签名的 URL 写进 `im_message.body`,24h 后历史消息会永久 403。imserver 落库前统一 `MediaSigner::canonical()` 去掉 query,推送/历史/会话列表再现签;`body.image.url` 里出现 `?e=&s=` 说明写时规范化被绕过了。
- **两端密钥不一致 = 所有聊天图片 403**:先比对 Django `.env` 与容器环境里的 `IM_MEDIA_SIGN_SECRET`(以及 `IM_MEDIA_SIGN_TTL`),再去查 nginx —— 其它图片(头像/广场)正常、只有 `/media/chat/` 403,基本就是这里。
- **签名 URL 每小时稳定**:`e` 按整点对齐 + TTL,所以同一小时内同一张图的 URL 不变(浏览器缓存有效),但**不要把它持久化到客户端数据库**——超过 24h 就会 403,重进聊天页拉历史即可刷新。
- **清理命令默认 dry-run**:定时任务必须显式 `--apply`;删文件不可逆,第一次先跑不带 `--apply` 看汇总。清理后图片 404、聊天显示占位是预期行为。
- **nginx `alias` 会吃掉 location 前缀(2026-10-26 部署实测)**:`location ^~ /media/chat/ { alias .../media/; }` 会把 `/media/chat/` 整段替换掉,实际去找 `media/2026/10/x.jpg` —— 验签通过但 404。alias 必须写成 `.../media/chat/`。另外别用 `sed s#media/#media/chat/#` 批量替换:通用 `location ^~ /media/` 的 alias 会被一起改掉,用户头像与广场图立刻全 404。
- **上传落盘路径别重复拼 `chat/年/月`(2026-10-26 部署实测)**:`ChatImage.file` 的 `upload_to` 已经是 `chat/%Y/%m/`,视图里再传 `chat/{month}/{stem}.jpg` 会落成 `media/chat/2026/10/chat/2026/10/x.jpg`;测试只断言了前缀所以没红。正确写法是只给文件名,并用 `assertRegex(image.file.name, r"^chat/\d{4}/\d{2}/...")` 兜住。

