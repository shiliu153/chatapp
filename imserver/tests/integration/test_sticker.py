"""贴纸消息(kind=2 custom)集成测试 —— 批次 J 的 J-1 闸门落地版。

覆盖四件事:
    1. 上行 ``kind=custom`` 且 ``type=sticker`` 能被接受(落库为 kind=2);
    2. 下行实时帧与 ``GET /im/api/messages`` 的历史都能带回 ``custom``;
    3. 客户端伪造系统灰条(``type=match_notice``)被 42201 拒绝;
    4. 贴纸 id 形状不合法被 42201 拒绝。

为什么要有这条测试:``custom`` 原本是服务端专用消息类型(灰条/系统通知只走
``/internal/send``),批次 J 为了贴纸把上行放开了。放开的边界必须被测试钉住,
否则以后有人把白名单改成「照单全收」时没人会发现。
"""

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
        {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600, "jti": "sticker"},
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


def send_frame(client_msg_id: str, to_uid: int, custom: dict) -> dict:
    """拼一帧上行 send(kind=custom)。"""
    return {
        "v": 1,
        "type": "send",
        "id": client_msg_id,
        "data": {
            "client_msg_id": client_msg_id,
            "to": f"u{to_uid}",
            "kind": "custom",
            "custom": custom,
        },
    }


async def main():
    base = 500000 + (int(time.time() * 1000) + os.getpid()) % 100000
    sender_uid, receiver_uid = base, base + 1
    ensure(sender_uid, "A")
    ensure(receiver_uid, "B")
    pair(sender_uid, receiver_uid)

    sender = await auth(sender_uid)
    receiver = await auth(receiver_uid)

    # 1) 合法贴纸:发送成功,对端收到实时下行帧
    await sender.send(json.dumps(send_frame("st-1", receiver_uid,
                                            {"type": "sticker", "id": "sticker_01"})))
    ack = await recv(sender, "ack")
    assert ack["data"]["seq"] == 1, ack
    pushed = await recv(receiver, "message")
    assert pushed["data"]["kind"] == "custom", pushed
    assert pushed["data"]["custom"] == {"type": "sticker", "id": "sticker_01"}, pushed

    # 2) 历史接口同样带回 custom(离线补拉路径)
    history = get(f"/messages?peer=u{sender_uid}&limit=50", receiver_uid)["items"]
    assert len(history) == 1, history
    assert history[0]["kind"] == "custom", history
    assert history[0]["custom"] == {"type": "sticker", "id": "sticker_01"}, history

    # 3) 伪造系统灰条:必须被拒(否则任何账号都能冒充系统通知)
    await sender.send(json.dumps(send_frame(
        "st-2", receiver_uid, {"type": "match_notice", "desc": "你们已互相喜欢"})))
    forged = await recv(sender, "error")
    assert forged["data"]["code"] == 42201, forged

    # 4) 贴纸 id 形状不合法:必须被拒
    await sender.send(json.dumps(send_frame(
        "st-3", receiver_uid, {"type": "sticker", "id": "sticker_1"})))
    bad_id = await recv(sender, "error")
    assert bad_id["data"]["code"] == 42201, bad_id

    # 5) 白名单外的多余字段不落库:只保留 type/id
    await sender.send(json.dumps(send_frame(
        "st-4", receiver_uid,
        {"type": "sticker", "id": "sticker_12", "desc": "夹带", "data": {"x": 1}})))
    await recv(sender, "ack")
    await recv(receiver, "message")
    latest = get(f"/messages?peer=u{sender_uid}&limit=50", receiver_uid)["items"][-1]
    assert latest["custom"] == {"type": "sticker", "id": "sticker_12"}, latest

    await sender.close()
    await receiver.close()


asyncio.run(main())
