"""聊天文字敏感词(批次 Q)集成测试。

覆盖五件事:
    1. 含敏感词的 ``send`` 回 ``42201``「消息包含违规内容」,且**不落库、不推送**;
    2. 拒发**不占 seq**:同一会话里下一条正常消息仍是 seq=1;
    3. 正常文本照常发送,对端实时收到;
    4. 贴纸(``kind=custom``)不受影响 —— 过滤只看 ``kind=text``;
    5. 服务端经 ``/internal/send`` 发的文本不被拦(灰条 / ``im_send`` 走的是内部 API,
       历史消息也照常回放):过滤只作用于**客户端上行**。

词表用 ``tests/fixtures/sensitive_words_test.txt``(由 docker-compose.test.yml 的
``IM_SENSITIVE_WORDS_FILE`` 指过去),词是 ``违禁测试词`` / ``testviolation``。
"""

import asyncio
import json
import os
import time
import urllib.request

import jwt
import websockets

from _support import call, ensure, pair

SECRET = os.environ["IM_JWT_SECRET"]
WS = os.environ.get("IM_TEST_WS", "ws://127.0.0.1:19100/im/ws")
HTTP = os.environ.get("IM_TEST_HTTP", "http://127.0.0.1:19101/im/api")
METRICS = os.environ.get("IM_TEST_METRICS", "http://127.0.0.1:19101/metrics")

# 与 tests/fixtures/sensitive_words_test.txt 保持一致
HIT_TEXT = "帮我看看这个违禁测试词"
CLEAN_TEXT = "今天天气不错,晚上一起吃饭?"


def token(uid: int) -> str:
    """签一枚测试用 IM token。"""
    now = int(time.time())
    return jwt.encode(
        {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600, "jti": "sensitive"},
        SECRET,
        algorithm="HS256",
    )


async def auth(uid: int):
    """握手 + auth 帧,返回已鉴权的连接。"""
    ws = await websockets.connect(WS)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid)}}))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == "auth_ok":
            return ws


async def recv(ws, type_):
    """收到指定 type 的下一帧。"""
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == type_:
            return message


def get_history(uid: int, peer: int):
    """拉一段历史消息(接收方视角)。"""
    request = urllib.request.Request(
        f"{HTTP}/messages?peer=u{peer}&limit=50",
        headers={"Authorization": f"Bearer {token(uid)}"},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())["items"]


def blocked_counter() -> int:
    """读 /metrics 里的 ``im_sensitive_blocked_total``(只允许回环,测试进程就在容器里)。"""
    with urllib.request.urlopen(METRICS, timeout=3) as response:
        text = response.read().decode()
    for line in text.splitlines():
        if line.startswith("im_sensitive_blocked_total "):
            return int(line.split()[1])
    raise AssertionError("指标里没有 im_sensitive_blocked_total:\n" + text)


def send_frame(client_msg_id: str, to_uid: int, **data) -> dict:
    """拼一帧上行 send(返回值给调用方 ``json.dumps`` 一次即可)。"""
    payload = {"client_msg_id": client_msg_id, "to": f"u{to_uid}"}
    payload.update(data)
    return {"v": 1, "type": "send", "id": client_msg_id, "data": payload}


async def main():
    base = 600000 + (int(time.time() * 1000) + os.getpid()) % 100000
    sender_uid, receiver_uid = base, base + 1
    ensure(sender_uid, "A")
    ensure(receiver_uid, "B")
    pair(sender_uid, receiver_uid)

    sender = await auth(sender_uid)
    receiver = await auth(receiver_uid)
    blocked_before = blocked_counter()

    # 1) 命中敏感词:错误帧 + 不落库 + 不推送
    await sender.send(json.dumps(send_frame("sc-1", receiver_uid, kind="text", text=HIT_TEXT)))
    error = await recv(sender, "error")
    assert error["data"]["code"] == 42201, error
    assert error["data"]["message"] == "消息包含违规内容", error
    # 对端什么都没收到(等待窗口内必须超时)
    try:
        leaked = await asyncio.wait_for(receiver.recv(), 0.5)
    except asyncio.TimeoutError:
        leaked = None
    assert leaked is None, leaked
    assert get_history(receiver_uid, sender_uid) == [], "被拦下的消息不该落库"

    # 2) 英文词同样命中且大小写不敏感
    await sender.send(json.dumps(send_frame("sc-2", receiver_uid, kind="text",
                                            text="hello TESTVIOLATION world")))
    english = await recv(sender, "error")
    assert english["data"]["code"] == 42201, english

    # 3) 正常文本照常发;拒发不占 seq,所以这里仍是 seq=1
    await sender.send(json.dumps(send_frame("sc-3", receiver_uid, kind="text", text=CLEAN_TEXT)))
    ack = await recv(sender, "ack")
    assert ack["id"] == "sc-3", ack
    assert ack["data"]["seq"] == 1, ack
    pushed = await recv(receiver, "message")
    assert pushed["data"]["text"] == CLEAN_TEXT, pushed

    # 4) 贴纸不受影响(过滤只看 kind=text)
    await sender.send(json.dumps(send_frame(
        "sc-4", receiver_uid, kind="custom",
        custom={"type": "sticker", "id": "sticker_07"})))
    sticker_ack = await recv(sender, "ack")
    assert sticker_ack["data"]["seq"] == 2, sticker_ack
    sticker_push = await recv(receiver, "message")
    assert sticker_push["data"]["kind"] == "custom", sticker_push

    # 5) 服务端 /internal/send 发的文本不被拦(过滤只在客户端上行这条路上),
    #    且历史接口照常回放 —— 「历史消息不受影响」的实证。
    call("/internal/send", {"from": sender_uid, "to": receiver_uid,
                            "kind": "text", "text": "系统代发:" + HIT_TEXT})
    await recv(receiver, "message")
    texts = [item.get("text") for item in get_history(receiver_uid, sender_uid)]
    assert any(text and HIT_TEXT in text for text in texts), texts

    # 6) 指标:这次至少拦了 2 条(中文 1 + 英文 1)
    blocked_after = blocked_counter()
    assert blocked_after >= blocked_before + 2, (blocked_before, blocked_after)

    await sender.close()
    await receiver.close()

    print("test_sensitive ok: 命中即 42201 不落库不推送 / 不占 seq / 正常文本照发 / "
          "贴纸不受影响 / 内部发的不拦 / 指标计数")


asyncio.run(main())
