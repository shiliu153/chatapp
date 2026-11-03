"""统一压测入口:一个命令跑一个场景,输出一份可对比的 JSON。

为什么要有这一层:2026-11-01 的压测脚本散在 `docs/ops/stress/` 与 `imserver/scripts/`,
各自输出不同格式、没有机器规格、没有时间戳,换台机器就不可比。这里统一成
「场景 + 参数 → 结果 JSON」,`report.py` 负责出表和对比基线。

用法(在服务器上跑,压测器不要和被压服务同机):
    python3 perf/run.py --scenario api_read --conns 100 --dur 30 --out perf/results/api100.json
    python3 perf/run.py --scenario ws_burst --conns 500 --count 1 --out perf/results/ws500.json

场景:
    api_read     GET 一个只读接口(默认 /api/v1/app/config,可 --path 覆盖)
    api_health   GET /api/v1/health(最轻的探活路径,用来测框架开销)
    ws_burst     WS 突发:每个连接发 --count 条,委托 imserver/scripts/bench_ws.py
    ws_steady    WS 稳态:每连接每 --interval 秒发 1 条,持续 --dur 秒

退出码:0 成功;2 参数错误;3 压测本身失败(连接全挂等)。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import socket
import ssl
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCENARIO_PATHS = {
    "api_read": "/api/v1/app/config",
    "api_health": "/api/v1/health",
}

BENCH_WS = Path(__file__).resolve().parent.parent / "imserver" / "scripts" / "bench_ws.py"


async def read_response(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    """读一个完整的 HTTP/1.1 响应。

    Args:
        reader: asyncio 流读取器。

    Returns:
        (状态码, body)。
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
    """一条连接上的闭循环(发请求 → 读完 → 再发),等价于 wrk 的 -c。

    Args:
        args: 命令行参数。
        stats: 共享统计容器。
        stop: 停止信号。
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
    except Exception as exc:  # noqa: BLE001  连接失败要计入错误率而不是崩掉
        stats["codes"][f"connect:{type(exc).__name__}"] += 1
        return
    request = (f"GET {args.path} HTTP/1.1\r\nHost: {args.sni or args.host}\r\n"
               f"X-Forwarded-Proto: https\r\nX-Real-IP: 10.99.0.1\r\n"
               f"User-Agent: chatapp-perf\r\nAccept: */*\r\n"
               f"Connection: keep-alive\r\n\r\n").encode()
    try:
        while not stop.is_set():
            started = time.perf_counter()
            writer.write(request)
            await writer.drain()
            status, _ = await read_response(reader)
            stats["lat"].append(time.perf_counter() - started)
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
    """取分位数(毫秒)。

    Args:
        values: 秒为单位的样本。
        p: 百分位(0-100)。

    Returns:
        毫秒分位数;样本为空时 None。
    """
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1,
                max(0, int(round(p / 100 * len(ordered) + 0.5)) - 1))
    return round(ordered[index] * 1000, 1)


def read_load() -> tuple[float | None, float | None]:
    """读一次 1 分钟负载与已用内存(MB);非 Linux 返回 (None, None)。

    Returns:
        (load1, used_mb)。
    """
    try:
        load1 = float(Path("/proc/loadavg").read_text().split()[0])
    except Exception:  # noqa: BLE001  非 Linux 或容器未挂 /proc
        load1 = None
    used_mb = None
    try:
        meminfo = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            meminfo[key] = int(rest.strip().split()[0])
        used_mb = round((meminfo["MemTotal"] - meminfo["MemAvailable"]) / 1024, 1)
    except Exception:  # noqa: BLE001
        used_mb = None
    return load1, used_mb


async def sample_resources(stats: dict, stop: asyncio.Event) -> None:
    """每秒采一次负载/内存,记录峰值。

    Args:
        stats: 共享统计容器(写 ``load_peak`` / ``mem_peak``)。
        stop: 停止信号。
    """
    while not stop.is_set():
        load1, used_mb = read_load()
        if load1 is not None:
            stats["load_peak"] = max(stats.get("load_peak") or 0, load1)
        if used_mb is not None:
            stats["mem_peak"] = max(stats.get("mem_peak") or 0, used_mb)
        try:
            await asyncio.wait_for(stop.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass


async def run_http(args) -> dict:
    """跑 HTTP 场景。

    Args:
        args: 命令行参数。

    Returns:
        结果字典(``requests`` / ``rps`` / ``error_rate`` / ``lat_ms`` 等)。
    """
    stats = {"n": 0, "lat": [], "codes": Counter()}
    stop = asyncio.Event()
    started = time.perf_counter()
    tasks = [asyncio.create_task(one_conn(args, stats, stop)) for _ in range(args.conns)]
    sampler = asyncio.create_task(sample_resources(stats, stop))
    await asyncio.sleep(args.dur)
    stop.set()
    await asyncio.wait(tasks, timeout=10)
    await asyncio.wait([sampler], timeout=3)
    for task in tasks:
        task.cancel()
    elapsed = time.perf_counter() - started

    codes = dict(stats["codes"])
    failures = sum(count for code, count in codes.items() if not code.startswith("2"))
    return {
        "requests": stats["n"],
        "rps": round(stats["n"] / elapsed, 1) if elapsed else 0,
        "error_rate": round(failures / stats["n"], 4) if stats["n"] else 1.0,
        "codes": codes,
        "load_peak": stats.get("load_peak"),
        "mem_peak": stats.get("mem_peak"),
        "lat_ms": {
            "p50": pct(stats["lat"], 50),
            "p90": pct(stats["lat"], 90),
            "p95": pct(stats["lat"], 95),
            "p99": pct(stats["lat"], 99),
            "max": round(max(stats["lat"]) * 1000, 1) if stats["lat"] else None,
        },
    }


def run_ws(args) -> dict:
    """委托 imserver 自带的 WS 压测脚本并读取其结果。

    Args:
        args: 命令行参数。

    Returns:
        bench_ws 的结果字典。

    Raises:
        RuntimeError: 脚本缺失或退出码非 0。
    """
    if not BENCH_WS.exists():
        raise RuntimeError(f"缺少 {BENCH_WS}")
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        out_path = handle.name
    command = [sys.executable, str(BENCH_WS), "--n", str(args.conns),
               "--out", out_path]
    if args.scenario == "ws_steady":
        command += ["--interval", str(args.interval), "--duration", str(args.dur)]
    else:
        command += ["--count", str(args.count)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if completed.returncode != 0:
        raise RuntimeError("bench_ws 失败:\n" + completed.stderr[-2000:])
    with open(out_path, encoding="utf-8") as handle:
        result = json.load(handle)
    os.unlink(out_path)
    return {
        "connected": result.get("connected"),
        "requests": result.get("ack_total"),
        "rps": round(result["ack_total"] / args.dur, 1) if args.dur else None,
        "error_rate": round(result.get("errors_total", 0) / max(result.get("ack_total", 1), 1), 4),
        "lat_ms": result.get("ack_ms"),
        "codes": {"send_fail": result.get("send_fail"),
                  "connect_fail": result.get("connect_fail"),
                  "auth_fail": result.get("auth_fail")},
    }


def machine_spec() -> dict:
    """采集机器规格,让结果可比较。

    Returns:
        主机名 / CPU 核数 / 平台 / 内存(MB)。
    """
    total_mb = None
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            if line.startswith("MemTotal:"):
                total_mb = round(int(line.split()[1]) / 1024, 1)
    except Exception:  # noqa: BLE001
        total_mb = None
    return {
        "hostname": socket.gethostname(),
        "cpu": os.cpu_count(),
        "platform": platform.platform(),
        "mem_total_mb": total_mb,
    }


def main() -> int:
    """解析参数、跑场景、写结果 JSON。

    Returns:
        进程退出码。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True,
                        choices=["api_read", "api_health", "ws_burst", "ws_steady"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--path", default="")
    parser.add_argument("--conns", type=int, default=100)
    parser.add_argument("--dur", type=int, default=20)
    parser.add_argument("--count", type=int, default=1, help="ws_burst:每连接发送条数")
    parser.add_argument("--interval", type=float, default=1.0, help="ws_steady:发送间隔秒")
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--sni", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    if args.scenario.startswith("api"):
        args.path = args.path or SCENARIO_PATHS[args.scenario]

    started_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    try:
        if args.scenario.startswith("ws"):
            result = run_ws(args)
        else:
            result = asyncio.run(run_http(args))
    except Exception as error:  # noqa: BLE001
        print(f"压测失败: {error}", file=sys.stderr)
        return 3

    payload = {
        "schema": 1,
        "scenario": args.scenario,
        "started_at": started_at,
        "machine": machine_spec(),
        "params": {
            "target": f"{args.host}:{args.port}{args.path}",
            "conns": args.conns,
            "duration_s": args.dur,
            "count": args.count if args.scenario == "ws_burst" else None,
            "interval": args.interval if args.scenario == "ws_steady" else None,
            "tls": args.tls,
        },
        "result": result,
        "resources": {
            "load1_peak": result.pop("load_peak", None),
            "mem_used_mb_peak": result.pop("mem_peak", None),
        },
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
