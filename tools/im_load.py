"""自建 IM 压测:默认 500 连接、20 msg/s,统计 ack 延迟。"""

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
    now = int(time.time())
    return jwt.encode(
        {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600, "jti": "load"},
        SECRET,
        algorithm="HS256",
    )


async def connect(uid: int):
    ws = await websockets.connect(WS, max_size=2**20)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid)}}))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 5))
        if message["type"] == "auth_ok":
            return ws


async def main():
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
