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
