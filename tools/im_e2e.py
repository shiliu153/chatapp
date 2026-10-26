"""自建 IM 端到端验收:登录、互发、离线未读、幂等、撤回、互踢。"""

import asyncio
import json
import os
import sys
import time
import urllib.request

import jwt
import websockets

SECRET = os.environ["IM_JWT_SECRET"]
WS = os.environ.get("IM_BASE_WS", "ws://127.0.0.1:19100/im/ws")
HTTP = os.environ.get("IM_BASE_HTTP", "http://127.0.0.1:19101/im/api")
# 必须与 imserver 的 IM_MEDIA_PREFIX 一致,否则图片帧会被 42201 拒掉
MEDIA_PREFIX = os.environ.get("IM_MEDIA_PREFIX", "http://cdn/media/chat/")


def token(uid: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600, "jti": "e2e"},
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
    base = 500000 + (int(time.time() * 1000) + os.getpid()) % 100000
    a_uid, b_uid = base, base + 1
    a = await auth(a_uid)
    b = await auth(b_uid)

    msg_ids = []
    for index in range(3):
        await a.send(json.dumps({
            "v": 1,
            "type": "send",
            "id": f"e2e-{index}",
            "data": {"to": f"u{b_uid}", "kind": "text", "text": f"m{index}"},
        }))
        ack = await recv(a, "ack")
        msg_ids.append(ack["data"]["msg_id"])
        pushed = await recv(b, "message")
        assert pushed["data"]["text"] == f"m{index}"

    conversations = get("/conversations", b_uid)["items"]
    assert conversations[0]["unread"] == 3

    # 图片消息:上传后的 URL 必须带 IM_MEDIA_PREFIX,服务端才认
    image_url = MEDIA_PREFIX + "2026/10/e2e.jpg"
    await a.send(json.dumps({
        "v": 1,
        "type": "send",
        "id": "e2e-image",
        "data": {
            "client_msg_id": "e2e-image",
            "to": f"u{b_uid}",
            "kind": "image",
            "image": {"url": image_url,
                      "thumb_url": MEDIA_PREFIX + "2026/10/e2e_thumb.jpg",
                      "width": 1080, "height": 1440, "size": 345678},
        },
    }))
    await recv(a, "ack")
    pushed_image = await recv(b, "message")
    assert pushed_image["data"]["kind"] == "image"
    assert pushed_image["data"]["image"]["url"] == image_url
    history = get(f"/messages?peer=u{a_uid}", b_uid)["items"]
    assert any(item["kind"] == "image" for item in history)

    # 伪造外链必须被拒
    await a.send(json.dumps({
        "v": 1,
        "type": "send",
        "id": "e2e-image-bad",
        "data": {
            "client_msg_id": "e2e-image-bad",
            "to": f"u{b_uid}",
            "kind": "image",
            "image": {"url": "http://evil.example/a.jpg",
                      "thumb_url": MEDIA_PREFIX + "2026/10/e2e_thumb.jpg",
                      "width": 1080, "height": 1440, "size": 345678},
        },
    }))
    rejected = await recv(a, "error")
    assert rejected["data"]["code"] == 42201

    await a.send(json.dumps({
        "v": 1,
        "type": "send",
        "id": "e2e-0",
        "data": {"to": f"u{b_uid}", "kind": "text", "text": "m0"},
    }))
    again = await recv(a, "ack")
    assert again["data"]["msg_id"] == msg_ids[0]

    await a.send(json.dumps({
        "v": 1,
        "type": "revoke",
        "id": "e2e-revoke",
        "data": {"msg_id": msg_ids[0]},
    }))
    revoked = await recv(b, "revoked")
    assert revoked["data"]["msg_id"] == msg_ids[0]

    second = await auth(a_uid)
    kicked = await recv(a, "kicked")
    assert kicked["data"]["reason"] == "multi_device"

    await a.close()
    await b.close()
    await second.close()
    print("e2e ok")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:  # noqa: BLE001 - 脚本入口统一转退出码
        print(f"e2e failed: {error}", file=sys.stderr)
        raise SystemExit(1)
