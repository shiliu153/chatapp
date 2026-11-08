"""输入中状态(`typing`)的集成测试:只发对端、限流静默、未配对不发。

覆盖批次 L(L-1)的三条验收:
    1. A 打字 → **对端**收到下行 `typing`;A 自己另一端(`web`)收不到
       —— `send_to` 是多端扇出,若直接复用就会把自己也刷一遍;
    2. 连发 10 帧 → 对端只收到 1~4 帧(1 次 / 2 秒、突发 3 的令牌桶),
       且**全程没有任何 error 帧**(超限静默丢弃);
    3. 未配对 → 对端与发起端**都收不到任何帧**(同样静默,不回错误)。

为什么每条都要断言「没有错误帧」:typing 是**可丢信号**。给洪泛者任何反馈
(42901 / 42201)都等于告诉他「帧收到了,继续打」,而正常用户这边只该表现为
「对方没在打字」——所以服务端一律静默返回。
"""

import asyncio
import json
import os
import time

import jwt
import websockets

from _support import ensure, pair

SECRET = os.environ["IM_JWT_SECRET"]
WS = os.environ.get("IM_TEST_WS", "ws://127.0.0.1:19100/im/ws")


def token(uid: int, client_type: str = "app") -> str:
    """签一个带端类型的测试 JWT(与 Django 侧 `mint_im_token` 同口径)。

    Args:
        uid: 账号 id。
        client_type: `app` 或 `web`。

    Returns:
        HS256 JWT 字符串。
    """
    now = int(time.time())
    return jwt.encode(
        {
            "sub": f"u{uid}",
            "uid": uid,
            "iat": now,
            "exp": now + 3600,
            "jti": "test",
            "ct": client_type,
        },
        SECRET,
        algorithm="HS256",
    )


async def connect(uid: int, client_type: str = "app"):
    """连 WS 并完成握手。

    Args:
        uid: 账号 id。
        client_type: `app` 或 `web`。

    Returns:
        握手成功的 ws 连接。
    """
    ws = await websockets.connect(WS)
    await ws.send(
        json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid, client_type)}})
    )
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == "auth_ok":
            return ws
        if message["type"] == "error":
            raise AssertionError(f"鉴权失败: {message}")


async def recv_until(ws, type_, timeout=3):
    """丢弃无关帧,直到拿到指定类型。

    Args:
        ws: 已鉴权的连接。
        type_: 期望的帧类型。
        timeout: 单帧等待上限(秒)。

    Returns:
        命中的帧(dict)。
    """
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if message["type"] == type_:
            return message


async def expect_silence(ws, seconds=1.0):
    """断言这段时间内**没有任何**帧下发(错误帧也不行)。

    Args:
        ws: 已鉴权的连接。
        seconds: 观察窗口(秒)。
    """
    try:
        frame = json.loads(await asyncio.wait_for(ws.recv(), seconds))
    except asyncio.TimeoutError:
        return
    raise AssertionError(f"不该收到任何帧,却收到: {frame}")


async def send_typing(ws, peer_uid: int) -> None:
    """发一个上行 `typing` 帧(没有 id、不等 ack)。

    Args:
        ws: 发送方的连接。
        peer_uid: 收件人账号 id。
    """
    await ws.send(json.dumps({"v": 1, "type": "typing", "data": {"to": f"u{peer_uid}"}}))


async def case_typing_reaches_peer_only(base: int) -> None:
    """1. A 打字:B 收到 typing;A 自己的另一端**收不到**(只发对端)。"""
    me, peer_uid = base, base + 1
    ensure(me)
    ensure(peer_uid)
    pair(me, peer_uid)
    app_ws = await connect(me, "app")
    web_ws = await connect(me, "web")
    peer_ws = await connect(peer_uid, "app")

    await send_typing(app_ws, peer_uid)
    frame = await recv_until(peer_ws, "typing")
    # peer 是**收帧者**的对端:对端看到的「正在打字的人」是 me
    assert frame["data"] == {"peer": f"u{me}"}, frame
    # 多端在线:发起端自己的另一台设备绝不能收到(否则会显示「我自己正在输入」)
    await expect_silence(web_ws, 1.0)
    # 发起端自己也不该收到任何回执(typing 不 ack)
    await expect_silence(app_ws, 0.5)

    for ws in (app_ws, web_ws, peer_ws):
        await ws.close()


async def case_typing_is_rate_limited(base: int) -> None:
    """2. 连发 10 帧:对端收到的远少于 10,且**不产生错误帧**(静默丢弃)。"""
    me, peer_uid = base + 2, base + 3
    ensure(me)
    ensure(peer_uid)
    pair(me, peer_uid)
    app_ws = await connect(me)
    peer_ws = await connect(peer_uid)

    for _ in range(10):
        await send_typing(app_ws, peer_uid)

    received = 0
    try:
        while True:
            message = json.loads(await asyncio.wait_for(peer_ws.recv(), 2))
            # 令牌桶 1 次 / 2 秒、突发 3:10 帧里最多漏过去 3~4 帧,其余静默丢弃。
            # 断言类型只能是 typing —— 出现 error 就说明服务端回执了,那是错的。
            assert message["type"] == "typing", message
            received += 1
    except asyncio.TimeoutError:
        pass
    assert 1 <= received <= 4, received
    # 发起端不该收到任何错误回执(42901 也不行)
    await expect_silence(app_ws, 0.5)

    for ws in (app_ws, peer_ws):
        await ws.close()


async def case_typing_requires_pair(base: int) -> None:
    """3. 未配对:对端收不到任何帧(静默丢弃,不回错误)。"""
    me, stranger = base + 4, base + 5
    ensure(me)
    ensure(stranger)
    app_ws = await connect(me)
    other_ws = await connect(stranger)

    await send_typing(app_ws, stranger)
    await expect_silence(other_ws, 1.5)
    await expect_silence(app_ws, 0.5)

    await app_ws.close()
    await other_ws.close()


async def main() -> None:
    """依次跑三条用例(账号 id 按时间 + pid 取号,避免与其它用例撞号)。"""
    base = 600000 + (int(time.time() * 1000) + os.getpid()) % 90000
    await case_typing_reaches_peer_only(base)
    await case_typing_is_rate_limited(base)
    await case_typing_requires_pair(base)
    print("test_typing ok: 只发对端 / 限流静默 / 未配对不发")


asyncio.run(main())
