"""多端在线的集成测试:同账号两端并存、扇出、同类互顶、按端版本、按端踢人。

覆盖批次 K(K-2)的验收:
    1. 同一账号 `app` 与 `web` 两条连接**并存**,一条发消息另一条也能收到下行;
    2. 同端第二条连接会把第一条踢掉(`kicked` reason=`multi_device`);
    3. 按端版本:把 `web` 的版本 +1 后,`web` 旧 token 连不上(WS 与 `/im/api/*` 同口径),
       `app` 不受影响;从未登录过的端没有会话行,带 `sv` 的 token 一律拒;
    4. `/internal/kick` 带 `client_type` 时只踢该端,另一端的会话照常收发;
    5. Step 0 核实结论:撤回经 `send_to` 扇出,自己另一端也收到 `revoked`;
    6. Step 0 核实结论:`im:online:{uid}` 在「一端断开、另一端还在」时不能被抹掉。
"""

import asyncio
import json
import os
import time
import urllib.error
import urllib.request

import jwt
import redis
import websockets

from _support import call, ensure, pair

SECRET = os.environ["IM_JWT_SECRET"]
WS = os.environ.get("IM_TEST_WS", "ws://127.0.0.1:19100/im/ws")
HTTP = os.environ.get("IM_TEST_HTTP", "http://127.0.0.1:19101/im/api")


def token(uid: int, client_type: str, sv: int = 0) -> str:
    """签一个带端类型的测试 JWT(与 Django 侧 `mint_im_token` 同口径)。

    Args:
        uid: 账号 id。
        client_type: `app` 或 `web`。
        sv: 会话版本;0 表示不写这个 claim(旧 token 形态)。

    Returns:
        HS256 JWT 字符串。
    """
    now = int(time.time())
    payload = {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600,
               "jti": "test", "ct": client_type}
    if sv:
        payload["sv"] = sv
    return jwt.encode(payload, SECRET, algorithm="HS256")


async def connect(uid: int, client_type: str, sv: int = 0):
    """连 WS 并完成握手。

    Args:
        uid: 账号 id。
        client_type: `app` 或 `web`。
        sv: token 里的会话版本。

    Returns:
        握手成功返回 ws 连接;被拒返回服务端的 `error` 帧(dict)。
    """
    ws = await websockets.connect(WS)
    await ws.send(json.dumps({"v": 1, "type": "auth",
                              "data": {"token": token(uid, client_type, sv)}}))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == "auth_ok":
            return ws
        if message["type"] == "error":
            await ws.close()
            return message


async def recv_until(ws, type_, timeout=3):
    """丢弃无关帧,直到拿到指定类型。"""
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if message["type"] == type_:
            return message


async def send_text(ws, peer_uid: int, text: str, client_id: str):
    """发一条文本并等 ack,返回 ack 的 data(里面有 msg_id / seq)。"""
    await ws.send(json.dumps({"v": 1, "type": "send", "id": client_id,
                              "data": {"to": f"u{peer_uid}", "kind": "text", "text": text}}))
    ack = await recv_until(ws, "ack")
    assert ack["id"] == client_id, ack
    return ack["data"]


def http_get(path: str, uid: int, client_type: str, sv: int = 0):
    """带 Bearer token 调 `/im/api/*`;4xx 也按 (状态码, body) 返回,不抛异常。"""
    request = urllib.request.Request(
        HTTP + path, method="GET",
        headers={"Authorization": f"Bearer {token(uid, client_type, sv)}"})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


async def case_coexist_and_fan_out(base: int) -> None:
    """1. 两端并存:对端发给我的消息,App 与网页都收到。"""
    me, peer_uid = base, base + 1
    ensure(me)
    ensure(peer_uid)
    pair(me, peer_uid)
    app_ws = await connect(me, "app")
    web_ws = await connect(me, "web")
    assert not isinstance(app_ws, dict), app_ws
    assert not isinstance(web_ws, dict), web_ws
    sender = await connect(peer_uid, "app")
    await send_text(sender, me, "hi", "peer-1")
    for ws in (app_ws, web_ws):
        frame = await recv_until(ws, "message")
        assert frame["data"]["text"] == "hi", frame
    for ws in (app_ws, web_ws, sender):
        await ws.close()


async def case_same_client_kicks(base: int) -> None:
    """2. 同端第二条连接踢掉第一条(reason multi_device),另一端不受影响。"""
    me = base + 2
    ensure(me)
    web_ws = await connect(me, "web")
    assert not isinstance(web_ws, dict), web_ws
    first = await connect(me, "app")
    assert not isinstance(first, dict), first
    second = await connect(me, "app")
    assert not isinstance(second, dict), second
    frame = await recv_until(first, "kicked")
    assert frame["data"]["reason"] == "multi_device", frame
    # 网页端还活着:发一条 ping 必须拿到 pong(而不是 kicked)
    await web_ws.send(json.dumps({"v": 1, "type": "ping"}))
    await recv_until(web_ws, "pong")
    await web_ws.close()
    await second.close()


async def case_per_client_version(base: int) -> None:
    """3. 按端版本:web 升版后 web 旧 token 全入口被拒,app 不受影响。"""
    me = base + 3
    ensure(me)
    call("/internal/session_version", {"uid": me, "client_type": "app", "version": 7})
    call("/internal/session_version", {"uid": me, "client_type": "web", "version": 7})
    app_ws = await connect(me, "app", 7)
    web_ws = await connect(me, "web", 7)
    assert not isinstance(app_ws, dict), app_ws
    assert not isinstance(web_ws, dict), web_ws
    await web_ws.close()

    # 网页端重新登录:版本 7 → 8
    call("/internal/session_version", {"uid": me, "client_type": "web", "version": 8})
    stale = await connect(me, "web", 7)
    assert isinstance(stale, dict) and stale["data"]["code"] == 40101, stale
    status, body = http_get("/conversations", me, "web", 7)
    assert status == 401 and body["code"] == 40101, (status, body)
    fresh = await connect(me, "web", 8)
    assert not isinstance(fresh, dict), fresh
    status, _ = http_get("/conversations", me, "web", 8)
    assert status == 200, status

    # app 那一行没动过:版本 7 的 app token 仍可用(WS 与 HTTP 都一样)
    status, _ = http_get("/conversations", me, "app", 7)
    assert status == 200, status
    app_again = await connect(me, "app", 7)
    assert not isinstance(app_again, dict), app_again

    # 从未登录过的端没有会话行:带 sv 的 token 一律拒(避免凭空放行)
    never = base + 4
    ensure(never)
    absent = await connect(never, "web", 3)
    assert isinstance(absent, dict) and absent["data"]["code"] == 40101, absent

    for ws in (app_ws, fresh, app_again):
        await ws.close()


async def case_kick_single_client(base: int) -> None:
    """4. `/internal/kick` 带 client_type 只踢该端,另一端照常收发。"""
    me, peer_uid = base + 5, base + 6
    ensure(me)
    ensure(peer_uid)
    pair(me, peer_uid)
    app_ws = await connect(me, "app")
    web_ws = await connect(me, "web")
    assert not isinstance(app_ws, dict), app_ws
    assert not isinstance(web_ws, dict), web_ws

    call("/internal/kick", {"uid": me, "client_type": "web"})
    frame = await recv_until(web_ws, "kicked")
    # 带 client_type 的踢人只来自「同端换设备登录」,原因按 multi_device 下发
    assert frame["data"]["reason"] == "multi_device", frame

    # App 仍在:对端发消息照样能收到
    sender = await connect(peer_uid, "app")
    await send_text(sender, me, "still here", "peer-2")
    pushed = await recv_until(app_ws, "message")
    assert pushed["data"]["text"] == "still here", pushed
    await app_ws.close()
    await sender.close()


async def case_revoke_fans_out(base: int) -> None:
    """5. 撤回扇出:撤回者自己的另一端也收到 `revoked`(Step 0 核实结论)。"""
    me, peer_uid = base + 7, base + 8
    ensure(me)
    ensure(peer_uid)
    pair(me, peer_uid)
    app_ws = await connect(me, "app")
    web_ws = await connect(me, "web")
    peer_ws = await connect(peer_uid, "app")
    ack = await send_text(app_ws, peer_uid, "撤回我", "me-1")
    await recv_until(peer_ws, "message")

    await app_ws.send(json.dumps({"v": 1, "type": "revoke", "id": "rv-1",
                                  "data": {"msg_id": ack["msg_id"]}}))
    await recv_until(app_ws, "ack")
    # 帧里的 peer 是**相对收帧者**的对端:自己的另一端看到的是对端,对端看到的是我
    for ws, expected_peer in ((web_ws, peer_uid), (peer_ws, me)):
        frame = await recv_until(ws, "revoked")
        assert frame["data"]["msg_id"] == ack["msg_id"], frame
        assert frame["data"]["peer"] == f"u{expected_peer}", frame
    for ws in (app_ws, web_ws, peer_ws):
        await ws.close()


async def case_online_key_survives_one_client(base: int) -> None:
    """6. `im:online:{uid}`:一端断开、另一端还在 → 仍算在线;最后一个断开才抹掉。"""
    me = base + 9
    ensure(me)
    store = redis.Redis.from_url(os.environ["IM_REDIS_URL"])
    key = f"im:online:{me}"
    app_ws = await connect(me, "app")
    web_ws = await connect(me, "web")
    assert not isinstance(app_ws, dict), app_ws
    assert not isinstance(web_ws, dict), web_ws
    assert store.exists(key) == 1

    await app_ws.close()
    await asyncio.sleep(0.5)
    assert store.exists(key) == 1, "App 断开后网页还在线,在线键不该被抹掉"

    await web_ws.close()
    for _ in range(30):
        if store.exists(key) == 0:
            break
        await asyncio.sleep(0.1)
    assert store.exists(key) == 0, "最后一个连接也断了,在线键应当被删掉"


async def main() -> None:
    """依次跑六条用例(账号 id 按时间 + pid 取号,避免与其它测试撞号)。"""
    base = 400000 + (int(time.time() * 1000) + os.getpid()) % 90000
    await case_coexist_and_fan_out(base)
    await case_same_client_kicks(base)
    await case_per_client_version(base)
    await case_kick_single_client(base)
    await case_revoke_fans_out(base)
    await case_online_key_survives_one_client(base)
    print("test_multi_device ok: 两端并存 / 同类互顶 / 按端版本 / 按端踢 / 撤回扇出 / 在线键")


asyncio.run(main())
