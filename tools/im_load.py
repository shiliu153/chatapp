"""自建 IM 压测:默认 500 连接、20 msg/s,统计 ack 延迟。

文件信息:
    文件名称          tools/im_load.py
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
import json
import os
import statistics
import time

import jwt
import websockets

SECRET = os.environ["IM_JWT_SECRET"]
WS = os.environ.get("IM_BASE_WS", "ws://127.0.0.1:19100/im/ws")
CONNECTIONS = int(os.environ.get("IM_LOAD_CONNS", "500"))
DURATION = float(os.environ.get("IM_LOAD_SECONDS", "10"))
RATE = float(os.environ.get("IM_LOAD_RATE", "20"))


def token(uid: int) -> str:
    """签发一个 HS256 的 IM JWT。

    参数说明:
        uid: IM 账号 id(整数)。

    返回参数:
        JWT 字符串,有效期 3600 秒,``jti`` 固定为 ``load``。

    使用示例:
        ``token(uid)``

    备注信息:
        密钥取环境变量 ``IM_JWT_SECRET``,必须与 imserver 一致。
    """
    now = int(time.time())
    return jwt.encode(
        {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600, "jti": "load"},
        SECRET,
        algorithm="HS256",
    )


async def connect(uid: int):
    """建立 WS 连接并完成 auth 握手。

    参数说明:
        uid: 以哪个账号身份登录。

    返回参数:
        已收到 ``auth_ok`` 的连接对象。

    使用示例:
        ``connect(uid)``

    备注信息:
        单帧上限 1 MiB,握手帧等待 5 秒超时。
    """
    ws = await websockets.connect(WS, max_size=2**20)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid)}}))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 5))
        if message["type"] == "auth_ok":
            return ws


async def main():
    """起全部连接并发压测,末尾打印延迟分位。

    参数说明:
        无。

    返回参数:
        无返回值;``IM_LOAD_ASSERT=1`` 且 p99 ≥ 200ms 时抛 ``SystemExit(1)``。

    使用示例:
        ``python tools/im_load.py``

    备注信息:
        规模由 ``IM_LOAD_CONNS`` / ``IM_LOAD_SECONDS`` / ``IM_LOAD_RATE`` 控制(默认 500 连接、10 秒、20 msg/s);账号 id 从固定 ``700000`` 起,压测前需先建号并配对。
    """
    base = 700000
    clients = await asyncio.gather(*[connect(base + i) for i in range(CONNECTIONS)])
    latencies: list[float] = []
    errors = 0
    lock = asyncio.Lock()

    async def send_one(index: int):
        nonlocal errors
        client = clients[index]
        target = base + (index + 1) % CONNECTIONS
        started = time.perf_counter()
        await client.send(json.dumps({
            "v": 1,
            "type": "send",
            "id": f"load-{index}-{started}",
            "data": {"to": f"u{target}", "kind": "text", "text": "load"},
        }))
        while True:
            message = json.loads(await asyncio.wait_for(client.recv(), 5))
            if message["type"] == "ack":
                elapsed = (time.perf_counter() - started) * 1000
                async with lock:
                    latencies.append(elapsed)
                return
            if message["type"] == "error":
                async with lock:
                    errors += 1
                return

    async def sender(index: int):
        interval = CONNECTIONS / RATE
        end = time.perf_counter() + DURATION
        while time.perf_counter() < end:
            try:
                await send_one(index)
            except Exception:
                async with lock:
                    errors += 1
            await asyncio.sleep(interval)

    await asyncio.gather(*[sender(i) for i in range(CONNECTIONS)])
    for client in clients:
        await client.close()

    latencies.sort()
    p50 = statistics.median(latencies) if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
    p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0
    print(json.dumps({
        "connections": CONNECTIONS,
        "sent": len(latencies),
        "errors": errors,
        "p50_ms": round(p50, 2),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
    }))
    if os.environ.get("IM_LOAD_ASSERT") == "1" and p99 >= 200:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
