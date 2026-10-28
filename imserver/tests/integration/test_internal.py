import asyncio
import hashlib
import hmac
import json
import os
import time
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


asyncio.run(main())
