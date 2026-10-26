"""图片消息:落库存规范 URL、推送与历史里读时签名、签名可被独立复算。"""

import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.request
from urllib.parse import parse_qs, urlsplit

import jwt
import websockets

SECRET = os.environ["IM_JWT_SECRET"]
SIGN_SECRET = os.environ["IM_MEDIA_SIGN_SECRET"]
MEDIA_PREFIX = os.environ["IM_MEDIA_PREFIX"]
WS = os.environ.get("IM_TEST_WS", "ws://127.0.0.1:19100/im/ws")
HTTP = os.environ.get("IM_TEST_HTTP", "http://127.0.0.1:19101/im/api")


def token(uid: int) -> str:
    """签发测试用 IM JWT。

    Args:
        uid: 用户数字 id。

    Returns:
        HS256 JWT 字符串。
    """
    now = int(time.time())
    return jwt.encode(
        {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600, "jti": "test"},
        SECRET,
        algorithm="HS256",
    )


def get(path: str, uid: int):
    """带鉴权发 GET 请求并解析 JSON。

    Args:
        path: 相对 ``/im/api`` 的路径。
        uid: 用户数字 id。

    Returns:
        解析后的 JSON。
    """
    request = urllib.request.Request(
        HTTP + path, headers={"Authorization": f"Bearer {token(uid)}"}
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


async def auth(uid: int):
    """建立 WS 连接并完成 auth 帧握手。

    Args:
        uid: 用户数字 id。

    Returns:
        已认证的 websocket 连接。
    """
    ws = await websockets.connect(WS)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid)}}))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == "auth_ok":
            return ws


async def recv(ws, type_):
    """等待指定类型的帧。

    Args:
        ws: websocket 连接。
        type_: 期望的帧类型。

    Returns:
        该类型的帧。
    """
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == type_:
            return message


def assert_signed(url: str) -> None:
    """断言 URL 带有效签名,并按共享算法独立复算。

    Args:
        url: 服务端下发的图片 URL。

    Raises:
        AssertionError: 签名不符或已过期。
    """
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    expires = int(query["e"][0])
    expected = hmac.new(
        SIGN_SECRET.encode(), f"{parts.path}\n{expires}".encode(), hashlib.sha256
    ).hexdigest()
    assert query["s"][0] == expected, (url, expected)
    assert expires > time.time()


async def main():
    """跑一遍图片消息的发送、推送、历史与会话列表签名校验。"""
    base = 300000 + (int(time.time() * 1000) + os.getpid()) % 100000
    sender_uid, receiver_uid = base, base + 1
    sender = await auth(sender_uid)
    receiver = await auth(receiver_uid)
    image = {
        "url": MEDIA_PREFIX + "2026/10/12-abc.jpg?e=1&s=stale",
        "thumb_url": MEDIA_PREFIX + "2026/10/12-abc_thumb.jpg",
        "width": 100,
        "height": 200,
        "size": 1024,
    }
    await sender.send(json.dumps({
        "v": 1, "type": "send", "id": "img-1",
        "data": {"to": f"u{receiver_uid}", "kind": "image", "image": image},
    }))
    pushed = await recv(receiver, "message")
    assert_signed(pushed["data"]["image"]["url"])
    assert_signed(pushed["data"]["image"]["thumb_url"])
    assert "stale" not in pushed["data"]["image"]["url"]

    history = get(f"/messages?peer=u{sender_uid}&limit=50", receiver_uid)["items"]
    assert_signed(history[0]["image"]["url"])
    assert history[0]["image"]["url"].count("?") == 1

    conversations = get("/conversations", receiver_uid)["items"]
    assert_signed(conversations[0]["last_message"]["image"]["url"])

    await sender.close()
    await receiver.close()


asyncio.run(main())
