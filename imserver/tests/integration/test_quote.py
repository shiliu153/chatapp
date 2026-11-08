"""引用回复(`ref_msg_id` + 服务端快照)的集成测试(批次 L-2)。

覆盖四条验收:
    1. **快照只能由服务端生成**:A 引用 B 的消息,下行 `message` 帧里的 `ref.text`
       是**库里的原文**(且按 120 字截断),客户端夹带的伪造快照被丢弃;
    2. **同会话校验**:`ref_msg_id` 指向别的会话里的消息 → `42201`,不落库;
    3. **已撤回标注**:引用一条已撤回的消息 → `ref.revoked=true` 且 `ref.text=""`;
    4. **历史回放**:`GET /im/api/messages` 里同样带回 `ref`(离线补拉也能显示)。

为什么第 1 条要专门发一个伪造快照的帧:客户端传快照 = 允许任何人伪造「对方说过 X」。
这条断言守的是安全边界,不是「顺手」——所以伪造内容是**整段**不同的一串中文,
只要服务端有一处读了客户端的 `ref`,断言立刻红。
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

#: 引用摘要的截断长度(与设计文档 §4.2 / imserver 的 kRefTextMax 一致)。
REF_TEXT_MAX = 120

#: 客户端伪造的引用内容。服务端只要有一处读了它,断言就会看到这一串。
FORGED_TEXT = "伪造的引用内容:对方从没这么说过"


def token(uid: int) -> str:
    """签一个测试 JWT(与 Django 侧 `mint_im_token` 同口径)。

    Args:
        uid: 账号 id。

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
    """带 Bearer 令牌读一次 IM HTTP 接口。

    Args:
        path: 以 `/` 开头的路径(相对 `IM_TEST_HTTP`)。
        uid: 以谁的身份读。

    Returns:
        解析后的 JSON。
    """
    request = urllib.request.Request(
        HTTP + path, headers={"Authorization": f"Bearer {token(uid)}"}
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


async def auth(uid: int):
    """连 WS 并完成握手。

    Args:
        uid: 账号 id。

    Returns:
        已鉴权的 ws 连接。
    """
    ws = await websockets.connect(WS)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid)}}))
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


async def send_text(ws, to_uid: int, text: str, client_id: str) -> str:
    """发一条普通文本消息,等 ack 并返回 msg_id。

    Args:
        ws: 发送方的连接。
        to_uid: 接收方账号 id。
        text: 正文。
        client_id: 幂等 id。

    Returns:
        服务端分配的 msg_id(字符串)。
    """
    await ws.send(
        json.dumps(
            {
                "v": 1,
                "type": "send",
                "id": client_id,
                "data": {
                    "client_msg_id": client_id,
                    "to": f"u{to_uid}",
                    "kind": "text",
                    "text": text,
                },
            },
            ensure_ascii=False,
        )
    )
    ack = await recv_until(ws, "ack")
    return str(ack["data"]["msg_id"])


async def send_quote(ws, to_uid: int, text: str, client_id: str, ref_msg_id: int,
                     forged_ref=None) -> dict:
    """发一条引用消息(可选夹带伪造的 `ref` 载荷)。

    Args:
        ws: 发送方的连接。
        to_uid: 接收方账号 id。
        text: 正文。
        client_id: 幂等 id。
        ref_msg_id: 被引用消息 id。
        forged_ref: 想夹带的伪造快照;服务端必须完全忽略它。

    Returns:
        服务端回来的第一帧(ack 或 error)。
    """
    data = {
        "client_msg_id": client_id,
        "to": f"u{to_uid}",
        "kind": "text",
        "text": text,
        "ref_msg_id": int(ref_msg_id),
    }
    if forged_ref is not None:
        data["ref"] = forged_ref
    await ws.send(
        json.dumps({"v": 1, "type": "send", "id": client_id, "data": data}, ensure_ascii=False)
    )
    return await recv_until(ws, "ack")


async def case_snapshot_is_server_side(base: int) -> None:
    """1. 快照由服务端生成:伪造的 `ref` 被丢弃,`ref.text` 是库里的原文且截断到 120 字。"""
    me, peer_uid = base, base + 1
    ensure(me)
    ensure(peer_uid)
    pair(me, peer_uid)
    my_ws = await auth(me)
    peer_ws = await auth(peer_uid)

    # 对端说一句短话,我来引用
    short_id = await send_text(peer_ws, me, "今晚吃饭?", "b-1")
    await recv_until(my_ws, "message")
    await send_quote(
        my_ws,
        peer_uid,
        "好,六点",
        "q-1",
        int(short_id),
        forged_ref={
            "msg_id": int(short_id),
            "from": f"u{me}",
            "kind": "text",
            "text": FORGED_TEXT,
            "revoked": False,
        },
    )
    pushed = await recv_until(peer_ws, "message")
    ref = pushed["data"]["ref"]
    assert ref["text"] == "今晚吃饭?", f"快照不是服务端生成的: {ref}"
    assert ref["text"] != FORGED_TEXT, f"落库的是客户端伪造的快照: {ref}"
    assert ref["from"] == f"u{peer_uid}", ref
    assert ref["kind"] == "text", ref
    assert ref["msg_id"] == int(short_id), ref
    assert ref["revoked"] is False, ref
    # 引用消息本身照常
    assert pushed["data"]["text"] == "好,六点", pushed["data"]

    # 超长文本:摘要必须按**字符**截到 120,且不能在半个汉字上切开
    long_text = "引" * 130
    long_id = await send_text(peer_ws, me, long_text, "b-2")
    await recv_until(my_ws, "message")
    await send_quote(my_ws, peer_uid, "这句太长了吧", "q-2", int(long_id))
    pushed = await recv_until(peer_ws, "message")
    assert pushed["data"]["ref"]["text"] == "引" * REF_TEXT_MAX, pushed["data"]["ref"]
    assert len(pushed["data"]["ref"]["text"]) == REF_TEXT_MAX

    for ws in (my_ws, peer_ws):
        await ws.close()


async def case_cross_conversation_rejected(base: int) -> None:
    """2. `ref_msg_id` 指向**别的会话**的消息 → 42201,且那条消息不会落库。"""
    me, peer_uid, stranger = base + 2, base + 3, base + 4
    for uid in (me, peer_uid, stranger):
        ensure(uid)
    pair(me, peer_uid)
    pair(peer_uid, stranger)
    my_ws = await auth(me)
    peer_ws = await auth(peer_uid)
    stranger_ws = await auth(stranger)

    # 这条消息在 (peer, stranger) 的会话里,不在 (me, peer) 的会话里
    foreign_id = await send_text(peer_ws, stranger, "别人的会话", "b-3")
    await recv_until(stranger_ws, "message")

    await my_ws.send(
        json.dumps(
            {
                "v": 1,
                "type": "send",
                "id": "q-3",
                "data": {
                    "client_msg_id": "q-3",
                    "to": f"u{peer_uid}",
                    "kind": "text",
                    "text": "跨会话引用",
                    "ref_msg_id": int(foreign_id),
                },
            },
            ensure_ascii=False,
        )
    )
    error = await recv_until(my_ws, "error")
    assert error["data"]["code"] == 42201, error

    # 不落库:历史里不能出现这条引用消息
    history = get(f"/messages?peer=u{me}&limit=50", peer_uid)["items"]
    assert all(item.get("text") != "跨会话引用" for item in history), history

    for ws in (my_ws, peer_ws, stranger_ws):
        await ws.close()


async def case_revoked_snapshot(base: int) -> None:
    """3. 引用一条已撤回的消息 → `ref.revoked=true` 且 `ref.text=""`(不泄漏原文)。"""
    me, peer_uid = base + 5, base + 6
    ensure(me)
    ensure(peer_uid)
    pair(me, peer_uid)
    my_ws = await auth(me)
    peer_ws = await auth(peer_uid)

    target_id = await send_text(my_ws, peer_uid, "马上撤回", "b-4")
    await recv_until(peer_ws, "message")
    await my_ws.send(
        json.dumps({"v": 1, "type": "revoke", "id": "v-1", "data": {"msg_id": target_id}})
    )
    await recv_until(my_ws, "ack")
    await recv_until(peer_ws, "revoked")

    # 对端引用这条已撤回的消息
    await send_quote(peer_ws, me, "你刚才说啥", "q-4", int(target_id))
    pushed = await recv_until(my_ws, "message")
    ref = pushed["data"]["ref"]
    assert ref["revoked"] is True, ref
    assert ref["text"] == "", ref
    assert ref["msg_id"] == int(target_id), ref

    for ws in (my_ws, peer_ws):
        await ws.close()


async def case_history_replays_ref(base: int) -> None:
    """4. `GET /im/api/messages` 历史里同样带回 `ref`(离线补拉也能显示引用)。"""
    me, peer_uid = base + 7, base + 8
    ensure(me)
    ensure(peer_uid)
    pair(me, peer_uid)
    my_ws = await auth(me)
    peer_ws = await auth(peer_uid)

    target_id = await send_text(peer_ws, me, "历史里的原话", "b-5")
    await recv_until(my_ws, "message")
    await send_quote(my_ws, peer_uid, "我引用一句", "q-5", int(target_id))
    await recv_until(peer_ws, "message")

    history = get(f"/messages?peer=u{me}&limit=50", peer_uid)["items"]
    quoted = [item for item in history if item.get("text") == "我引用一句"]
    assert len(quoted) == 1, history
    ref = quoted[0]["ref"]
    assert ref["msg_id"] == int(target_id), ref
    assert ref["from"] == f"u{peer_uid}", ref
    assert ref["text"] == "历史里的原话", ref
    assert ref["revoked"] is False, ref

    # 会话列表的 last_message 走同一个序列化函数,引用也必须跟着出来
    conversations = get("/conversations", peer_uid)["items"]
    last = conversations[0]["last_message"]
    assert last["ref"]["text"] == "历史里的原话", last

    for ws in (my_ws, peer_ws):
        await ws.close()


async def main() -> None:
    """依次跑四条用例(账号 id 按时间 + pid 取号,避免与其它用例撞号)。"""
    base = 700000 + (int(time.time() * 1000) + os.getpid()) % 90000
    await case_snapshot_is_server_side(base)
    await case_cross_conversation_rejected(base)
    await case_revoked_snapshot(base)
    await case_history_replays_ref(base)
    print("test_quote ok: 快照由服务端生成 / 跨会话 42201 / 已撤回标注 / 历史回放")


asyncio.run(main())
