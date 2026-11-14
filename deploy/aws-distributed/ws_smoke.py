"""P1 冒烟:验证 nginx -> imserver 的 WebSocket 鉴权链路。

只做一件事:走 nginx 的 /im/ws 建连,发 auth 帧,断言收到 auth_ok。
不改任何数据,可反复执行。
"""

import asyncio
import json
import os
import urllib.error
import urllib.request

BASE = os.environ.get("BASE", "http://127.0.0.1:8080")
PHONE = os.environ.get("PHONE", "13800138000")
CODE = "123456"


def post(path, payload, token=None):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        print("POST %s -> HTTP %s body=%r" % (path, exc.code, exc.read()[:400]))
        raise


async def main():
    post("/api/v1/auth/sms/send", {"phone": PHONE})
    login = post("/api/v1/auth/sms/verify", {"phone": PHONE, "code": CODE})
    sig = post("/api/v1/im/user_sig", {}, login["access"])
    token = sig["token"]
    print("im_user_id=%s ws_url=%s" % (sig.get("im_user_id"), sig.get("ws_url")))

    ws_uri = BASE.replace("http://", "ws://") + "/im/ws"
    async with websockets.connect(ws_uri, open_timeout=10) as ws:
        await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token}}))
        first = await asyncio.wait_for(ws.recv(), timeout=10)
        print("RECV:", first)
        kind = json.loads(first).get("type")
        print("IM_WS_AUTH_OK" if kind == "auth_ok" else "IM_WS_AUTH_FAIL:%s" % kind)


if __name__ == "__main__":
    import websockets
    asyncio.run(main())
