"""`GET /im/api/search` 的 HTTP 集成测试。

覆盖:中文命中与排序、对端资料、游标分页、撤回后不可见、空关键词、未认证、
`limit` 上限收敛到 20、限流(每账号 10 次/分钟、burst 5 → 第 6 次起 429 + 42901)。

限流桶按账号共享,所以「断言链」与「限流断言」必须用**不同的 uid**:
同一个 uid 连打十几次会先撞到自己的桶(第五轮审计 M-2 把 search 的桶从
60 次/分钟、burst 20 压到 10 次/分钟、burst 5,余量变小,更不能再混用)。
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

from _support import ensure, pair

SECRET = os.environ["IM_JWT_SECRET"]
WS = os.environ.get("IM_TEST_WS", "ws://127.0.0.1:19100/im/ws")
HTTP = os.environ.get("IM_TEST_HTTP", "http://127.0.0.1:19101/im/api")
# 服务端 limit 的硬上限(M-2 从 50 收到 20):一次搜索的扫描成本与返回条数同阶。
LIMIT_CAP = 20


def token(uid: int) -> str:
    """签发测试用 IM JWT。"""
    now = int(time.time())
    return jwt.encode(
        {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600, "jti": "test"},
        SECRET,
        algorithm="HS256",
    )


def search(uid: int, keyword: str, limit: int = 20, before_id: int = 0):
    """调用搜索接口并返回 JSON。"""
    query = {"q": keyword, "limit": str(limit)}
    if before_id:
        query["before_id"] = str(before_id)
    request = urllib.request.Request(
        HTTP + "/search?" + urllib.parse.urlencode(query),
        headers={"Authorization": f"Bearer {token(uid)}"},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


def search_status(uid: int, keyword: str):
    """只关心状态码与业务码的搜索调用(用于错误分支)。

    Args:
        uid: 请求者账号 id。
        keyword: 关键词原样发送(含空白串)。

    Returns:
        ``(HTTP 状态码, 业务码)``;成功时业务码为 ``None``。
    """
    request = urllib.request.Request(
        HTTP + "/search?" + urllib.parse.urlencode({"q": keyword}),
        headers={"Authorization": f"Bearer {token(uid)}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, None
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read()).get("code")


async def auth(uid: int):
    """建立 WS 并完成首帧鉴权。"""
    ws = await websockets.connect(WS)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid)}}))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == "auth_ok":
            return ws


async def recv(ws, type_: str):
    """等指定类型的帧(跳过心跳等其它帧)。"""
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == type_:
            return message


async def send_text(ws, index: int, to: int, text: str):
    """发一条文本消息并等 ack。"""
    await ws.send(
        json.dumps(
            {
                "v": 1,
                "type": "send",
                "id": f"s-{index}",
                "data": {"to": f"u{to}", "kind": "text", "text": text},
            }
        )
    )
    await recv(ws, "ack")


async def main():
    """跑完整条断言链。"""
    base = 300000 + (int(time.time() * 1000) + os.getpid()) % 100000
    me, peer = base, base + 1
    # side:只用于「无命中 / 空关键词 / limit 上限」这三条不吃 me 的桶的断言。
    side = base + 2
    # limited:只用于限流断言,必须从**满桶**开始,所以单独一个从没搜过的账号。
    limited = base + 3
    for uid in (me, peer, side, limited):
        ensure(uid)
    pair(me, peer)
    # side 与 me 也配对:side 发的批量消息落在同一个会话里,双方都能搜到,
    # 用来验证「limit 传 50 也只返回 20 条」而不用再借 me 的令牌。
    pair(me, side)

    ws = await auth(peer)
    for index, text in enumerate(["晚上吃火锅吗", "火锅店在楼下", "今天天气不错"]):
        await send_text(ws, index, me, text)

    # 中文命中 + 新 → 旧 + 对端资料(me 的第 1 次搜索)
    result = search(me, "火锅")
    assert [item["text"] for item in result["items"]] == ["火锅店在楼下", "晚上吃火锅吗"]
    assert result["items"][0]["peer"]["id"] == f"u{peer}"
    assert result["items"][0]["kind"] == "text"
    assert result["has_more"] is False

    # 游标分页(me 的第 2、3 次搜索)
    first = search(me, "火锅", limit=1)
    assert first["has_more"] is True and len(first["items"]) == 1
    second = search(me, "火锅", limit=1, before_id=int(first["items"][0]["msg_id"]))
    assert [item["text"] for item in second["items"]] == ["晚上吃火锅吗"]

    # 无命中 / 空关键词 / 未认证(side 自己的桶,不占 me 的 5 个令牌)
    assert search(side, "不存在")["items"] == []
    status, code = search_status(side, "   ")
    assert (status, code) == (422, 42201), (status, code)
    anonymous = urllib.request.Request(HTTP + "/search?q=x")
    try:
        urllib.request.urlopen(anonymous, timeout=3)
        raise AssertionError("未认证应当 401")
    except urllib.error.HTTPError as error:
        assert error.code == 401

    # 撤回后不可见(me 的第 4 次搜索)
    target = first["items"][0]["msg_id"]
    await ws.send(
        json.dumps({"v": 1, "type": "revoke", "id": "r-1", "data": {"msg_id": target}})
    )
    await recv(ws, "ack")
    assert all(item["msg_id"] != target for item in search(me, "火锅")["items"])

    # limit 上限:即便客户端传 50,服务端也只给 20(M-2 的 clamp 上界)。
    # 用 side 发 25 条、side 自己搜,免得再借 me 的令牌。
    side_ws = await auth(side)
    for index in range(25):
        await send_text(side_ws, 100 + index, me, f"批量火锅 {index}")
    bulk = search(side, "批量", limit=50)
    assert len(bulk["items"]) == LIMIT_CAP, len(bulk["items"])
    assert bulk["has_more"] is True
    await side_ws.close()

    # 限流(M-2):每账号 10 次/分钟、burst 5 —— 新账号连打 11 次,
    # 前 5 次从满桶放行,第 6 次起一律 429 + 42901(不靠 sleep 等补令牌)。
    codes = [search_status(limited, "火锅") for _ in range(11)]
    assert codes[:5] == [(200, None)] * 5, codes
    assert codes[5:] == [(429, 42901)] * 6, codes

    await ws.close()


asyncio.run(main())
