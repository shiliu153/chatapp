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

    Args:
        level: ``heavy`` 为全域封禁,其余按轻度限制处理。
        reason: 封禁原因;为空时用 ``BAN_REASON_FALLBACK``。

    Returns:
        面向用户的中文说明。
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

    Args:
        identifier: IM 账号(即 ``u{user_id}``)。
        nickname: 初始昵称,可为空串。

    Returns:
        建号成功(或账号已存在)返回 ``True``,失败返回 ``False``。
    """
    return self_client.ensure_account(identifier, nickname)


def ensure_account(identifier: str, nickname: str = "") -> bool:
    """幂等建号:已存在就**不动它**,不存在才创建。

    Args:
        identifier: IM 账号。
        nickname: 仅在需要新建账号时使用的初始昵称。

    Returns:
        账号已存在或新建成功返回 ``True``;失败返回 ``False``。
    """
    return self_client.ensure_account(identifier, nickname)


def send_custom_elem(from_identifier: str, to_identifier: str, data: dict,
                     desc: str = "") -> bool:
    """发送一条自定义消息(灰条、系统通知都走它)。

    Args:
        from_identifier: 发送方 IM 账号。
        to_identifier: 接收方 IM 账号。
        data: 自定义消息体,会被序列化成 JSON。
        desc: 消息摘要;客户端在会话列表里用它做预览文案。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    return self_client.send_custom_elem(from_identifier, to_identifier, data, desc)


def send_match_notice(identifier_a: str, identifier_b: str) -> bool:
    """双方各发一条自定义消息:两个人的会话列表都会出现这个会话(渲染成居中灰条)。

    Args:
        identifier_a: 配对一方 IM 账号。
        identifier_b: 配对另一方 IM 账号。

    Returns:
        两条消息都成功才返回 ``True``;任一条失败返回 ``False``。
    """
    data = {"type": "match_notice"}
    ok_a = send_custom_elem(identifier_a, identifier_b, data, MATCH_NOTICE_TEXT)
    ok_b = send_custom_elem(identifier_b, identifier_a, data, MATCH_NOTICE_TEXT)
    return ok_a and ok_b


def black_list_add(owner_identifier: str, other_identifier: str) -> bool:
    """把对方加入自己的 IM 黑名单(拉黑时调用)。

    Args:
        owner_identifier: 拉黑发起方 IM 账号。
        other_identifier: 被拉黑方 IM 账号。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    return self_client.black_list_add(owner_identifier, other_identifier)


def black_list_delete(owner_identifier: str, other_identifier: str) -> bool:
    """把对方从自己的 IM 黑名单移除(解除拉黑时调用)。

    Args:
        owner_identifier: 解除拉黑的操作方 IM 账号。
        other_identifier: 被解除拉黑方 IM 账号。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    return self_client.black_list_delete(owner_identifier, other_identifier)


def kick_user(identifier: str, block: bool = False,
              client_type: str | None = None) -> bool:
    """把账号的在线 IM 会话踢下线(重封禁/同类端顶号/退出所有设备)。

    Args:
        identifier: 目标 IM 账号。
        block: 是否同时写封禁键(重封禁时为 True)。
        client_type: ``app`` / ``web`` 时只踢该端(同类互顶);``None`` = **踢全部**
            端,封禁与注销走这个语义,别改成按端。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    return self_client.kick_user(identifier, block, client_type)


def set_session_version(identifier: str, version: int,
                        client_type: str = "app") -> bool:
    """把账号在某一端上的会话版本同步给 imserver。

    Args:
        identifier: IM 账号。
        version: 该端当前的会话版本(``accounts.DeviceSession.version``)。
        client_type: ``app`` 或 ``web``;imserver 按 ``(uid, ct)`` 落库。

    Returns:
        同步结果;失败返回 ``False``(调用方按 fail-closed 处理)。
    """
    return self_client.set_session_version(identifier, version, client_type)


def pair_add(identifier_a: str, identifier_b: str) -> bool:
    """建立聊天权限(配对成功)。

    Args:
        identifier_a: 一方 IM 账号。
        identifier_b: 另一方 IM 账号。

    Returns:
        同步结果。
    """
    return self_client.pair_add(identifier_a, identifier_b)


def pair_remove(identifier_a: str, identifier_b: str) -> bool:
    """移除聊天权限(解除配对/拉黑)。

    Args:
        identifier_a: 一方 IM 账号。
        identifier_b: 另一方 IM 账号。

    Returns:
        同步结果。
    """
    return self_client.pair_remove(identifier_a, identifier_b)


def delete_account(identifier: str) -> bool:
    """删除 IM 账号(注销账号时调用)。

    Args:
        identifier: 待删除的 IM 账号。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    return self_client.delete_account(identifier)


def send_ban_notice(to_identifier: str, level: str, reason: str) -> bool:
    """封禁说明:以「系统通知」身份发一条自定义消息(level 取 light/heavy)。

    Args:
        to_identifier: 被处理用户的 IM 账号。
        level: ``heavy`` 为全域封禁,其余按轻度限制处理。
        reason: 封禁原因;为空时用 ``BAN_REASON_FALLBACK``。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    data = {"type": "ban_notice", "level": level}
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier, data,
                            _ban_notice_text(level, reason))


def send_ban_lifted(to_identifier: str) -> bool:
    """解封通知:以「系统通知」身份发一条自定义消息。

    Args:
        to_identifier: 被解封用户的 IM 账号。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    return self_client.send_ban_lifted(to_identifier)


def send_report_handled(to_identifier: str) -> bool:
    """举报处理结果通知:以「系统通知」身份告知举报者(固定文案,不披露处罚细节)。

    Args:
        to_identifier: 举报者的 IM 账号。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "report_handled"}, REPORT_HANDLED_TEXT)


def send_post_commented(to_identifier: str, commenter_nickname: str, snippet: str) -> bool:
    """动态被评论通知:以「系统通知」身份发给动态作者。

    Args:
        to_identifier: 动态作者的 IM 账号。
        commenter_nickname: 评论者昵称,用于通知正文。
        snippet: 评论内容摘要(由调用方截断)。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    desc = POST_COMMENTED_TEMPLATE.format(nickname=commenter_nickname, snippet=snippet)
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "post_commented"}, desc)


def send_post_replied(to_identifier: str, replier_nickname: str, snippet: str) -> bool:
    """被回复通知:以「系统通知」身份发给被回复者。

    Args:
        to_identifier: 被回复者的 IM 账号。
        replier_nickname: 回复者昵称,用于通知正文。
        snippet: 回复内容摘要(由调用方截断)。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    desc = POST_REPLIED_TEMPLATE.format(nickname=replier_nickname, snippet=snippet)
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "post_replied"}, desc)


def send_text(from_identifier: str, to_identifier: str, text: str) -> bool:
    """发一条普通文本消息;手测/联调用(业务消息都从 App 端走 WS)。

    Args:
        from_identifier: 发送方 IM 账号。
        to_identifier: 接收方 IM 账号。
        text: 文本内容。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    return self_client.send_text(from_identifier, to_identifier, text)


def set_profile_nick(identifier: str, nickname: str) -> bool:
    """把昵称同步到 IM 资料(会话列表 showName 的来源,名字降级兜底的根)。

    Args:
        identifier: IM 账号。
        nickname: 要写入的昵称。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    return self_client.set_profile_nick(identifier, nickname)


def set_profile_avatar(identifier: str, avatar_url: str) -> bool:
    """把头像同步到 IM 资料(会话列表/消息页头像取自 IM 的资料)。

    Args:
        identifier: IM 账号。
        avatar_url: 头像的绝对 URL。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    return self_client.set_profile_avatar(identifier, avatar_url)
