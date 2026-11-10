"""`POST /im/api/messages/delete`(多选删除,批次 T)的 HTTP 集成测试。

覆盖验收口径(设计见 `docs/superpowers/plans/2026-11-10-batch-t-chat-polish.md` Task 1):
    1. 删后**我的**历史不含、**对端历史仍含**(单方语义);
    2. 删未读 → 未读减少;删已读 → 未读**不变**;
    3. 删掉最后一条后**我的** `last_message` 落到上一条可见、对端不变、`last_seq` 不变;
    4. 搜索不再命中(对端仍能搜到);
    5. 超限:51 条 / 空数组 / 元素非法 → `400` + `42201`;
    6. 幂等:同一批删两次,第一次 `deleted=N`、第二次 `deleted=0`,历史条数不变;
    7. 别人的 `msg_id` 混在批量里 → 不报错、不计入 `deleted`、那条消息对谁都还在;
    8. 无 token → `401` + `40101`;`GET` → `405` + `40501`。

设计要点:每个场景用**独立账号对**,因为该接口按账号限流(令牌桶 1/s、突发 10),
一组用例连打十几次会被自己的限流挡成 `429`(那不是被测行为)。
"""

import asyncio
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

import jwt
import websockets

from _support import call, ensure, pair

SECRET = os.environ["IM_JWT_SECRET"]
WS = os.environ.get("IM_TEST_WS", "ws://127.0.0.1:19100/im/ws")
HTTP = os.environ.get("IM_TEST_HTTP", "http://127.0.0.1:19101/im/api")


def token(uid: int) -> str:
    """为测试账号签一个短时 IM JWT(与 Django 侧 `user_sig` 同口径)。

    Args:
        uid: 账号 id。

    Returns:
        编码好的 HS256 JWT。
    """
    now = int(time.time())
    return jwt.encode(
        {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600, "jti": "test"},
        SECRET,
        algorithm="HS256",
    )


def request(uid, path: str, payload=None, method: str = "GET"):
    """发一次 HTTP 请求并返回 `(状态码, JSON)`,4xx/5xx 不抛异常。

    Args:
        uid: 账号 id;`None` 表示不带令牌(用来验证 401)。
        path: 相对 `http_url` 的路径,如 `/messages/delete`。
        payload: JSON 请求体;`None` 表示不带 body。
        method: HTTP 方法。

    Returns:
        `(状态码, 解析后的 JSON)`。
    """
    data = None if payload is None else json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if uid is not None:
        headers["Authorization"] = f"Bearer {token(uid)}"
    req = urllib.request.Request(HTTP + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=3) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        body = error.read()
        return error.code, json.loads(body) if body else {}


def delete(uid, ids):
    """调用多选删除接口。

    Args:
        uid: 账号 id。
        ids: 消息 id 列表(字符串或整数混着传,接口两种都收)。

    Returns:
        `(状态码, JSON)`。
    """
    return request(uid, "/messages/delete", {"ids": ids}, "POST")


def history(uid: int, peer: int):
    """取我和某人的历史消息(旧 → 新)。

    Args:
        uid: 请求者账号 id。
        peer: 对端账号 id。

    Returns:
        `items` 列表。
    """
    status, body = request(uid, f"/messages?peer=u{peer}&limit=50")
    assert status == 200, body
    return body["items"]


def conversation_of(uid: int, peer: int):
    """取会话列表里与某人对谈的那一项。

    Args:
        uid: 请求者账号 id。
        peer: 对端账号 id。

    Returns:
        列表项(含 `unread` / `last_message` / `last_seq`)。
    """
    status, body = request(uid, "/conversations")
    assert status == 200, body
    for item in body["items"]:
        if item["peer"]["id"] == f"u{peer}":
            return item
    raise AssertionError(f"会话列表里没有 u{peer}: {body['items']}")


def unread(uid: int, peer: int) -> int:
    """取我对某人的未读数。

    Args:
        uid: 请求者账号 id。
        peer: 对端账号 id。

    Returns:
        未读条数。
    """
    return conversation_of(uid, peer)["unread"]


def search(uid: int, keyword: str):
    """调用搜索接口,返回命中的文本列表(新 → 旧)。

    Args:
        uid: 请求者账号 id。
        keyword: 关键词。

    Returns:
        `text` 列表。
    """
    query = urllib.parse.urlencode({"q": keyword})
    status, body = request(uid, "/search?" + query)
    assert status == 200, body
    return [item.get("text") for item in body["items"]]


def push(sender: int, receiver: int, texts) -> None:
    """通过内部 HMAC 接口代发若干条文本(只为造数据,不依赖 WS)。

    Args:
        sender: 发送方账号 id。
        receiver: 接收方账号 id。
        texts: 文本列表。
    """
    for text in texts:
        result = call("/internal/send", {"from": sender, "to": receiver, "kind": "text",
                                         "text": text})
        assert result.get("ok") is True, result


def prepare(a: int, b: int) -> None:
    """建号 + 配对(发送前必须有配对关系)。

    Args:
        a: 一方账号 id。
        b: 另一方账号 id。
    """
    ensure(a)
    ensure(b)
    pair(a, b)


def msg_id_of(uid: int, peer: int, text: str) -> str:
    """按正文找我这边历史里的那条消息,返回它的 `msg_id`。

    Args:
        uid: 请求者账号 id。
        peer: 对端账号 id。
        text: 消息正文。

    Returns:
        `msg_id` 字符串。
    """
    for item in history(uid, peer):
        if item.get("text") == text:
            return item["msg_id"]
    raise AssertionError(f"历史里没有「{text}」")


async def mark_read(uid: int, peer: int, seq: int) -> None:
    """用 WS `read` 帧把某会话标到已读(删除接口没有「标已读」的 HTTP 入口)。

    Args:
        uid: 读消息的人。
        peer: 会话对端。
        seq: 读到哪。
    """
    async with websockets.connect(WS) as ws:
        await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid)}}))
        while True:
            message = json.loads(await asyncio.wait_for(ws.recv(), 3))
            if message["type"] == "auth_ok":
                break
        await ws.send(
            json.dumps({"v": 1, "type": "read", "id": "r-1",
                        "data": {"peer": f"u{peer}", "seq": seq}})
        )
        while True:
            message = json.loads(await asyncio.wait_for(ws.recv(), 3))
            if message["type"] == "ack" and message.get("id") == "r-1":
                return


def scenario_single_sided(base: int) -> None:
    """① 删后我的历史不含、对端历史仍含(单方语义)。

    Args:
        base: 本场景的账号 id 起点。
    """
    a, b = base, base + 1
    prepare(a, b)
    push(a, b, ["一", "二", "三"])
    assert [item["text"] for item in history(b, a)] == ["一", "二", "三"]

    status, body = delete(b, [msg_id_of(b, a, "二")])
    assert status == 200 and body == {"deleted": 1}, (status, body)

    assert [item["text"] for item in history(b, a)] == ["一", "三"]
    # 对端历史一个字都不能少:这是「只删我这边」
    assert [item["text"] for item in history(a, b)] == ["一", "二", "三"]


def scenario_unread(base: int) -> None:
    """② 删未读 → 未读减少;删已读 → 未读不变。

    Args:
        base: 本场景的账号 id 起点。
    """
    a, b = base, base + 1
    prepare(a, b)
    push(a, b, ["一", "二", "三"])
    assert unread(b, a) == 3, unread(b, a)

    # 标到 seq=2(未读清零、read_seq=2),再让对端发两条 → 未读 2 条(seq 4、5)
    asyncio.run(mark_read(b, a, 2))
    assert unread(b, a) == 0, unread(b, a)
    push(a, b, ["四", "五"])
    assert unread(b, a) == 2, unread(b, a)

    # 删**已读**的那条(seq=2):它本来就没算进未读里,减它就是把计数搞坏
    status, body = delete(b, [msg_id_of(b, a, "二")])
    assert status == 200 and body == {"deleted": 1}, (status, body)
    assert unread(b, a) == 2, unread(b, a)

    # 删**未读**的那条(seq=4)→ 未读 2 → 1
    status, body = delete(b, [msg_id_of(b, a, "四")])
    assert status == 200 and body == {"deleted": 1}, (status, body)
    assert unread(b, a) == 1, unread(b, a)

    # 历史口径与未读口径必须一致:剩下的可见消息 = 一 / 三 / 五
    assert [item["text"] for item in history(b, a)] == ["一", "三", "五"]


def scenario_last_message_and_search(base: int) -> None:
    """③④ 我的 last_message 落到上一条可见(对端不变),搜索不再命中(对端仍能搜到)。

    Args:
        base: 本场景的账号 id 起点。
    """
    a, b = base, base + 1
    prepare(a, b)
    push(a, b, ["火锅一", "火锅二", "火锅三"])

    before = conversation_of(b, a)
    assert before["last_message"]["text"] == "火锅三", before
    assert before["last_seq"] == 3, before

    status, body = delete(b, [msg_id_of(b, a, "火锅三")])
    assert status == 200 and body == {"deleted": 1}, (status, body)

    after = conversation_of(b, a)
    assert after["last_message"]["text"] == "火锅二", after
    # `last_seq` 是会话全局的语义,删自己的副本不该动它
    assert after["last_seq"] == 3, after
    # 对端看到的摘要仍是原来那条
    peer_view = conversation_of(a, b)
    assert peer_view["last_message"]["text"] == "火锅三", peer_view
    assert peer_view["last_seq"] == 3, peer_view

    # 搜索口径同历史:删了就不能再被搜到,对端仍能搜到
    assert search(b, "火锅") == ["火锅二", "火锅一"], search(b, "火锅")
    assert search(a, "火锅") == ["火锅三", "火锅二", "火锅一"], search(a, "火锅")


def scenario_validation(base: int) -> None:
    """⑤ 参数校验:空数组 / 51 条 / 元素非法 / ids 不是数组 → `400` + `42201`。

    Args:
        base: 本场景的账号 id 起点。
    """
    a, b = base, base + 1
    # 元素级校验单独用一个账号发:该接口按账号限流(突发 10),一个账号连打十几次
    # 会把「参数校验」测成 `429`。
    other = base + 4
    prepare(a, b)
    ensure(other)
    push(a, b, ["甲"])

    status, body = delete(b, [])
    assert status == 400 and body["code"] == 42201, (status, body)
    status, body = delete(b, [str(90_000_000 + i) for i in range(51)])
    assert status == 400 and body["code"] == 42201, (status, body)
    status, body = request(b, "/messages/delete", {"ids": "不是数组"}, "POST")
    assert status == 400 and body["code"] == 42201, (status, body)
    status, body = request(b, "/messages/delete", {"nope": []}, "POST")
    assert status == 400 and body["code"] == 42201, (status, body)
    # 元素级:非数字 / 0 / 负数 / 小数 / 布尔 / 空串
    for bad in (["abc"], [0], [-1], [1.5], [True], [""]):
        status, body = delete(other, bad)
        assert status == 400 and body["code"] == 42201, (bad, status, body)
    # 这些请求一条都不该落隐藏行:历史仍是那一条
    assert [item["text"] for item in history(b, a)] == ["甲"]


def scenario_idempotency_and_foreign(base: int) -> None:
    """⑥⑦ 幂等(第二次 `deleted=0`)与别人的 msg_id 静默忽略。

    Args:
        base: 本场景的账号 id 起点。
    """
    a, b = base, base + 1
    other_a, other_b = base + 2, base + 3
    prepare(a, b)
    prepare(other_a, other_b)
    push(a, b, ["甲", "乙"])
    push(other_a, other_b, ["丙"])

    # ⑥ 同一批删两次:第一次 = 条数,第二次 = 0,历史条数不变
    batch = [item["msg_id"] for item in history(b, a)]
    assert len(batch) == 2, batch
    status, body = delete(b, batch)
    assert status == 200 and body == {"deleted": 2}, (status, body)
    status, body = delete(b, batch)
    assert status == 200 and body == {"deleted": 0}, (status, body)
    assert history(b, a) == []
    assert [item["text"] for item in history(a, b)] == ["甲", "乙"]

    # ⑦ 别人的 msg_id 混在批量里 → 不报错、不计入、那条消息对谁都还在
    push(a, b, ["丁"])
    foreign = msg_id_of(other_b, other_a, "丙")
    status, body = delete(b, [msg_id_of(b, a, "丁"), foreign])
    assert status == 200 and body == {"deleted": 1}, (status, body)
    assert history(b, a) == []
    assert [item["text"] for item in history(other_b, other_a)] == ["丙"]
    assert [item["text"] for item in history(other_a, other_b)] == ["丙"]


def scenario_auth_and_method(base: int) -> None:
    """⑧ 无 token → 401 + 40101;GET → 405 + 40501。

    Args:
        base: 本场景的账号 id 起点。
    """
    uid = base
    ensure(uid)
    status, body = request(None, "/messages/delete", {"ids": ["1"]}, "POST")
    assert status == 401 and body["code"] == 40101, (status, body)
    status, body = request(uid, "/messages/delete")
    assert status == 405 and body["code"] == 40501, (status, body)


def main() -> None:
    """跑完全部场景(每个场景一对独立账号,避免撞自己的限流桶)。"""
    base = 600000 + (int(time.time() * 1000) + os.getpid()) % 200000
    scenario_auth_and_method(base)
    scenario_single_sided(base + 10)
    scenario_unread(base + 20)
    scenario_last_message_and_search(base + 30)
    scenario_validation(base + 40)
    scenario_idempotency_and_foreign(base + 50)
    print("test_delete ok: 单方历史 / 未读增减 / last_message / 搜索 / 42201 / 幂等 / 忽略他人 id / 401 / 405")


main()
