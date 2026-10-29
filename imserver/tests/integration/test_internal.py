import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request

import jwt
import websockets

SECRET = os.environ["IM_INTERNAL_SECRET"]
JWT_SECRET = os.environ["IM_JWT_SECRET"]
BASE = "http://127.0.0.1:19101"
WS = "ws://127.0.0.1:19100/im/ws"


def token(uid: int, sv=None) -> str:
    now = int(time.time())
    payload = {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600, "jti": "test"}
    if sv is not None:
        payload["sv"] = sv
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def call(path: str, payload=None, method: str = "POST"):
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


async def auth(uid: int, sv=None):
    ws = await websockets.connect(WS)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid, sv)}}))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == "auth_ok":
            return ws
        if message["type"] == "error":
            return message


def http_get(path: str, uid: int, sv=None):
    """带 Bearer token 调用自建 IM 的读接口。

    Args:
        path: 以 ``/im/api`` 开头的路径(可带 query)。
        uid: 账号 id,用来签 token。
        sv: token 里的会话版本;``None`` 表示不带。

    Returns:
        ``(状态码, 响应 JSON)``;4xx/5xx 也按同样形式返回,不抛异常。
    """
    request = urllib.request.Request(
        BASE + path,
        method="GET",
        headers={"Authorization": f"Bearer {token(uid, sv)}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


async def recv(ws, type_):
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == type_:
            return message


async def main():
    uid = 300000 + (int(time.time() * 1000) + os.getpid()) % 100000
    call("/internal/healthz", method="GET")
    call("/internal/accounts/ensure", {"uid": uid, "nickname": "N"})

    ws = await auth(uid)
    call(
        "/internal/send",
        {
            "from": 0,
            "to": uid,
            "kind": "custom",
            "custom": {"type": "ban_notice", "desc": "你被封禁", "data": {}},
        },
    )

    message = await recv(ws, "message")
    assert message["data"]["custom"]["type"] == "ban_notice"
    await ws.close()

    call("/internal/kick", {"uid": uid, "block": True})
    blocked = await auth(uid)
    assert isinstance(blocked, dict)
    assert blocked["data"]["code"] == 40301

    call("/internal/unblock", {"uid": uid})
    allowed = await auth(uid)
    assert not isinstance(allowed, dict)
    await allowed.close()

    # 会话版本:同步到 5 后 sv=5 可连;升到 6 后旧 token 必须被拒。
    call("/internal/session_version", {"uid": uid, "version": 5})
    current = await auth(uid, sv=5)
    assert not isinstance(current, dict)
    await current.close()
    call("/internal/session_version", {"uid": uid, "version": 6})
    stale = await auth(uid, sv=5)
    assert isinstance(stale, dict)
    assert stale["data"]["code"] == 40101
    fresh = await auth(uid, sv=6)
    assert not isinstance(fresh, dict)
    await fresh.close()

    # H-1:HTTP 读接口与 WS 同口径校验 sv —— 旧设备不能继续翻历史
    status, body = http_get("/im/api/conversations", uid, sv=6)
    assert status == 200, (status, body)
    status, body = http_get("/im/api/conversations", uid, sv=5)
    assert status == 401 and body["code"] == 40101, (status, body)

    # M-2:会话列表按账号限流(120/min、burst 40),连续请求必须出现 429
    limited_uid = uid + 1
    call("/internal/accounts/ensure", {"uid": limited_uid, "nickname": "L"})
    statuses = [http_get("/im/api/conversations", limited_uid)[0] for _ in range(60)]
    assert 429 in statuses, statuses
    assert statuses.count(200) <= 45, statuses

    # M-8:``u12abc`` 必须整体拒绝,不能按前缀解析成 u12
    sender = await auth(uid, sv=6)
    await sender.send(
        json.dumps(
            {
                "v": 1,
                "type": "send",
                "id": "bad-to",
                "data": {"to": "u12abc", "kind": "text", "text": "x"},
            }
        )
    )
    bad_to = await recv(sender, "error")
    assert bad_to["data"]["code"] == 42201, bad_to
    await sender.close()


asyncio.run(main())
