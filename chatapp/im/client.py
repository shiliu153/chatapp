"""腾讯云 IM REST 客户端。

设计要点:
    1. **业务函数对外永不抛异常**:失败只记日志并返回 ``False``。IM 抖动不应该拖垮
       主流程;把 ``False`` 转成异常、交给 Celery 重试是 ``im/tasks.py`` 的职责;
    2. **REST 调用的 identifier 必须是应用管理员**(否则腾讯返回 60010),而消息的
       发送方由 body 里的 ``From_Account`` 决定 —— 所以对外仍是「双方各自发的」;
    3. **建号必须幂等**:``ensure_account`` 先查后建,绝不盲目调用 ``account_import``。

注意事项:
    ``account_import`` 对**已存在**的账号不会返回 7015,而是返回 ``ErrorCode: 0``
    并把 ``Nick`` / ``FaceUrl`` 覆盖成传入值。因此「先导入、把 7015 当成功」的写法
    会静默清空已同步的昵称与头像,详见 ``ensure_account`` 的说明。

关联文档:
    - 踩坑记录:docs/pitfalls/im.md
"""

import json
import logging
import random

import requests
from django.conf import settings

from .signature import gen_user_sig

logger = logging.getLogger(__name__)

MATCH_NOTICE_TEXT = "你们已互相喜欢,开始聊天吧"

SYSTEM_NOTICE_IDENTIFIER = "system_notice"
SYSTEM_NOTICE_NICK = "系统通知"

BAN_REASON_FALLBACK = "违反社区规范"
BAN_LIFTED_TEXT = "您的账号限制已解除,所有功能已恢复。请遵守社区规范。"
REPORT_HANDLED_TEXT = "您提交的举报已处理,感谢您对社区安全的支持。"
POST_COMMENTED_TEMPLATE = "{nickname} 评论了你的动态:{snippet}"


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


def _random_int():
    """生成腾讯 REST 要求的随机数参数。

    Returns:
        1 ~ 4294967295 之间的随机整数(即无符号 32 位范围)。
    """
    return random.randint(1, 4294967295)


def _request(service: str, command: str, payload: dict | None = None, identifier: str | None = None) -> dict:
    """发起一次腾讯 IM REST 调用。

    统一拼 URL、签名、随机数与超时;HTTP 层错误由 ``raise_for_status`` 抛出,
    由各业务函数的 ``try`` 兜住。

    Args:
        service: REST 服务名,如 ``im_open_login_svc``。
        command: 该服务下的命令名,如 ``account_import``。
        payload: 请求体;``None`` 表示空对象。
        identifier: 调用身份;``None`` 表示用管理员账号 ``IM_ADMIN_IDENTIFIER``。

    Returns:
        腾讯返回的 JSON 字典。
    """
    identifier = identifier or settings.IM_ADMIN_IDENTIFIER
    url = f"{settings.IM_REST_BASE}/{service}/{command}"
    params = {
        "sdkappid": settings.IM_SDKAPPID,
        "identifier": identifier,
        "usersig": gen_user_sig(identifier),
        "random": _random_int(),
        "contenttype": "json",
    }
    resp = requests.post(url, params=params, json=payload or {}, timeout=settings.IM_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _check(result: dict, what: str) -> bool:
    """按腾讯的 ``ErrorCode`` 判定调用是否成功。

    Args:
        result: 腾讯返回的 JSON 字典。
        what: 调用名,仅用于日志。

    Returns:
        ``ErrorCode`` 为 0 时返回 ``True``,否则记警告日志并返回 ``False``。
    """
    if result.get("ErrorCode") != 0:
        logger.warning("IM %s 返回错误: %s", what, result)
        return False
    return True


def import_account(identifier: str, nickname: str = "") -> bool:
    """导入(创建)一个 IM 账号。

    注意这是**破坏性**接口:对已存在的账号会把昵称与头像覆盖成传入值。
    需要幂等建号时请用 ``ensure_account``,不要直接调本函数。

    Args:
        identifier: IM 账号(即 ``u{user_id}``)。
        nickname: 初始昵称,可为空串。

    Returns:
        成功返回 ``True``;调用异常或腾讯返回非 0 错误码时返回 ``False``。
    """
    payload = {"Identifier": identifier, "Nick": nickname, "FaceUrl": ""}
    try:
        result = _request("im_open_login_svc", "account_import", payload)
    except Exception:
        logger.exception("IM account_import 调用失败 identifier=%s", identifier)
        return False
    return _check(result, "account_import")


def send_custom_elem(from_identifier: str, to_identifier: str, data: dict, desc: str = "") -> bool:
    """发送一条自定义消息(灰条、系统通知都走它)。

    Args:
        from_identifier: 发送方 IM 账号(由 body 的 ``From_Account`` 决定)。
        to_identifier: 接收方 IM 账号。
        data: 自定义消息体,会被序列化成 JSON 放进 ``Data``。
        desc: 消息摘要;客户端在会话列表里用它做预览文案。

    Returns:
        成功返回 ``True``;调用异常或腾讯返回非 0 错误码时返回 ``False``。
    """
    payload = {
        "SyncOtherMachine": 2,
        "From_Account": from_identifier,
        "To_Account": to_identifier,
        "MsgRandom": _random_int(),
        "MsgBody": [{
            "MsgType": "TIMCustomElem",
            "MsgContent": {"Data": json.dumps(data, ensure_ascii=False), "Desc": desc, "Ext": ""},
        }],
    }
    try:
        # REST 的 identifier 必须是本应用的管理员账号(否则腾讯报 60010);
        # 消息的发送方由 body 里的 From_Account 决定,所以对外仍是"双方各自发的"。
        result = _request("openim", "sendmsg", payload)
    except Exception:
        logger.exception("IM 发消息失败 %s -> %s", from_identifier, to_identifier)
        return False
    return _check(result, "sendmsg")


def send_match_notice(identifier_a: str, identifier_b: str) -> bool:
    """双方各发一条 TIMCustomElem:两个人的会话列表都会出现这个会话(M2 渲染成居中灰条)。

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
    return _black_list("black_list_add", owner_identifier, other_identifier)


def black_list_delete(owner_identifier: str, other_identifier: str) -> bool:
    """把对方从自己的 IM 黑名单移除(解除拉黑时调用)。

    Args:
        owner_identifier: 解除拉黑的操作方 IM 账号。
        other_identifier: 被解除拉黑方 IM 账号。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    return _black_list("black_list_delete", owner_identifier, other_identifier)


def _black_list(command: str, owner_identifier: str, other_identifier: str) -> bool:
    """拉黑/解除拉黑的公共实现。

    Args:
        command: ``black_list_add`` 或 ``black_list_delete``。
        owner_identifier: 操作方 IM 账号。
        other_identifier: 对方 IM 账号。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    # 注意:identifier 是否必须是管理员,需用真凭据实测确认,与 sendmsg 的 60010 同类问题
    payload = {"From_Account": owner_identifier, "To_Account": [other_identifier]}
    try:
        result = _request("sns", command, payload)
    except Exception:
        logger.exception("IM %s 失败 %s -> %s", command, owner_identifier, other_identifier)
        return False
    return _check(result, command)


def kick_user(identifier: str) -> bool:
    """把账号的在线 IM 会话踢下线(重封禁用;不然已有 userSig 最长 7 天还能聊)。

    Args:
        identifier: 目标 IM 账号。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    try:
        result = _request("im_open_login_svc", "kick", {"UserID": identifier})
    except Exception:
        logger.exception("IM kick 调用失败 identifier=%s", identifier)
        return False
    return _check(result, "kick")


def delete_account(identifier: str) -> bool:
    """删除 IM 账号(注销账号时调用)。

    注意:参数形状需用真凭据实测确认。本仓库已有两处同类前车之鉴 ——
    ``sendmsg`` 的 identifier 必须是管理员(否则 60010)、``account_import``
    对已存在账号会覆盖 Nick/FaceUrl 而不是返回 7015。

    Args:
        identifier: 待删除的 IM 账号。

    Returns:
        成功返回 ``True``;调用异常或腾讯返回非 0 错误码时返回 ``False``。
    """
    payload = {"DeleteItem": [{"UserID": identifier}]}
    try:
        result = _request("im_open_login_svc", "account_delete", payload)
    except Exception:
        logger.exception("IM account_delete 调用失败 identifier=%s", identifier)
        return False
    return _check(result, "account_delete")


def ensure_account(identifier: str, nickname: str = "") -> bool:
    """幂等建号:已存在就**不动它**,不存在才导入。

    腾讯的 ``account_import`` 对**已存在**账号并不返回 7015,而是返回
    ``ErrorCode: 0`` 并把 ``Nick`` / ``FaceUrl`` **覆盖**成传入值(2026-10-12 实测)。
    「先导入、7015 当成功」的写法会带来两个后果:
        1. 每次 ``POST /im/user_sig`` 的首次 ensure 都把已同步的昵称/头像清成空串
           (会话列表于是显示成 ``u43`` 而不是昵称);
        2. 7015 分支实际上永远走不到,是个假兜底。

    因此这里先 ``account_check`` 问状态:已存在直接返回成功;查询失败时**不敢盲目
    导入**(导入是破坏性的),返回 ``False`` 让上层重试。

    Args:
        identifier: IM 账号。
        nickname: 仅在需要新建账号时使用的初始昵称。

    Returns:
        账号已存在或新建成功返回 ``True``;状态查询失败、导入失败返回 ``False``。
    """
    try:
        result = _request("im_open_login_svc", "account_check",
                          {"CheckItem": [{"UserID": identifier}]})
        if result.get("ErrorCode") != 0:
            logger.warning("IM account_check 返回错误: %s", result)
            return False
        items = result.get("ResultItem") or []
        if items and items[0].get("AccountStatus") == "Imported":
            return True
    except Exception:
        logger.exception("IM account_check 调用失败 identifier=%s", identifier)
        return False

    return import_account(identifier, nickname)


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
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "ban_lifted"}, BAN_LIFTED_TEXT)


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


def send_text(from_identifier: str, to_identifier: str, text: str) -> bool:
    """发一条普通文本消息;手测/联调用(业务消息都从 App 端走 SDK)。

    Args:
        from_identifier: 发送方 IM 账号。
        to_identifier: 接收方 IM 账号。
        text: 文本内容。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    payload = {
        "SyncOtherMachine": 2,
        "From_Account": from_identifier,
        "To_Account": to_identifier,
        "MsgRandom": _random_int(),
        "MsgBody": [{"MsgType": "TIMTextElem", "MsgContent": {"Text": text}}],
    }
    try:
        result = _request("openim", "sendmsg", payload)
    except Exception:
        logger.exception("IM 发消息失败 %s -> %s", from_identifier, to_identifier)
        return False
    return _check(result, "sendmsg")


def set_profile_nick(identifier: str, nickname: str) -> bool:
    """把昵称同步到 IM 资料(会话列表 showName 的来源,名字降级兜底的根)。

    接口是 ``profile/portrait_set``;名字写错(如 ``profile_set_field``)会返回 60008。

    Args:
        identifier: IM 账号。
        nickname: 要写入的昵称。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    return _portrait_set(identifier, [{"Tag": "Tag_Profile_IM_Nick", "Value": nickname}], "portrait_set")


def set_profile_avatar(identifier: str, avatar_url: str) -> bool:
    """把头像同步到 IM 资料(会话列表/消息页头像取自 IM 的资料)。

    字段名是 ``Tag_Profile_IM_Image``;写成 ``Url`` 会报 40009「Invalid field」。

    Args:
        identifier: IM 账号。
        avatar_url: 头像的绝对 URL。

    Returns:
        成功返回 ``True``,失败返回 ``False``。
    """
    return _portrait_set(identifier, [{"Tag": "Tag_Profile_IM_Image", "Value": avatar_url}], "portrait_set")


def _portrait_set(identifier: str, profile_items: list, what: str) -> bool:
    """资料字段写入的公共实现。

    Args:
        identifier: IM 账号。
        profile_items: 待写入的 ``ProfileItem`` 列表。
        what: 调用名,仅用于日志。

    Returns:
        成功返回 ``True``;调用异常或腾讯返回非 0 错误码时返回 ``False``。
    """
    payload = {"From_Account": identifier, "ProfileItem": profile_items}
    try:
        result = _request("profile", "portrait_set", payload)
    except Exception:
        logger.exception("IM portrait_set 调用失败 identifier=%s", identifier)
        return False
    return _check(result, what)
