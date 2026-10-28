"""自建 IM 的管理端客户端:HMAC 内部 API。

设计要点:
    1. 对外函数**永不抛异常**,失败只记日志并返回 ``False``,与腾讯客户端一致;
    2. 标识符仍是 ``u<id>``,``system_notice`` 映射为 ``uid=0``;
    3. 不 import ``client.py``,避免循环依赖;文案常量在本文件本地定义。
"""

import hashlib
import hmac
import json
import logging
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SYSTEM_NOTICE_IDENTIFIER = "system_notice"
BAN_LIFTED_TEXT = "您的账号限制已解除,所有功能已恢复。请遵守社区规范。"
REPORT_HANDLED_TEXT = "您提交的举报已处理,感谢您对社区安全的支持。"


def _uid(identifier: str) -> int:
    """把 IM 账号转成用户 id。

    Args:
        identifier: ``u9`` 或 ``system_notice``。

    Returns:
        用户 id;系统通知为 0。
    """
    if identifier == SYSTEM_NOTICE_IDENTIFIER:
        return 0
    return int(identifier.removeprefix("u"))


def _post(path: str, payload: dict) -> bool:
    """调用一次内部 API。

    Args:
        path: 以 ``/internal/`` 开头的路径。
        payload: JSON 请求体。

    Returns:
        2xx 返回 ``True``;网络/HTTP 错误返回 ``False``。
    """
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time()))
    signing = f"{timestamp}\nPOST\n{path}\n{body}".encode()
    signature = hmac.new(
        settings.IM_SELF_INTERNAL_SECRET.encode(), signing, hashlib.sha256
    ).hexdigest()
    try:
        response = requests.post(
            settings.IM_SELF_URL + path,
            data=body.encode(),
            headers={
                "Content-Type": "application/json",
                "X-IM-Timestamp": timestamp,
                "X-IM-Signature": signature,
            },
            timeout=5,
        )
        response.raise_for_status()
        return True
    except Exception:
        logger.exception("自建 IM 调用失败 path=%s", path)
        return False


def ensure_account(identifier: str, nickname: str = "") -> bool:
    """幂等建号。"""
    return _post("/internal/accounts/ensure",
                 {"uid": _uid(identifier), "nickname": nickname})


def set_profile_nick(identifier: str, nickname: str) -> bool:
    """同步昵称。"""
    return _post("/internal/profile", {"uid": _uid(identifier), "nickname": nickname})


def set_profile_avatar(identifier: str, avatar_url: str) -> bool:
    """同步头像。"""
    return _post("/internal/profile", {"uid": _uid(identifier), "avatar": avatar_url})


def send_custom_elem(from_identifier: str, to_identifier: str, data: dict,
                     desc: str = "") -> bool:
    """发送自定义消息(灰条/系统通知)。"""
    return _post(
        "/internal/send",
        {
            "from": _uid(from_identifier),
            "to": _uid(to_identifier),
            "kind": "custom",
            "custom": {"type": data.get("type", "other"), "desc": desc, "data": data},
        },
    )


def send_text(from_identifier: str, to_identifier: str, text: str) -> bool:
    """发送文本消息(手测/联调用)。"""
    return _post(
        "/internal/send",
        {"from": _uid(from_identifier), "to": _uid(to_identifier),
         "kind": "text", "text": text},
    )


def black_list_add(owner_identifier: str, other_identifier: str) -> bool:
    """加入 IM 黑名单。"""
    return _post("/internal/blacklist",
                 {"owner": _uid(owner_identifier), "peer": _uid(other_identifier),
                  "action": "add"})


def black_list_delete(owner_identifier: str, other_identifier: str) -> bool:
    """移出 IM 黑名单。"""
    return _post("/internal/blacklist",
                 {"owner": _uid(owner_identifier), "peer": _uid(other_identifier),
                  "action": "remove"})


def kick_user(identifier: str, block: bool = False) -> bool:
    """踢下线;``block=True`` 同时写入封禁键。"""
    return _post("/internal/kick", {"uid": _uid(identifier), "block": block})


def set_session_version(identifier: str, version: int) -> bool:
    """把账号当前会话版本同步给自建 IM。

    imserver 在 WS 鉴权时比对 token 里的 ``sv``;不一致即拒绝旧 token(H3)。

    Args:
        identifier: IM 账号,如 ``u9``。
        version: 账号当前的 ``session_version``。

    Returns:
        同步成功返回 ``True``;网络/HTTP 错误返回 ``False``。
    """
    return _post("/internal/session_version",
                 {"uid": _uid(identifier), "version": int(version)})


def pair_add(user_a_identifier: str, user_b_identifier: str) -> bool:
    """建立聊天权限(配对成功)。

    Args:
        user_a_identifier: 一方 IM 账号。
        user_b_identifier: 另一方 IM 账号。

    Returns:
        同步成功返回 ``True``;失败返回 ``False``。
    """
    return _post("/internal/pair", {"a": _uid(user_a_identifier),
                                    "b": _uid(user_b_identifier), "action": "add"})


def pair_remove(user_a_identifier: str, user_b_identifier: str) -> bool:
    """移除聊天权限(解除配对/拉黑)。

    Args:
        user_a_identifier: 一方 IM 账号。
        user_b_identifier: 另一方 IM 账号。

    Returns:
        同步成功返回 ``True``;失败返回 ``False``。
    """
    return _post("/internal/pair", {"a": _uid(user_a_identifier),
                                    "b": _uid(user_b_identifier), "action": "remove"})


def unblock_user(identifier: str) -> bool:
    """清除封禁键。"""
    return _post("/internal/unblock", {"uid": _uid(identifier)})


def delete_account(identifier: str) -> bool:
    """删除该账号的全部 IM 数据。"""
    return _post("/internal/delete_account", {"uid": _uid(identifier)})


def send_ban_lifted(to_identifier: str) -> bool:
    """解封通知:先发灰条,再清封禁键。"""
    sent = send_custom_elem(SYSTEM_NOTICE_IDENTIFIER, to_identifier,
                            {"type": "ban_lifted"}, BAN_LIFTED_TEXT)
    return unblock_user(to_identifier) and sent
