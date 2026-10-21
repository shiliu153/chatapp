import asyncio
import json
import os
import time

import jwt
import websockets

SECRET = os.environ["IM_JWT_SECRET"]
WS = os.environ.get("IM_TEST_WS", "ws://127.0.0.1:19100/im/ws")


def token(uid: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600, "jti": "test"},
        SECRET,
        algorithm="HS256",
    )


async def recv_until(ws, type_):
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == type_:
            return message


async def main():
    first = await websockets.connect(WS)
    await first.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(1)}}))
    ok = await recv_until(first, "auth_ok")
    assert ok["data"]["uid"] == 1

    second = await websockets.connect(WS)
    await second.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(1)}}))
    kicked = await recv_until(first, "kicked")
    assert kicked["data"]["reason"] == "multi_device"

    await second.send(json.dumps({"v": 1, "type": "ping"}))
    pong = await recv_until(second, "pong")
    assert "server_time" in pong["data"]

    await first.close()
    await second.close()


asyncio.run(main())
