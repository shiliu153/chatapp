"""已读回执的集成测试:下行 `read` 帧 + `peer_read_seq` 补拉 + 帧限流。

覆盖 backlog C-2 的四条验收:
    1. B 读完后 A **实时**收到下行 `read` 帧(帧里是**写完之后**的真实 seq);
    2. 乱序到达的旧 `read` 帧不会让已读位置回退(`GREATEST` 语义 + 回读);
    3. B 离线期间 A 继续发,B 重连后从 `GET /im/api/conversations` 的
       `peer_read_seq` 补拉(**不是** A 后来发的那条);
    4. `read` 帧有条数限制(每次都会给对端推一帧,不限流就能打爆对端)。
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
    """为测试账号签一个短时 JWT(与 Django 侧 `user_sig` 同口径)。"""
    now = int(time.time())
    return jwt.encode(
        {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600, "jti": "test"},
        SECRET,
        algorithm="HS256",
    )


def conversations(uid: int):
    """取某账号的会话列表(走 HTTP,补拉已读态的入口)。"""
    request = urllib.request.Request(
        HTTP + "/conversations", headers={"Authorization": f"Bearer {token(uid)}"}
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())["items"]


async def auth(uid: int):
    """连 WS 并完成握手。"""
    ws = await websockets.connect(WS)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid)}}))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == "auth_ok":
            return ws


async def recv_until(ws, type_, timeout=3):
    """丢弃无关帧,直到拿到指定类型(其它类型的帧留给调用方自己再收)。"""
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if message["type"] == type_:
            return message


async def send_text(ws, peer_uid: int, text: str, client_id: str):
    """发一条文本并等 ack,返回 ack 的 data(里面有 seq)。"""
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
    """发一个上行 read 帧并等 ack。"""
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


async def main():
    base = 300000 + (int(time.time() * 1000) + os.getpid()) % 90000
    reader_uid, writer_uid = base, base + 1
    ensure(reader_uid)
    ensure(writer_uid)
    pair(reader_uid, writer_uid)

    writer = await auth(writer_uid)
    reader = await auth(reader_uid)

    # 1. 三条消息,reader 全收到(顺带确认推送正常)
    last_seq = 0
    for index, text in enumerate(["一", "二", "三"]):
        ack = await send_text(writer, reader_uid, text, f"w-{index}")
        last_seq = ack["seq"]
        push = await recv_until(reader, "message")
        assert push["data"]["text"] == text
    assert last_seq == 3

    # 2. seq=0 表示「读到最新」:writer 收到下行 read 帧,seq 是真实值 3
    await mark_read(reader, writer_uid, 0, "r-1")
    receipt = await recv_until(writer, "read")
    assert receipt["data"] == {"peer": f"u{reader_uid}", "seq": 3}, receipt
    assert conversations(writer_uid)[0]["peer_read_seq"] == 3

    # 3. 乱序/旧值不回退:再发一个 seq=1,writer 收到的仍是 3(GREATEST + 回读)
    await mark_read(reader, writer_uid, 1, "r-2")
    stale = await recv_until(writer, "read")
    assert stale["data"]["seq"] == 3, stale

    # 4. 离线补拉:reader 断开 → writer 再发一条 → reader 重连后读到的仍是 3
    await reader.close()
    await asyncio.sleep(0.2)
    forth = await send_text(writer, reader_uid, "四", "w-3")
    assert forth["seq"] == 4

    reader = await auth(reader_uid)
    # reader 自己视角的 unread 应该是 1(第 4 条没读)
    assert conversations(reader_uid)[0]["unread"] == 1
    # writer 视角的 peer_read_seq 仍是 3 —— 第 4 条**没有被读**
    assert conversations(writer_uid)[0]["peer_read_seq"] == 3

    # 再读一次 → writer 收到 seq=4
    await mark_read(reader, writer_uid, 4, "r-3")
    fresh = await recv_until(writer, "read")
    assert fresh["data"]["seq"] == 4, fresh

    # 5. 限流:连发 40 个 read 帧,只有令牌桶允许的会被处理(30 突发 + 少量补充)
    sent = 40
    for index in range(sent):
        await reader.send(
            json.dumps(
                {
                    "v": 1,
                    "type": "read",
                    "id": f"burst-{index}",
                    "data": {"peer": f"u{writer_uid}", "seq": 4},
                }
            )
        )
    acks = 0
    try:
        while True:
            frame = json.loads(await asyncio.wait_for(reader.recv(), 1.0))
            if frame["type"] == "ack" and str(frame.get("id", "")).startswith("burst-"):
                acks += 1
            elif frame["type"] == "error":
                raise AssertionError(f"限流应当静默丢弃,不该回错误帧: {frame}")
    except asyncio.TimeoutError:
        pass
    assert 25 <= acks < sent, f"read 帧限流没生效或被误伤: acks={acks}"

    await writer.close()
    await reader.close()
    print(f"test_read ok: 下行 read 帧 / 不回退 / 补拉 / 限流(acks={acks})")


asyncio.run(main())
