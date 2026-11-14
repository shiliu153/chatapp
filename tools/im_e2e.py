"""自建 IM 端到端验收:登录、互发、离线未读、幂等、撤回、互踢。

文件信息:
    文件名称          tools/im_e2e.py
    项目名称          chat_app / 工程脚本
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11
    适用平台          Linux x86_64（本地与 CI）
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.request

import jwt
import websockets

SECRET = os.environ["IM_JWT_SECRET"]
WS = os.environ.get("IM_BASE_WS", "ws://127.0.0.1:19100/im/ws")
HTTP = os.environ.get("IM_BASE_HTTP", "http://127.0.0.1:19101/im/api")
INTERNAL = os.environ.get("IM_INTERNAL_BASE", "http://127.0.0.1:19101")
# 必须与 imserver 的 IM_MEDIA_PREFIX 一致,否则图片帧会被 42201 拒掉
MEDIA_PREFIX = os.environ.get("IM_MEDIA_PREFIX", "http://cdn/media/chat/")


def internal(path: str, payload: dict):
    """调用一次内部 HMAC API(建号 / 配对)。

    参数说明:
        path: 以 ``/internal/`` 开头的路径。
        payload: JSON 请求体。

    返回参数:
        解析后的 JSON 响应。

    使用示例:
        ``internal(path, payload)``

    备注信息:
        签名口径:``HMAC-SHA256(secret, f"{timestamp}\nPOST\n{path}\n{body}")``;内部服务地址取自环境变量 ``IM_INTERNAL_BASE``。
    """
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time()))
    signature = hmac.new(
        os.environ["IM_INTERNAL_SECRET"].encode(),
        f"{timestamp}\nPOST\n{path}\n{body}".encode(),
        hashlib.sha256,
    ).hexdigest()
    request = urllib.request.Request(
        INTERNAL + path,
        data=body.encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-IM-Timestamp": timestamp,
            "X-IM-Signature": signature,
        },
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


def token(uid: int) -> str:
    """签发一个 HS256 的 IM JWT。

    参数说明:
        uid: IM 账号 id(整数);写进 ``sub`` 的 ``u{uid}`` 与 ``uid``。

    返回参数:
        JWT 字符串,有效期 3600 秒。

    使用示例:
        ``token(uid)``

    备注信息:
        密钥取环境变量 ``IM_JWT_SECRET``,必须与 imserver 一致。
    """
    now = int(time.time())
    return jwt.encode(
        {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600, "jti": "e2e"},
        SECRET,
        algorithm="HS256",
    )


def get(path: str, uid: int):
    """带 JWT 调一次 IM 的 HTTP 接口。

    参数说明:
        path: ``/im/api`` 之下的相对路径,如 ``/conversations``。
        uid: 以哪个账号身份调用。

    返回参数:
        解析后的 JSON 响应。

    使用示例:
        ``get(path, uid)``

    备注信息:
        超时 3 秒;非 2xx 直接抛 ``urllib.error.HTTPError``。
    """
    request = urllib.request.Request(
        HTTP + path, headers={"Authorization": f"Bearer {token(uid)}"}
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


async def auth(uid: int):
    """建立 WS 连接并完成 auth 握手。

    参数说明:
        uid: 以哪个账号身份登录。

    返回参数:
        已收到 ``auth_ok`` 的连接对象。

    使用示例:
        ``auth(uid)``

    备注信息:
        只认 ``auth_ok``,其余帧丢弃;单帧等待 3 秒超时。
    """
    ws = await websockets.connect(WS)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid)}}))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == "auth_ok":
            return ws


async def recv(ws, type_):
    """从连接上取第一条指定类型的帧。

    参数说明:
        ws: 已握手的连接。
        type_: 要匹配的帧类型,如 ``message``。

    返回参数:
        匹配到的帧(``dict``)。

    使用示例:
        ``recv(ws, type_)``

    备注信息:
        途中收到的其它类型帧直接丢弃;单帧等待 3 秒超时。
    """
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == type_:
            return message


async def main():
    """跑完整条端到端验收链并断言。

    参数说明:
        无。

    返回参数:
        无返回值;断言失败抛 ``AssertionError``。

    使用示例:
        ``python tools/im_e2e.py``

    备注信息:
        需先起 imserver 并配好 ``IM_JWT_SECRET`` / ``IM_INTERNAL_SECRET`` / ``IM_MEDIA_PREFIX``;账号 id 取时间戳与 PID 拼出的随机段,不污染固定测试数据。
    """
    base = 500000 + (int(time.time() * 1000) + os.getpid()) % 100000
    a_uid, b_uid = base, base + 1
    # H4:收件人必须真实存在,且双方必须有配对关系
    internal("/internal/accounts/ensure", {"uid": a_uid, "nickname": "A"})
    internal("/internal/accounts/ensure", {"uid": b_uid, "nickname": "B"})
    internal("/internal/pair", {"a": a_uid, "b": b_uid, "action": "add"})
    a = await auth(a_uid)
    b = await auth(b_uid)

    msg_ids = []
    for index in range(3):
        await a.send(json.dumps({
            "v": 1,
            "type": "send",
            "id": f"e2e-{index}",
            "data": {"to": f"u{b_uid}", "kind": "text", "text": f"m{index}"},
        }))
        ack = await recv(a, "ack")
        msg_ids.append(ack["data"]["msg_id"])
        pushed = await recv(b, "message")
        assert pushed["data"]["text"] == f"m{index}"

    conversations = get("/conversations", b_uid)["items"]
    assert conversations[0]["unread"] == 3

    # 图片消息:上传后的 URL 必须带 IM_MEDIA_PREFIX,服务端才认
    image_url = MEDIA_PREFIX + "2026/10/e2e.jpg"
    await a.send(json.dumps({
        "v": 1,
        "type": "send",
        "id": "e2e-image",
        "data": {
            "client_msg_id": "e2e-image",
            "to": f"u{b_uid}",
            "kind": "image",
            "image": {"url": image_url,
                      "thumb_url": MEDIA_PREFIX + "2026/10/e2e_thumb.jpg",
                      "width": 1080, "height": 1440, "size": 345678},
        },
    }))
    await recv(a, "ack")
    pushed_image = await recv(b, "message")
    assert pushed_image["data"]["kind"] == "image"
    # 图片 URL 在推送/历史里是**读时签名**的:路径不变,追加 ?e=&s=
    signed_url = pushed_image["data"]["image"]["url"]
    assert signed_url.startswith(image_url + "?e="), signed_url
    assert "&s=" in signed_url
    history = get(f"/messages?peer=u{a_uid}", b_uid)["items"]
    assert any(item["kind"] == "image" for item in history)

    # 伪造外链必须被拒
    await a.send(json.dumps({
        "v": 1,
        "type": "send",
        "id": "e2e-image-bad",
        "data": {
            "client_msg_id": "e2e-image-bad",
            "to": f"u{b_uid}",
            "kind": "image",
            "image": {"url": "http://evil.example/a.jpg",
                      "thumb_url": MEDIA_PREFIX + "2026/10/e2e_thumb.jpg",
                      "width": 1080, "height": 1440, "size": 345678},
        },
    }))
    rejected = await recv(a, "error")
    assert rejected["data"]["code"] == 42201

    await a.send(json.dumps({
        "v": 1,
        "type": "send",
        "id": "e2e-0",
        "data": {"to": f"u{b_uid}", "kind": "text", "text": "m0"},
    }))
    again = await recv(a, "ack")
    assert again["data"]["msg_id"] == msg_ids[0]

    await a.send(json.dumps({
        "v": 1,
        "type": "revoke",
        "id": "e2e-revoke",
        "data": {"msg_id": msg_ids[0]},
    }))
    revoked = await recv(b, "revoked")
    assert revoked["data"]["msg_id"] == msg_ids[0]

    second = await auth(a_uid)
    kicked = await recv(a, "kicked")
    assert kicked["data"]["reason"] == "multi_device"

    await a.close()
    await b.close()
    await second.close()
    print("e2e ok")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as error:  # noqa: BLE001 - 脚本入口统一转退出码
        print(f"e2e failed: {error}", file=sys.stderr)
        raise SystemExit(1)
