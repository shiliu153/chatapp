"""跨端同步帧的集成测试:`self_read`(跨端已读)与 `conversation_deleted`(跨端删除)。

覆盖批次 K(K-3)的四条验收:
    1. 同账号 `app` + `web` 在线,`app` 发上行 `read` → **对端**收到下行 `read`,
       `web` 收到 `self_read`,且 `seq` 是**回读实库后**的真实值(不是请求里带的);
    2. `app` 删会话 → `web` 收到 `conversation_deleted`;**对端收不到任何帧**
       (删会话是单方行为,对方不该知道);
    3. 自己只有一端在线时,`self_read` / `conversation_deleted` 不产生任何下行
       (不能发给自己这条连接);
    4. 乱序/重复的上行 `read` 不会让 `self_read` 的 `seq` 回退(与下行 `read` 同口径)。

为什么两个帧都要单独测:它们的收帧人都是「**我自己的其他端**」,而不是对端。
复用下行 `read` 帧会被客户端读成「对方已读」,是假已读;`conversation_deleted`
发给对方则会泄露单方操作。
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


def token(uid: int, client_type: str) -> str:
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


async def connect(uid: int, client_type: str):
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
    """断言这段时间内**没有任何**帧下发。

    Args:
        ws: 已鉴权的连接。
        seconds: 观察窗口(秒)。
    """
    try:
        frame = json.loads(await asyncio.wait_for(ws.recv(), seconds))
    except asyncio.TimeoutError:
        return
    raise AssertionError(f"不该收到任何帧,却收到: {frame}")


async def send_text(ws, peer_uid: int, text: str, client_id: str):
    """发一条文本并等 ack。

    Args:
        ws: 发送方的连接。
        peer_uid: 收件人账号 id。
        text: 文本内容。
        client_id: 上行帧 id。

    Returns:
        ack 的 data(含 msg_id / seq)。
    """
    await ws.send(
        json.dumps(
            {
                "v": 1,
                "type": "send",
                "id": client_id,
                "data": {"to": f"u{peer_uid}", "kind": "text", "text": text},
            }
        )
    )
    ack = await recv_until(ws, "ack")
    assert ack["id"] == client_id, ack
    return ack["data"]


async def mark_read(ws, peer_uid: int, seq: int, client_id: str):
    """发一个上行 `read` 帧并等 ack。

    Args:
        ws: 读消息一方的连接。
        peer_uid: 会话对端账号 id。
        seq: 请求的已读位置(0 = 读到最新)。
        client_id: 上行帧 id。
    """
    await ws.send(
        json.dumps(
            {
                "v": 1,
                "type": "read",
                "id": client_id,
                "data": {"peer": f"u{peer_uid}", "seq": seq},
            }
        )
    )
    ack = await recv_until(ws, "ack")
    assert ack["id"] == client_id, ack
    assert ack["data"]["ok"] is True, ack


async def case_read_fans_out_to_own_other_client(base: int) -> None:
    """1. `app` 读消息:对端收 `read`,`web` 收 `self_read`(seq 是回读后的真值)。"""
    me, peer_uid = base, base + 1
    ensure(me)
    ensure(peer_uid)
    pair(me, peer_uid)
    app_ws = await connect(me, "app")
    web_ws = await connect(me, "web")
    peer_ws = await connect(peer_uid, "app")

    last_seq = 0
    for index, text in enumerate(["一", "二", "三"]):
        ack = await send_text(peer_ws, me, text, f"peer-{index}")
        last_seq = ack["seq"]
        # 本人两端都收到下行 message(K-2 的扇出)
        for ws in (app_ws, web_ws):
            pushed = await recv_until(ws, "message")
            assert pushed["data"]["text"] == text, pushed
    assert last_seq == 3, last_seq

    # seq=0 表示「读到最新」:对端收到的 read 帧里是回读后的真实值 3
    await mark_read(app_ws, peer_uid, 0, "r-1")
    receipt = await recv_until(peer_ws, "read")
    assert receipt["data"] == {"peer": f"u{me}", "seq": 3}, receipt

    # 自己的另一端收到 self_read:peer 是**会话对端**,seq 同样是 3
    self_read = await recv_until(web_ws, "self_read")
    assert self_read["data"] == {"peer": f"u{peer_uid}", "seq": 3}, self_read
    # 发起端自己不该收到 self_read(只发给本人的其他端)
    await expect_silence(app_ws, 0.5)

    for ws in (app_ws, web_ws, peer_ws):
        await ws.close()


async def case_delete_fans_out_only_to_own_clients(base: int) -> None:
    """2. `app` 删会话:`web` 收 `conversation_deleted`,对端**一帧都收不到**。"""
    me, peer_uid = base + 2, base + 3
    ensure(me)
    ensure(peer_uid)
    pair(me, peer_uid)
    app_ws = await connect(me, "app")
    web_ws = await connect(me, "web")
    peer_ws = await connect(peer_uid, "app")

    await send_text(peer_ws, me, "删掉我", "peer-1")
    for ws in (app_ws, web_ws):
        await recv_until(ws, "message")

    await app_ws.send(
        json.dumps(
            {
                "v": 1,
                "type": "conversation_delete",
                "id": "del-1",
                "data": {"peer": f"u{peer_uid}"},
            }
        )
    )
    ack = await recv_until(app_ws, "ack")
    assert ack["id"] == "del-1" and ack["data"]["ok"] is True, ack

    deleted = await recv_until(web_ws, "conversation_deleted")
    assert deleted["data"] == {"peer": f"u{peer_uid}"}, deleted
    # 对端不该知道这次删除
    await expect_silence(peer_ws, 1.0)

    for ws in (app_ws, web_ws, peer_ws):
        await ws.close()


async def case_single_client_gets_no_downlink(base: int) -> None:
    """3. 自己只有一端在线:读 / 删都不产生下行(不能发给自己这条连接)。"""
    me, peer_uid = base + 4, base + 5
    ensure(me)
    ensure(peer_uid)
    pair(me, peer_uid)
    peer_ws = await connect(peer_uid, "app")
    app_ws = await connect(me, "app")
    await send_text(peer_ws, me, "只有一端", "peer-1")
    pushed = await recv_until(app_ws, "message")
    assert pushed["data"]["text"] == "只有一端", pushed

    await mark_read(app_ws, peer_uid, 0, "r-1")
    # 对端会收到 read 帧(这是对的);但 app 自己不该收到 self_read
    await recv_until(peer_ws, "read")
    await expect_silence(app_ws, 1.0)

    await app_ws.send(
        json.dumps(
            {
                "v": 1,
                "type": "conversation_delete",
                "id": "del-1",
                "data": {"peer": f"u{peer_uid}"},
            }
        )
    )
    await recv_until(app_ws, "ack")
    await expect_silence(app_ws, 1.0)

    await app_ws.close()
    await peer_ws.close()


async def case_self_read_never_goes_back(base: int) -> None:
    """4. 乱序/重复的 read 不会让 `self_read` 的 seq 回退。"""
    me, peer_uid = base + 6, base + 7
    ensure(me)
    ensure(peer_uid)
    pair(me, peer_uid)
    app_ws = await connect(me, "app")
    web_ws = await connect(me, "web")
    peer_ws = await connect(peer_uid, "app")

    for index in range(2):
        await send_text(peer_ws, me, f"消息{index}", f"peer-{index}")
        for ws in (app_ws, web_ws):
            await recv_until(ws, "message")

    await mark_read(app_ws, peer_uid, 0, "r-1")
    assert (await recv_until(web_ws, "self_read"))["data"]["seq"] == 2
    await recv_until(peer_ws, "read")

    # 旧值(1)与重复值(2)都不该把已读推回去
    await mark_read(app_ws, peer_uid, 1, "r-2")
    assert (await recv_until(web_ws, "self_read"))["data"]["seq"] == 2
    await mark_read(app_ws, peer_uid, 2, "r-3")
    assert (await recv_until(web_ws, "self_read"))["data"]["seq"] == 2
    await recv_until(peer_ws, "read")
    await recv_until(peer_ws, "read")

    for ws in (app_ws, web_ws, peer_ws):
        await ws.close()


async def main() -> None:
    """依次跑四条用例(账号 id 按时间 + pid 取号,避免与其它测试撞号)。"""
    base = 500000 + (int(time.time() * 1000) + os.getpid()) % 90000
    await case_read_fans_out_to_own_other_client(base)
    await case_delete_fans_out_only_to_own_clients(base)
    await case_single_client_gets_no_downlink(base)
    await case_self_read_never_goes_back(base)
    print("test_self_read ok: 跨端已读扇出 / 跨端删除只发自己 / 单端不产生下行 / seq 不回退")


asyncio.run(main())
