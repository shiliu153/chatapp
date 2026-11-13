"""imserver 多实例投递的实验台(A/B 对照)。

用途:为「imserver 多实例(Redis pub/sub + owner 路由)」这张工单提供
**可复现的 before/after 判据**。当前代码(会话表在进程内)应当表现为:

    对照组  both_on_a    : 两个客户端连同一个 imserver  -> 消息送达
    实验组  split_a_b    : 两个客户端分别连两个 imserver -> **消息丢失**

改造完成后,两组都应送达 —— 那时把本脚本的断言反过来即可。

环境变量:
    BASE      Django 入口,默认 http://nginx:8080
    NODE_A    节点 A 的 WS 地址,默认 ws://imlab-a:9100/im/ws
    NODE_B    节点 B 的 WS 地址,默认 ws://imlab-b:9100/im/ws
    PHONE_1   发送方手机号(名单内),默认 13800138000
    PHONE_2   接收方手机号(名单内),默认 13800138001

前置:chatapp_im.im_pair 里必须已有 (1,2) 这一对,否则发送会被 40302 拒绝。
"""

import asyncio
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("BASE", "http://nginx:8080")
NODE_A = os.environ.get("NODE_A", "ws://imlab-a:9100/im/ws")
NODE_B = os.environ.get("NODE_B", "ws://imlab-b:9100/im/ws")
PHONE_1 = os.environ.get("PHONE_1", "13800138000")
PHONE_2 = os.environ.get("PHONE_2", "13800138001")
CODE = "123456"
WAIT_SECONDS = 8


def post(path, payload, token=None):
    """发一个 JSON POST,返回解析后的 body。"""
    data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print("POST %s -> HTTP %s body=%r" % (path, exc.code, exc.read()[:300]))
        raise


def im_token(phone):
    """走「发码 -> 登录 -> 取 IM 凭证」拿到该账号的 IM token 与 im_user_id。"""
    post("/api/v1/auth/sms/send", {"phone": phone})
    login = post("/api/v1/auth/sms/verify", {"phone": phone, "code": CODE})
    sig = post("/api/v1/im/user_sig", {}, login["access"])
    return sig["token"], sig["im_user_id"]


async def open_authed(uri, token):
    """建立 WS 连接并完成 auth 握手。"""
    ws = await websockets.connect(uri, open_timeout=10)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token}}))
    first = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
    if first.get("type") != "auth_ok":
        raise RuntimeError("auth failed on %s: %s" % (uri, first))
    return ws


async def scenario(name, sender_uri, receiver_uri, tok1, tok2, to_id):
    """让发送方在 sender_uri 上发一条,看接收方在 receiver_uri 上能否收到。"""
    sender = await open_authed(sender_uri, tok1)
    receiver = await open_authed(receiver_uri, tok2)
    try:
        await sender.send(json.dumps({
            "v": 1, "type": "send", "id": "probe-1",
            "data": {"client_msg_id": "probe-%s" % name, "to": to_id,
                     "kind": "text", "text": "cross-node probe %s" % name},
        }))
        ack = None
        try:
            raw = await asyncio.wait_for(sender.recv(), timeout=WAIT_SECONDS)
            ack = json.loads(raw).get("type")
        except asyncio.TimeoutError:
            ack = "timeout"

        delivered = False
        try:
            while True:
                raw = await asyncio.wait_for(receiver.recv(), timeout=WAIT_SECONDS)
                frame = json.loads(raw)
                if frame.get("type") == "message":
                    delivered = True
                    break
        except asyncio.TimeoutError:
            delivered = False

        print("%-12s ack=%-8s delivered=%s" % (name, ack, delivered))
        return delivered
    finally:
        await sender.close()
        await receiver.close()


async def main():
    tok1, id1 = im_token(PHONE_1)
    tok2, id2 = im_token(PHONE_2)
    print("sender=%s receiver=%s" % (id1, id2))

    same = await scenario("both_on_a", NODE_A, NODE_A, tok1, tok2, id2)
    split = await scenario("split_a_b", NODE_A, NODE_B, tok1, tok2, id2)

    print("---")
    print("control_same_node_delivered=%s" % same)
    print("cross_node_delivered=%s" % split)
    final = "BASELINE_EXPECTED" if (same and not split) else "UNEXPECTED"
    print("verdict=%s" % final)


if __name__ == "__main__":
    import websockets
    asyncio.run(main())
