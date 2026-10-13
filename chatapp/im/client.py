"""腾讯云 IM REST 客户端。

约定:业务函数对外**永不抛异常**,失败只记日志并返回 False —— IM 抖动不应该拖垮主流程。
跨系统副作用统一经 im/tasks.py 的 Celery 任务调用(带重试);这里保持纯 REST 封装。
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
    reason = reason or BAN_REASON_FALLBACK
    if level == "heavy":
        return (f"您的账号因「{reason}」已被封禁。"
                "封禁期间所有功能暂停使用,如有疑问请联系客服。")
    return (f"您的账号因「{reason}」被限制。"
            "限制期间无法使用滑卡功能,聊天、资料等其他功能不受影响。如有疑问请联系客服。")


def _random_int():
    return random.randint(1, 4294967295)


def _request(service: str, command: str, payload: dict | None = None, identifier: str | None = None) -> dict:
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
    if result.get("ErrorCode") != 0:
        logger.warning("IM %s 返回错误: %s", what, result)
        return False
    return True


def import_account(identifier: str, nickname: str = "") -> bool:
    payload = {"Identifier": identifier, "Nick": nickname, "FaceUrl": ""}
    try:
        result = _request("im_open_login_svc", "account_import", payload)
    except Exception:
        logger.exception("IM account_import 调用失败 identifier=%s", identifier)
        return False
    return _check(result, "account_import")


def send_custom_elem(from_identifier: str, to_identifier: str, data: dict, desc: str = "") -> bool:
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
    """双方各发一条 TIMCustomElem:两个人的会话列表都会出现这个会话(M2 渲染成居中灰条)。"""
    data = {"type": "match_notice"}
    ok_a = send_custom_elem(identifier_a, identifier_b, data, MATCH_NOTICE_TEXT)
    ok_b = send_custom_elem(identifier_b, identifier_a, data, MATCH_NOTICE_TEXT)
    return ok_a and ok_b


def black_list_add(owner_identifier: str, other_identifier: str) -> bool:
    return _black_list("black_list_add", owner_identifier, other_identifier)


def black_list_delete(owner_identifier: str, other_identifier: str) -> bool:
    return _black_list("black_list_delete", owner_identifier, other_identifier)


def _black_list(command: str, owner_identifier: str, other_identifier: str) -> bool:
    # ⚠️ identifier 语义(是否必须管理员)实施时用真凭据实测,与 sendmsg 的 60010 同类问题
    payload = {"From_Account": owner_identifier, "To_Account": [other_identifier]}
    try:
        result = _request("sns", command, payload)
    except Exception:
        logger.exception("IM %s 失败 %s -> %s", command, owner_identifier, other_identifier)
        return False
    return _check(result, command)


def kick_user(identifier: str) -> bool:
    """把账号的在线 IM 会话踢下线(重封禁用;不然已有 userSig 最长 7 天还能聊)。"""
    try:
        result = _request("im_open_login_svc", "kick", {"UserID": identifier})
    except Exception:
        logger.exception("IM kick 调用失败 identifier=%s", identifier)
        return False
    return _check(result, "kick")


def delete_account(identifier: str) -> bool:
    """删除 IM 账号(注销账号用)。

    ⚠️ 参数形状实施时用真凭据实测:本仓库已有两处同类前车之鉴 ——
    `sendmsg` 的 identifier 必须是管理员(否则 60010)、`account_import`
    对已存在账号会**覆盖** Nick/FaceUrl 而不是返回 7015。
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

    ⚠️ 实测坑(2026-10-12):腾讯的 `account_import` 对**已存在**账号并不返回 7015,
    而是返回 `ErrorCode: 0` 并把 `Nick`/`FaceUrl` **覆盖**成传入值。之前「先导入、
    7015 当成功」的写法会带来两个后果:
      1. 每次 `POST /im/user_sig` 的首次 ensure 都把已同步的昵称/头像清成空串
         (会话列表于是显示成 `u43` 而不是昵称);
      2. 7015 分支实际上永远走不到,是个假兜底。
    所以这里先 `account_check` 问状态,已存在直接返回成功;查询失败不敢盲目导入
    (导入是破坏性的),返回 False 让上层重试。
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
    """封禁说明:以「系统通知」身份发一条自定义消息(level 取 light/heavy)。"""
    data = {"type": "ban_notice", "level": level}
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier, data,
                            _ban_notice_text(level, reason))


def send_ban_lifted(to_identifier: str) -> bool:
    """解封通知:以「系统通知」身份发一条自定义消息。"""
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "ban_lifted"}, BAN_LIFTED_TEXT)


def send_report_handled(to_identifier: str) -> bool:
    """举报处理结果通知:以「系统通知」身份告知举报者(固定文案,不披露处罚细节)。"""
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "report_handled"}, REPORT_HANDLED_TEXT)


def send_post_commented(to_identifier: str, commenter_nickname: str, snippet: str) -> bool:
    """动态被评论通知:以「系统通知」身份发给动态作者。"""
    desc = POST_COMMENTED_TEMPLATE.format(nickname=commenter_nickname, snippet=snippet)
    return send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "post_commented"}, desc)


def send_text(from_identifier: str, to_identifier: str, text: str) -> bool:
    """发一条普通文本消息;手测/联调用(业务消息都从 App 端走 SDK)。"""
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

    ⚠️ 接口是 profile/portrait_set;名字写错(如 profile_set_field)会返回 60008。
    """
    return _portrait_set(identifier, [{"Tag": "Tag_Profile_IM_Nick", "Value": nickname}], "portrait_set")


def set_profile_avatar(identifier: str, avatar_url: str) -> bool:
    """把头像同步到 IM 资料(会话列表/消息页头像取自 IM 的资料)。

    ⚠️ 字段名是 Tag_Profile_IM_Image;写成 Url 会报 40009「Invalid field」。
    """
    return _portrait_set(identifier, [{"Tag": "Tag_Profile_IM_Image", "Value": avatar_url}], "portrait_set")


def _portrait_set(identifier: str, profile_items: list, what: str) -> bool:
    payload = {"From_Account": identifier, "ProfileItem": profile_items}
    try:
        result = _request("profile", "portrait_set", payload)
    except Exception:
        logger.exception("IM portrait_set 调用失败 identifier=%s", identifier)
        return False
    return _check(result, what)
