"""集成测试共用:调用 imserver 的内部 HMAC API。

设计要点:
    ``/internal/*`` 只接受本机回环 + HMAC 签名;测试进程与服务端共享
    ``IM_INTERNAL_SECRET``,签名串为 ``timestamp\\nMETHOD\\npath\\nbody``。
"""

import hashlib
import hmac
import json
import os
import time
import urllib.request

SECRET = os.environ["IM_INTERNAL_SECRET"]
BASE = os.environ.get("IM_INTERNAL_BASE", "http://127.0.0.1:19101")


def call(path: str, payload=None, method: str = "POST"):
    """调用一次内部 API。

    Args:
        path: 以 ``/internal/`` 开头的路径。
        payload: JSON 请求体;``None`` 表示空 body。
        method: HTTP 方法。

    Returns:
        解析后的 JSON 响应。
    """
    body = "" if payload is None else json.dumps(
        payload, ensure_ascii=False, separators=(",", ":")
    )
    timestamp = str(int(time.time()))
    signature = hmac.new(
        SECRET.encode(),
        f"{timestamp}\n{method}\n{path}\n{body}".encode(),
        hashlib.sha256,
    ).hexdigest()
    request = urllib.request.Request(
        BASE + path,
        data=body.encode() if method == "POST" else None,
        method=method,
        headers={
            "Content-Type": "application/json",
            "X-IM-Timestamp": timestamp,
            "X-IM-Signature": signature,
        },
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


def pair(a: int, b: int) -> None:
    """建立两人的聊天权限(H4 之后发送前必须先配对)。

    Args:
        a: 一方账号 id。
        b: 另一方账号 id。
    """
    call("/internal/pair", {"a": a, "b": b, "action": "add"})


def ensure(uid: int, nickname: str = "T") -> None:
    """幂等建号(H4 要求收件人真实存在,测试里先显式建好双方账号)。

    Args:
        uid: 账号 id。
        nickname: 初始昵称。
    """
    call("/internal/accounts/ensure", {"uid": uid, "nickname": nickname})
