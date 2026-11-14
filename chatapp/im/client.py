"""IM 管理端客户端(唯一后端 = 自建 imserver)。

设计要点:
    1. **业务函数对外永不抛异常**:失败只记日志并返回 ``False``。IM 抖动不应该拖垮
       主流程;把 ``False`` 转成异常、交给 Celery 重试是 ``im/tasks.py`` 的职责;
    2. **这一层只剩「语义与文案」**:消息类型、灰条文案、系统通知身份在这里,
       真正的传输由 ``im/self_client.py`` 用 HMAC 内部 API 完成;
    3. 腾讯云 IM 分支已于 2026-11-08 删除(backlog D-4):不再有 ``IM_BACKEND`` 开关、
       不再有灰度名单,也没有「切回腾讯」的回退路径 —— IM 出问题回退 imserver 镜像。

关联文档:
    - 踩坑记录:docs/pitfalls/im.md
    - 内部 API 契约:docs/ops/imserver.md

文件信息:
    文件名称          im/client.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import logging

from . import self_client

logger = logging.getLogger(__name__)

MATCH_NOTICE_TEXT = "你们已互相喜欢,开始聊天吧"

SYSTEM_NOTICE_IDENTIFIER = "system_notice"
SYSTEM_NOTICE_NICK = "系统通知"

BAN_REASON_FALLBACK = "违反社区规范"
BAN_LIFTED_TEXT = "您的账号限制已解除,所有功能已恢复。请遵守社区规范。"
REPORT_HANDLED_TEXT = "您提交的举报已处理,感谢您对社区安全的支持。"
POST_COMMENTED_TEMPLATE = "{nickname} 评论了你的动态:{snippet}"
POST_REPLIED_TEMPLATE = "{nickname} 回复了你:{snippet}"


def _ban_notice_text(level: str, reason: str) -> str:
    """生成封禁/限制说明的正文文案。

    参数说明:
        level: ``heavy`` 为全域封禁,其余按轻度限制处理。
        reason: 封禁原因;为空时用 ``BAN_REASON_FALLBACK``。

    返回参数:
        面向用户的中文说明。

    使用示例:
        ``_ban_notice_text("heavy", "骚扰他人")``

    备注信息:
        两级文案不同:``heavy`` 说明所有功能暂停使用,其余说明只禁滑卡、聊天与资料不受影响。
        纯函数,不触网、不落库、不抛异常。
    """
    reason = reason or BAN_REASON_FALLBACK
    if level == "heavy":
        return (f"您的账号因「{reason}」已被封禁。"
                "封禁期间所有功能暂停使用,如有疑问请联系客服。")
    return (f"您的账号因「{reason}」被限制。"
            "限制期间无法使用滑卡功能,聊天、资料等其他功能不受影响。如有疑问请联系客服。")


def import_account(identifier: str, nickname: str = "") -> bool:
    """导入(创建)一个 IM 账号。

    历史语义来自腾讯的 ``account_import``;自建后端没有独立的「导入」概念,
    统一走幂等的 ``ensure_account``(已存在不动它,不存在才建)。

    参数说明:
        identifier: IM 账号(即 ``u{user_id}``)。
        nickname: 初始昵称,可为空串。

    返回参数:
        建号成功(或账号已存在)返回 ``True``,失败返回 ``False``。

    使用示例:
        ``import_account("u9", "小明")``

    备注信息:
        与 ``ensure_account`` 走同一条调用,保留这个名字只为对齐历史语义;失败只记日志并
        返回 ``False``,不抛异常 —— 把 ``False`` 转成异常、交给 Celery 重试是
        ``im/tasks.py::_require`` 的职责。
    """
    return self_client.ensure_account(identifier, nickname)


def ensure_account(identifier: str, nickname: str = "") -> bool:
    """幂等建号:已存在就**不动它**,不存在才创建。

    参数说明:
        identifier: IM 账号。
        nickname: 仅在需要新建账号时使用的初始昵称。

    返回参数:
        账号已存在或新建成功返回 ``True``;失败返回 ``False``。

    使用示例:
        ``ensure_account("u9", "小明")``

    备注信息:
        ``nickname`` 只在新建账号时生效,已有账号不会被改名(改名走 ``set_profile_nick``)。
        失败只记日志返回 ``False``,不抛异常。
    """
    return self_client.ensure_account(identifier, nickname)


def send_custom_elem(from_identifier: str, to_identifier: str, data: dict,
                     desc: str = "") -> bool:
    """发送一条自定义消息(灰条、系统通知都走它)。

    参数说明:
        from_identifier: 发送方 IM 账号。
        to_identifier: 接收方 IM 账号。
        data: 自定义消息体,会被序列化成 JSON。
        desc: 消息摘要;客户端在会话列表里用它做预览文案。

    返回参数:
        成功返回 ``True``,失败返回 ``False``。

    使用示例:
        ``send_custom_elem("u9", "u10", {"type": "match_notice"}, MATCH_NOTICE_TEXT)``

    备注信息:
        ``data["type"]`` 决定客户端渲染成哪种灰条(缺省 ``other``),``desc`` 是会话列表的
        预览文案;系统通知用它发时发送方传 ``SYSTEM_NOTICE_IDENTIFIER``(imserver 侧
        ``uid=0``)。失败只记日志返回 ``False``,不抛异常。
    """
    return self_client.send_custom_elem(from_identifier, to_identifier, data, desc)


def send_match_notice(identifier_a: str, identifier_b: str) -> bool:
    """双方各发一条自定义消息:两个人的会话列表都会出现这个会话(渲染成居中灰条)。

    参数说明:
        identifier_a: 配对一方 IM 账号。
        identifier_b: 配对另一方 IM 账号。

    返回参数:
        两条消息都成功才返回 ``True``;任一条失败返回 ``False``。

    使用示例:
        ``send_match_notice("u9", "u10")``

    备注信息:
        两个方向是两次独立请求,用 ``and`` 合并结果:后一条失败时前一条可能已经送达,
        重试由 ``im/tasks.py::send_match_notice`` 负责。灰条正文固定为 ``MATCH_NOTICE_TEXT``。
    """
    data = {"type": "match_notice"}
    ok_a = send_custom_elem(identifier_a, identifier_b, data, MATCH_NOTICE_TEXT)
    ok_b = send_custom_elem(identifier_b, identifier_a, data, MATCH_NOTICE_TEXT)
    return ok_a and ok_b


def black_list_add(owner_identifier: str, other_identifier: str) -> bool:
    """把对方加入自己的 IM 黑名单(拉黑时调用)。

    参数说明:
        owner_identifier: 拉黑发起方 IM 账号。
        other_identifier: 被拉黑方 IM 账号。

    返回参数:
        成功返回 ``True``,失败返回 ``False``。

    使用示例:
        ``black_list_add("u9", "u10")``

    备注信息:
        只同步 IM 侧黑名单,拉黑关系本身由业务侧落库;双向拉黑是两次调用。失败只记日志
        返回 ``False``,不抛异常。
    """
    return self_client.black_list_add(owner_identifier, other_identifier)


def black_list_delete(owner_identifier: str, other_identifier: str) -> bool:
    """把对方从自己的 IM 黑名单移除(解除拉黑时调用)。

    参数说明:
        owner_identifier: 解除拉黑的操作方 IM 账号。
        other_identifier: 被解除拉黑方 IM 账号。

    返回参数:
        成功返回 ``True``,失败返回 ``False``。

    使用示例:
        ``black_list_delete("u9", "u10")``

    备注信息:
        与 ``black_list_add`` 同一条链路,靠 ``action`` 区分增删;失败只记日志返回 ``False``,
        不抛异常。
    """
    return self_client.black_list_delete(owner_identifier, other_identifier)


def kick_user(identifier: str, block: bool = False,
              client_type: str | None = None) -> bool:
    """把账号的在线 IM 会话踢下线(重封禁/同类端顶号/退出所有设备)。

    参数说明:
        identifier: 目标 IM 账号。
        block: 是否同时写封禁键(重封禁时为 True)。
        client_type: ``app`` / ``web`` 时只踢该端(同类互顶);``None`` = **踢全部**
            端,封禁与注销走这个语义,别改成按端。

    返回参数:
        成功返回 ``True``,失败返回 ``False``。

    使用示例:
        ``kick_user("u9", block=True)`` 或 ``kick_user("u9", client_type="web")``

    备注信息:
        ``client_type=None`` 才是「踢全部端」,封禁与注销必须用它;``block=True`` 在踢的同时
        写封禁键,漏写会出现「踢掉了但马上能重连」。失败只记日志返回 ``False``,不抛异常。
    """
    return self_client.kick_user(identifier, block, client_type)


def set_session_version(identifier: str, version: int,
                        client_type: str = "app") -> bool:
    """把账号在某一端上的会话版本同步给 imserver。

    参数说明:
        identifier: IM 账号。
        version: 该端当前的会话版本(``accounts.DeviceSession.version``)。
        client_type: ``app`` 或 ``web``;imserver 按 ``(uid, ct)`` 落库。

    返回参数:
        同步结果;失败返回 ``False``(调用方按 fail-closed 处理)。

    使用示例:
        ``set_session_version("u9", 3, client_type="app")``

    备注信息:
        版本号下沉到 ``accounts.DeviceSession`` 后按端同步,``(uid, ct)`` 对不上时 imserver
        无法判新旧,所以两端都要同步;登录链路上同步失败即回 503,不放行。
    """
    return self_client.set_session_version(identifier, version, client_type)


def pair_add(identifier_a: str, identifier_b: str) -> bool:
    """建立聊天权限(配对成功)。

    参数说明:
        identifier_a: 一方 IM 账号。
        identifier_b: 另一方 IM 账号。

    返回参数:
        同步结果。

    使用示例:
        ``pair_add("u9", "u10")``

    备注信息:
        没有 ``im_pair`` 时 imserver 对发送方回 40302(未配对),所以配对成功后必须同步一次;
        失败只记日志返回 ``False``,不抛异常。
    """
    return self_client.pair_add(identifier_a, identifier_b)


def pair_remove(identifier_a: str, identifier_b: str) -> bool:
    """移除聊天权限(解除配对/拉黑)。

    参数说明:
        identifier_a: 一方 IM 账号。
        identifier_b: 另一方 IM 账号。

    返回参数:
        同步结果。

    使用示例:
        ``pair_remove("u9", "u10")``

    备注信息:
        解除配对与拉黑都要撤掉 ``im_pair``,否则对方仍能继续发消息;失败只记日志返回
        ``False``,不抛异常。
    """
    return self_client.pair_remove(identifier_a, identifier_b)


def delete_account(identifier: str) -> bool:
    """删除 IM 账号(注销账号时调用)。

    参数说明:
        identifier: 待删除的 IM 账号。

    返回参数:
        成功返回 ``True``,失败返回 ``False``。

    使用示例:
        ``delete_account("u12")``

    备注信息:
        删除该账号在 IM 侧的全部数据,不可恢复;调用方必须在用户行删除**之前**取好
        ``im_user_id`` 再入队,``im/tasks.py::delete_account`` 的参数因此是字符串而非
        ``user_id``。失败只记日志返回 ``False``,不抛异常。
    """
    return self_client.delete_account(identifier)


def send_ban_notice(to_identifier: str, level: str, reason: str) -> bool:
    """封禁说明:以「系统通知」身份发一条自定义消息(level 取 light/heavy)。

    参数说明:
        to_identifier: 被处理用户的 IM 账号。
        level: ``heavy`` 为全域封禁,其余按轻度限制处理。
        reason: 封禁原因;为空时用 ``BAN_REASON_FALLBACK``。

    返回参数:
        成功返回 ``True``,失败返回 ``False``。

    使用示例:
        ``send_ban_notice("u9", "heavy", "骚扰他人")``

    备注信息:
        以 ``SYSTEM_NOTICE_IDENTIFIER``(imserver 侧 ``uid=0``)身份发出,正文由
        ``_ban_notice_text`` 生成;``level`` 只影响文案,真正的封禁键由
        ``kick_user(..., block=True)`` 写入。
    """
    data = {"type": "ban_notice", "level": level}
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier, data,
                            _ban_notice_text(level, reason))


def send_ban_lifted(to_identifier: str) -> bool:
    """解封通知:以「系统通知」身份发一条自定义消息。

    参数说明:
        to_identifier: 被解封用户的 IM 账号。

    返回参数:
        成功返回 ``True``,失败返回 ``False``。

    使用示例:
        ``send_ban_lifted("u9")``

    备注信息:
        转调 ``self_client.send_ban_lifted``:先发灰条再清封禁键,两步都成功才算成功;
        正文固定为 ``self_client.BAN_LIFTED_TEXT``。
    """
    return self_client.send_ban_lifted(to_identifier)


def send_report_handled(to_identifier: str) -> bool:
    """举报处理结果通知:以「系统通知」身份告知举报者(固定文案,不披露处罚细节)。

    参数说明:
        to_identifier: 举报者的 IM 账号。

    返回参数:
        成功返回 ``True``,失败返回 ``False``。

    使用示例:
        ``send_report_handled("u9")``

    备注信息:
        正文固定为 ``REPORT_HANDLED_TEXT``,不披露处罚细节,也不说明是否处罚;以系统通知身份
        发出。
    """
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "report_handled"}, REPORT_HANDLED_TEXT)


def send_post_commented(to_identifier: str, commenter_nickname: str, snippet: str) -> bool:
    """动态被评论通知:以「系统通知」身份发给动态作者。

    参数说明:
        to_identifier: 动态作者的 IM 账号。
        commenter_nickname: 评论者昵称,用于通知正文。
        snippet: 评论内容摘要(由调用方截断)。

    返回参数:
        成功返回 ``True``,失败返回 ``False``。

    使用示例:
        ``send_post_commented("u9", "小明", "写得好")``

    备注信息:
        正文由 ``POST_COMMENTED_TEMPLATE`` 拼成,``snippet`` 由调用方截短(``im/tasks.py``
        取评论前 50 字);``type`` 为 ``post_commented``,客户端据此渲染跳转。
    """
    desc = POST_COMMENTED_TEMPLATE.format(nickname=commenter_nickname, snippet=snippet)
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "post_commented"}, desc)


def send_post_replied(to_identifier: str, replier_nickname: str, snippet: str) -> bool:
    """被回复通知:以「系统通知」身份发给被回复者。

    参数说明:
        to_identifier: 被回复者的 IM 账号。
        replier_nickname: 回复者昵称,用于通知正文。
        snippet: 回复内容摘要(由调用方截断)。

    返回参数:
        成功返回 ``True``,失败返回 ``False``。

    使用示例:
        ``send_post_replied("u9", "小明", "同意")``

    备注信息:
        正文由 ``POST_REPLIED_TEMPLATE`` 拼成,``snippet`` 由调用方截短;``type`` 为
        ``post_replied``,与 ``send_post_commented`` 分开,客户端才能区分跳转目标。
    """
    desc = POST_REPLIED_TEMPLATE.format(nickname=replier_nickname, snippet=snippet)
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "post_replied"}, desc)


def send_text(from_identifier: str, to_identifier: str, text: str) -> bool:
    """发一条普通文本消息;手测/联调用(业务消息都从 App 端走 WS)。

    参数说明:
        from_identifier: 发送方 IM 账号。
        to_identifier: 接收方 IM 账号。
        text: 文本内容。

    返回参数:
        成功返回 ``True``,失败返回 ``False``。

    使用示例:
        ``send_text("u9", "u10", "hello")``

    备注信息:
        业务文本消息由 App 直接走 WebSocket 发出,本函数只供手测与联调,业务与视图里不要
        调用;失败只记日志返回 ``False``。
    """
    return self_client.send_text(from_identifier, to_identifier, text)


def set_profile_nick(identifier: str, nickname: str) -> bool:
    """把昵称同步到 IM 资料(会话列表 showName 的来源,名字降级兜底的根)。

    参数说明:
        identifier: IM 账号。
        nickname: 要写入的昵称。

    返回参数:
        成功返回 ``True``,失败返回 ``False``。

    使用示例:
        ``set_profile_nick("u9", "小明")``

    备注信息:
        会话列表的 ``showName`` 直接取自 IM 资料,昵称不同步会让对端看到旧名字;失败只记
        日志返回 ``False``,不抛异常。
    """
    return self_client.set_profile_nick(identifier, nickname)


def set_profile_avatar(identifier: str, avatar_url: str) -> bool:
    """把头像同步到 IM 资料(会话列表/消息页头像取自 IM 的资料)。

    参数说明:
        identifier: IM 账号。
        avatar_url: 头像的绝对 URL。

    返回参数:
        成功返回 ``True``,失败返回 ``False``。

    使用示例:
        ``set_profile_avatar("u9", "https://cdn.test/media/avatar/a.jpg")``

    备注信息:
        会话列表与消息页的头像取自 IM 资料,资料图变更后必须同步一次;``avatar_url`` 要带
        域名与协议,相对路径对端拼不出来。失败只记日志返回 ``False``,不抛异常。
    """
    return self_client.set_profile_avatar(identifier, avatar_url)
