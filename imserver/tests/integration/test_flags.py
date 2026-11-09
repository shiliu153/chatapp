"""`POST /im/api/conversations/flags` 与会话列表置顶 / 免打扰的 HTTP 集成测试。

覆盖批次 N(设计见 `docs/superpowers/specs/2026-11-09-batch-m-q-design.md` §4):
    1. 鉴权与 `/im/api/*` 同口径:无 token → `401` + `40101`;
    2. `peer` 格式错 / `pinned` 不是布尔 → `400` + `42201`;
    3. 未配对或从没聊过(会话不存在)→ `404` + `40401`;
    4. 置顶后 `GET /im/api/conversations` 顺序变化,`pinned` / `muted` 字段回显;
    5. 幂等:重复设置同值仍 `200` 且状态不变;
    6. 非置顶会话顺序不受影响,置顶组内按置顶时间倒序;
    7. 单方语义:对端看到的仍是 `pinned=false`。
"""

import json
import os
import time
import urllib.error
import urllib.request

import jwt

from _support import call, ensure, pair

SECRET = os.environ["IM_JWT_SECRET"]
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
        path: 相对 `http_url` 的路径,如 `/conversations`。
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


def set_flags(uid, peer, **switches):
    """调用置顶 / 免打扰接口。

    Args:
        uid: 账号 id。
        peer: 对端,可以是数字(拼成 `u<n>`)或原样字符串(用来验证格式错)。
        **switches: `pinned` / `muted`,缺省表示不改。

    Returns:
        `(状态码, JSON)`。
    """
    payload = {"peer": peer if isinstance(peer, str) else f"u{peer}"}
    payload.update(switches)
    return request(uid, "/conversations/flags", payload, "POST")


def conversations(uid: int):
    """取会话列表(客户端刷新置顶 / 免打扰的入口)。

    Args:
        uid: 账号 id。

    Returns:
        `items` 列表,顺序就是客户端看到的顺序。
    """
    status, body = request(uid, "/conversations")
    assert status == 200, body
    return body["items"]


def peer_order(uid: int):
    """只取会话列表的对端顺序,便于断言排序。

    Args:
        uid: 账号 id。

    Returns:
        `u<n>` 字符串列表,靠前 = 列表里更靠上。
    """
    return [item["peer"]["id"] for item in conversations(uid)]


def send_text(sender: int, receiver: int, text: str) -> None:
    """通过内部 HMAC 接口代发一条文本(只为造出会话,避免依赖 WS)。

    Args:
        sender: 发送方账号 id。
        receiver: 接收方账号 id。
        text: 文本内容。
    """
    result = call("/internal/send", {"from": sender, "to": receiver, "kind": "text", "text": text})
    assert result.get("ok") is True, result


def main():
    """跑完整个置顶 / 免打扰场景。"""
    base = 500000 + (int(time.time() * 1000) + os.getpid()) % 90000
    me, older, newer = base, base + 1, base + 2
    for uid in (me, older, newer):
        ensure(uid)
    # 已配对但**没聊过**:这种状态没有会话,flags 必须回 404
    pair(me, older)
    pair(me, newer)

    # 1. 无令牌 → 401 + 40101(与 /im/api/conversations|messages|search 同口径)
    status, body = request(None, "/conversations/flags", {"peer": f"u{older}", "pinned": True},
                           "POST")
    assert status == 401 and body["code"] == 40101, (status, body)

    # 2. peer 格式错 → 400 + 42201
    status, body = set_flags(me, "uoops", pinned=True)
    assert status == 400 and body["code"] == 42201, (status, body)
    # 2b. 开关不是布尔 → 400 + 42201(缺省才是「不改」,类型错不能当 false 处理)
    status, body = set_flags(me, older, pinned="yes")
    assert status == 400 and body["code"] == 42201, (status, body)

    # 3. 会话不存在(未配对 / 从没聊过)→ 404 + 40401
    status, body = set_flags(me, older, pinned=True)
    assert status == 404 and body["code"] == 40401, (status, body)

    # 造两个会话:先与 older 聊、再与 newer 聊 → 不置顶时最近消息优先 [newer, older]
    send_text(me, older, "早")
    time.sleep(0.02)
    send_text(me, newer, "晚")
    assert peer_order(me) == [f"u{newer}", f"u{older}"], peer_order(me)
    # 新字段对存量会话有确定的默认值(不是缺键)
    first = conversations(me)[0]
    assert first["pinned"] is False and first["muted"] is False, first

    # 4. 置顶 older(更早聊的)→ 进置顶组排到最前,两个字段都回显
    status, body = set_flags(me, older, pinned=True, muted=True)
    assert status == 200 and body == {"pinned": True, "muted": True}, (status, body)
    items = conversations(me)
    assert [item["peer"]["id"] for item in items] == [f"u{older}", f"u{newer}"], items
    assert items[0]["pinned"] is True and items[0]["muted"] is True, items[0]
    assert items[1]["pinned"] is False and items[1]["muted"] is False, items[1]

    # 5. 幂等:重复设置同值仍 200,顺序与状态都不变
    status, body = set_flags(me, older, pinned=True)
    assert status == 200 and body == {"pinned": True, "muted": True}, (status, body)
    assert peer_order(me) == [f"u{older}", f"u{newer}"], peer_order(me)

    # 6. 只改 muted:置顶不受影响(缺省 ≠ false)
    status, body = set_flags(me, older, muted=False)
    assert status == 200 and body == {"pinned": True, "muted": False}, (status, body)

    # 7. 再置顶 newer(置顶时间更晚)→ 置顶组内按置顶时间倒序 → [newer, older]
    time.sleep(0.02)
    status, body = set_flags(me, newer, pinned=True)
    assert status == 200 and body["pinned"] is True, (status, body)
    assert peer_order(me) == [f"u{newer}", f"u{older}"], peer_order(me)

    # 8. 取消 newer 的置顶 → older 仍在置顶组最前,newer 回落到最近消息组
    status, body = set_flags(me, newer, pinned=False)
    assert status == 200 and body == {"pinned": False, "muted": False}, (status, body)
    assert peer_order(me) == [f"u{older}", f"u{newer}"], peer_order(me)

    # 9. 置顶是**单方**的:对端看到的仍是默认值
    peer_items = conversations(older)
    assert peer_items, peer_items
    assert peer_items[0]["pinned"] is False and peer_items[0]["muted"] is False, peer_items[0]

    print("test_flags ok: 401 / 42201 / 40401 / 置顶优先 / 组内按置顶时间 / 幂等 / 单方")


main()
