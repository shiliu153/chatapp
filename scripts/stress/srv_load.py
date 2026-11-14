"""服务器内网侧 HTTP 压测器(纯标准库 asyncio,不依赖第三方包)。

为什么在服务器上跑:公网压测会被客户端出口带宽/单机 Python 吞吐卡住,
测到的是「我家宽带」而不是「服务器」。放到 127.0.0.1 才能压出真实容量。

用法:
    python3 srvload.py --host 127.0.0.1 --port 8000 --path /api/v1/app/config --conns 200 --dur 20
    python3 srvload.py --host 127.0.0.1 --port 443 --tls --sni chat.shiliu153.cn --path /api/v1/app/config --conns 500 --dur 20

每个连接是「发一个请求 → 读完响应 → 再发下一个」的闭循环,等价于 wrk 的 -c。

文件信息:
    文件名称          scripts/stress/srv_load.py
    项目名称          chat_app / 工程脚本
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11
    适用平台          Linux x86_64（本地与 CI）
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from __future__ import annotations

import argparse
import asyncio
import json
import ssl
import time
from collections import Counter


async def read_response(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    """读一个完整的 HTTP/1.1 响应,返回 (状态码, body)。

    参数说明:
        reader: ``asyncio.StreamReader`` 读端。

    返回参数:
        ``tuple[int, bytes]``。

    使用示例:
        ``read_response(reader)``

    备注信息:
        无特殊约束。
    """
    head = await reader.readuntil(b"\r\n\r\n")
    lines = head.decode("latin-1").split("\r\n")
    status = int(lines[0].split(" ")[1])
    length = 0
    chunked = False
    for line in lines[1:]:
        low = line.lower()
        if low.startswith("content-length:"):
            length = int(line.split(":", 1)[1].strip())
        elif low.startswith("transfer-encoding:") and "chunked" in low:
            chunked = True
    if chunked:
        body = b""
        while True:
            size_line = await reader.readuntil(b"\r\n")
            size = int(size_line.strip().split(b";")[0], 16)
            if size == 0:
                await reader.readuntil(b"\r\n")
                break
            body += await reader.readexactly(size)
            await reader.readexactly(2)
        return status, body
    if length:
        body = await reader.readexactly(length)
    else:
        body = b""
    return status, body


async def one_conn(args, stats: dict, stop: asyncio.Event) -> None:
    """一条连接上的闭循环。

    参数说明:
        args: 命令行参数(argparse 命名空间)。
        stats: 汇总容器(``dict``),含 ``lat`` / ``codes``。
        stop: ``asyncio.Event``,置位后各协程退出循环。

    返回参数:
        无返回值。

    使用示例:
        ``one_conn(args, stats, stop)``

    备注信息:
        无特殊约束。
    """
    ctx = None
    if args.tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    try:
        reader, writer = await asyncio.open_connection(
            args.host, args.port, ssl=ctx,
            server_hostname=args.sni if args.tls else None)
    except Exception as exc:  # noqa: BLE001
        stats["codes"][f"connect:{type(exc).__name__}"] += 1
        return
    req = (f"GET {args.path} HTTP/1.1\r\nHost: {args.sni or args.host}\r\n"
           f"X-Forwarded-Proto: https\r\nX-Real-IP: 10.99.0.1\r\n"
           f"User-Agent: srvload\r\nAccept: */*\r\nConnection: keep-alive\r\n\r\n").encode()
    try:
        while not stop.is_set():
            t0 = time.perf_counter()
            writer.write(req)
            await writer.drain()
            status, _ = await read_response(reader)
            stats["lat"].append(time.perf_counter() - t0)
            stats["codes"][str(status)] += 1
            stats["n"] += 1
    except Exception as exc:  # noqa: BLE001
        stats["codes"][f"io:{type(exc).__name__}"] += 1
    finally:
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass


def pct(values: list[float], p: float) -> float | None:
    """分位(毫秒)。

    参数说明:
        values: 延迟样本列表,单位秒。
        p: 分位点,取值 0–100。

    返回参数:
        ``float | None``。

    使用示例:
        ``pct(values, p)``

    备注信息:
        无特殊约束。
    """
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(p / 100 * len(ordered) + 0.5)) - 1))
    return round(ordered[idx] * 1000, 1)


async def main() -> None:
    """入口。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``main()``

    备注信息:
        无特殊约束。
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--path", default="/api/v1/app/config")
    ap.add_argument("--conns", type=int, default=100)
    ap.add_argument("--dur", type=int, default=20)
    ap.add_argument("--tls", action="store_true")
    ap.add_argument("--sni", default="chat.shiliu153.cn")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    stats = {"n": 0, "lat": [], "codes": Counter()}
    stop = asyncio.Event()
    t0 = time.perf_counter()
    tasks = [asyncio.create_task(one_conn(args, stats, stop)) for _ in range(args.conns)]
    await asyncio.sleep(args.dur)
    stop.set()
    await asyncio.wait(tasks, timeout=10)
    elapsed = time.perf_counter() - t0
    for t in tasks:
        t.cancel()

    out = {
        "target": f"{args.host}:{args.port}{args.path}",
        "tls": args.tls,
        "conns": args.conns,
        "duration_s": round(elapsed, 2),
        "requests": stats["n"],
        "rps": round(stats["n"] / elapsed, 1) if elapsed else 0,
        "codes": dict(stats["codes"]),
        "lat_ms": {"p50": pct(stats["lat"], 50), "p90": pct(stats["lat"], 90),
                   "p95": pct(stats["lat"], 95), "p99": pct(stats["lat"], 99),
                   "max": round(max(stats["lat"]) * 1000, 1) if stats["lat"] else None},
    }
    print(json.dumps(out, ensure_ascii=False, indent=2), flush=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
