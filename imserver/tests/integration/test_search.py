"""`GET /im/api/search` 的 HTTP 集成测试。

覆盖:中文命中与排序、对端资料、游标分页、撤回后不可见、空关键词、未认证、限流。
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

SECRET = os.environ["IM_JWT_SECRET"]
WS = os.environ.get("IM_TEST_WS", "ws://127.0.0.1:19100/im/ws")
HTTP = os.environ.get("IM_TEST_HTTP", "http://127.0.0.1:19101/im/api")


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


def status_of(uid: int, keyword: str) -> int:
    """只关心状态码的搜索调用(用于错误分支)。"""
    request = urllib.request.Request(
        HTTP + "/search?" + urllib.parse.urlencode({"q": keyword}),
        headers={"Authorization": f"Bearer {token(uid)}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


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


async def main():
    """跑完整条断言链。"""
    base = 300000 + (int(time.time() * 1000) + os.getpid()) % 100000
    me, peer = base, base + 1
    ws = await auth(peer)
    for index, text in enumerate(["晚上吃火锅吗", "火锅店在楼下", "今天天气不错"]):
        await ws.send(
            json.dumps(
                {
                    "v": 1,
                    "type": "send",
                    "id": f"s-{index}",
                    "data": {"to": f"u{me}", "kind": "text", "text": text},
                }
            )
        )
        await recv(ws, "ack")

    # 中文命中 + 新 → 旧 + 对端资料
    result = search(me, "火锅")
    assert [item["text"] for item in result["items"]] == ["火锅店在楼下", "晚上吃火锅吗"]
    assert result["items"][0]["peer"]["id"] == f"u{peer}"
    assert result["items"][0]["kind"] == "text"
    assert result["has_more"] is False

    # 游标分页
    first = search(me, "火锅", limit=1)
    assert first["has_more"] is True and len(first["items"]) == 1
    second = search(me, "火锅", limit=1, before_id=int(first["items"][0]["msg_id"]))
    assert [item["text"] for item in second["items"]] == ["晚上吃火锅吗"]

    # 无命中 / 空关键词 / 未认证
    assert search(me, "不存在")["items"] == []
    assert status_of(me, "   ") == 422
    anonymous = urllib.request.Request(HTTP + "/search?q=x")
    try:
        urllib.request.urlopen(anonymous, timeout=3)
        raise AssertionError("未认证应当 401")
    except urllib.error.HTTPError as error:
        assert error.code == 401

    # 撤回后不可见
    target = first["items"][0]["msg_id"]
    await ws.send(
        json.dumps({"v": 1, "type": "revoke", "id": "r-1", "data": {"msg_id": target}})
    )
    await recv(ws, "ack")
    assert all(item["msg_id"] != target for item in search(me, "火锅")["items"])

    # 限流:burst 20,连打 25 次必然出现 429
    codes = [status_of(me, "火锅") for _ in range(25)]
    assert 429 in codes, codes

    await ws.close()


asyncio.run(main())
