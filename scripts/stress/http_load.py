"""HTTP 压测器:固定并发循环打一个 URL,统计 RPS / 延迟分位 / 状态码分布。

用法:
    python stress_http.py --url https://host/api/v1/app/config --conc 200 --dur 30

设计要点:
- 每个 worker 串行发请求(闭循环),并发数 = worker 数,等价于 wrk 的 -c;
- 复用 keep-alive 连接,避免把 TLS 握手算进延迟;
- 任何异常都计数不抛出,压测器本身不能先崩;
- 结束时输出 JSON,便于和服务器端采样对齐。

文件信息:
    文件名称          scripts/stress/http_load.py
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
import time
from collections import Counter

import httpx


def pct(values: list[float], p: float) -> float | None:
    """返回列表的 p 分位(毫秒)。

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


async def worker(client: httpx.AsyncClient, args, stop: asyncio.Event, stats: dict) -> None:
    """一个并发循环:请求直到 stop 被置位。

    参数说明:
        client: ``httpx.AsyncClient`` 实例。
        args: 命令行参数(argparse 命名空间,已归一)。
        stop: ``asyncio.Event``,置位后各协程退出循环。
        stats: 汇总容器(``dict``),含 ``lat`` / ``codes`` / ``server_err``。

    返回参数:
        无返回值。

    使用示例:
        ``worker(client, args, stop, stats)``

    备注信息:
        无特殊约束。
    """
    while not stop.is_set():
        t0 = time.perf_counter()
        try:
            resp = await client.request(args.method, args.url)
            stats["lat"].append(time.perf_counter() - t0)
            stats["codes"][str(resp.status_code)] += 1
            if resp.status_code >= 500:
                stats["server_err"] += 1
        except Exception as exc:  # noqa: BLE001
            stats["lat"].append(time.perf_counter() - t0)
            stats["codes"][type(exc).__name__] += 1
            stats["errors"] += 1
        stats["n"] += 1


async def main() -> None:
    """入口:跑 dur 秒,打印汇总。

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
    ap.add_argument("--url", required=True)
    ap.add_argument("--method", default="GET")
    ap.add_argument("--conc", type=int, default=50)
    ap.add_argument("--dur", type=int, default=20)
    ap.add_argument("--timeout", type=float, default=15.0)
    ap.add_argument("--header", action="append", default=[])
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    headers = {}
    for raw in args.header:
        k, _, v = raw.partition(":")
        headers[k.strip()] = v.strip()

    limits = httpx.Limits(max_connections=args.conc + 10,
                          max_keepalive_connections=args.conc + 10)
    stats = {"n": 0, "lat": [], "codes": Counter(), "errors": 0, "server_err": 0}
    stop = asyncio.Event()

    async with httpx.AsyncClient(limits=limits, timeout=args.timeout,
                                 verify=False, headers=headers,
                                 follow_redirects=False) as client:
        t_start = time.perf_counter()
        tasks = [asyncio.create_task(worker(client, args, stop, stats))
                 for _ in range(args.conc)]
        await asyncio.sleep(args.dur)
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        elapsed = time.perf_counter() - t_start

    out = {
        "url": args.url,
        "conc": args.conc,
        "duration_s": round(elapsed, 2),
        "requests": stats["n"],
        "rps": round(stats["n"] / elapsed, 1) if elapsed else 0,
        "errors": stats["errors"],
        "server_5xx": stats["server_err"],
        "codes": dict(stats["codes"]),
        "lat_ms": {
            "p50": pct(stats["lat"], 50),
            "p90": pct(stats["lat"], 90),
            "p95": pct(stats["lat"], 95),
            "p99": pct(stats["lat"], 99),
            "max": round(max(stats["lat"]) * 1000, 1) if stats["lat"] else None,
            "avg": round(sum(stats["lat"]) / len(stats["lat"]) * 1000, 1) if stats["lat"] else None,
        },
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    asyncio.run(main())
