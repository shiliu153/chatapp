import asyncio
import json
import os
import time
import urllib.request

import jwt
import websockets

from _support import ensure, pair

SECRET = os.environ["IM_JWT_SECRET"]
WS = os.environ.get("IM_TEST_WS", "ws://127.0.0.1:19100/im/ws")
HTTP = os.environ.get("IM_TEST_HTTP", "http://127.0.0.1:19101/im/api")


def token(uid: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600, "jti": "test"},
        SECRET,
        algorithm="HS256",
    )


def get(path: str, uid: int):
    request = urllib.request.Request(
        HTTP + path, headers={"Authorization": f"Bearer {token(uid)}"}
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


async def auth(uid: int):
    ws = await websockets.connect(WS)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid)}}))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == "auth_ok":
            return ws


async def recv(ws, type_):
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == type_:
            return message


async def main():
    base = 200000 + (int(time.time() * 1000) + os.getpid()) % 100000
    sender_uid, receiver_uid = base, base + 1
    ensure(sender_uid)
    ensure(receiver_uid)
    pair(sender_uid, receiver_uid)
    sender = await auth(sender_uid)
    for index, text in enumerate(["一", "二"]):
        await sender.send(
            json.dumps(
                {
                    "v": 1,
                    "type": "send",
                    "id": f"c-{index}",
                    "data": {"to": f"u{receiver_uid}", "kind": "text", "text": text},
                }
            )
        )
        await recv(sender, "ack")

    conversations = get("/conversations", receiver_uid)["items"]
    assert conversations[0]["peer"]["id"] == f"u{sender_uid}"
    assert conversations[0]["unread"] == 2

    history = get(f"/messages?peer=u{sender_uid}&limit=50", receiver_uid)["items"]
    assert [item["text"] for item in history] == ["一", "二"]
    assert history[0]["seq"] == 1

    receiver = await auth(receiver_uid)
    await receiver.send(
        json.dumps({"v": 1, "type": "read", "id": "r-1", "data": {"peer": f"u{sender_uid}", "seq": 2}})
    )
    await recv(receiver, "ack")
    assert get("/conversations", receiver_uid)["items"][0]["unread"] == 0

    msg_id = history[0]["msg_id"]
    await sender.send(
        json.dumps({"v": 1, "type": "revoke", "id": "v-1", "data": {"msg_id": msg_id}})
    )
    revoked = await recv(receiver, "revoked")
    assert revoked["data"]["msg_id"] == msg_id
    after = get(f"/messages?peer=u{sender_uid}&limit=50", receiver_uid)["items"]
    assert after[0]["revoked"] is True and "text" not in after[0]

    await receiver.send(
        json.dumps({"v": 1, "type": "conversation_delete", "id": "d-1", "data": {"peer": f"u{sender_uid}"}})
    )
    await recv(receiver, "ack")
    assert get("/conversations", receiver_uid)["items"] == []

    await sender.close()
    await receiver.close()


asyncio.run(main())
