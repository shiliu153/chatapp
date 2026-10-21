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


async def auth(uid: int):
    ws = await websockets.connect(WS)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid)}}))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == "auth_ok":
            return ws


async def recv_until(ws, type_):
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == type_:
            return message


async def main():
    sender = await auth(101)
    receiver = await auth(102)

    await sender.send(
        json.dumps(
            {
                "v": 1,
                "type": "send",
                "id": "c-1",
                "data": {"to": "u102", "kind": "text", "text": "你好"},
            }
        )
    )
    ack = await recv_until(sender, "ack")
    assert ack["id"] == "c-1"
    assert ack["data"]["seq"] == 1

    push = await recv_until(receiver, "message")
    assert push["data"]["text"] == "你好"
    assert push["data"]["from"] == "u101"
    assert push["data"]["seq"] == 1

    await sender.send(
        json.dumps(
            {
                "v": 1,
                "type": "send",
                "id": "c-1",
                "data": {"to": "u102", "kind": "text", "text": "你好"},
            }
        )
    )
    again = await recv_until(sender, "ack")
    assert again["data"]["msg_id"] == ack["data"]["msg_id"]
    assert again["data"]["seq"] == 1

    await sender.close()
    await receiver.close()


asyncio.run(main())
