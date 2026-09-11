"""腾讯云 IM REST 客户端。

约定:业务函数(import_account / send_custom_elem / send_match_notice)对外
**永不抛异常**,失败只记日志并返回 False —— IM 抖动不应该拖垮注册/配对主流程。
上线前的改进方向是把这些调用丢进任务队列(Celery),开发期同步调用 + 短超时够用。
"""

import json
import logging
import random

import requests
from django.conf import settings

from .signature import gen_user_sig

logger = logging.getLogger(__name__)

MATCH_NOTICE_TEXT = "你们已互相喜欢,开始聊天吧"


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
