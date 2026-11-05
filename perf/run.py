"""统一压测入口:一个命令跑一个场景,输出一份可对比的 JSON。

为什么要有这一层:2026-11-01 的压测脚本散在 `docs/ops/stress/` 与 `imserver/scripts/`,
各自输出不同格式、没有机器规格、没有时间戳,换台机器就不可比。这里统一成
「场景 + 参数 → 结果 JSON」,`report.py` 负责出表和对比基线。

用法(在服务器上跑,压测器不要和被压服务同机):
    python3 perf/run.py --scenario api_read --conns 100 --dur 30 --out perf/results/api100.json
    python3 perf/run.py --scenario ws_burst --conns 500 --count 1 --out perf/results/ws500.json

带鉴权的写场景(写接口的限流都按用户计,单账号压不出容量,必须多账号):
    python3 manage.py perf_tokens --count 50 --out perf/results/headers.jsonl   # 源端签令牌
    python3 perf/run.py --scenario api_write --path /api/v1/discovery/swipe \\
        --method POST --header 'Content-Type: application/json' \\
        --body '{"target_user_id": {i}, "action": "like"}' --i-start 20001 \\
        --headers-file perf/results/headers.jsonl --conns 50 --dur 30 \\
        --out perf/results/write_swipe50.json

场景:
    api_read     GET 一个只读接口(默认 /api/v1/app/config,可 --path 覆盖)
    api_health   GET /api/v1/health(最轻的探活路径,用来测框架开销)
    api_write    POST 一个写接口(必须 --path;鉴权靠 --header / --headers-file,
                 请求体靠 --body,路径与请求体里的 {i} 会替换成自增序号)
    api_upload   multipart 上传(默认 /api/v1/im/images,必须 --file 给图片;
                 --field 是文件字段名,默认 file;--form 追加普通表单字段)
    api_mixed    混合读写:一条连接固定一个角色,按 --write-ratio(默认 0.3)均匀分配,
                 写侧用 --write-path/--write-body,读侧用 --path/--body;
                 配合 --dur 1800 就是「70 读 30 写 30 分钟」那条场景
    ws_burst     WS 突发:每个连接发 --count 条,委托 imserver/scripts/bench_ws.py
    ws_steady    WS 稳态:每连接每 --interval 秒发 1 条,持续 --dur 秒
    ws_reconnect WS 重连风暴:全部客户端连上后由 --restart-cmd 重启服务端,
                 客户端立刻无退避重连,委托 imserver/scripts/bench_ws_reconnect.py

`--ramp` 让连接在 N 秒内逐步建立(默认 0 = 全部立刻建),用来区分「0→1000 瞬间突发」
与「0→1000 爬坡」;`--sample-interval` 控制内存曲线的采样间隔(秒,默认 15)。

读连接同样能限速:`--read-interval 0.6` = 每条连接每次请求后等 0.6 秒。
压 `GET /discovery/candidates` 这种 per-user 限额的读接口时必须用它
(默认闭循环几秒就把 60 次/小时的额度打光,压出来的是 429 而不是容量;
E-7 的开/关缓存对比实验就是靠它把每账号请求数压在额度内的)。

请求头有两层,按「默认 → --header → --headers-file 里该连接那一套」合并(后者覆盖前者):
    --header        公共头,可重复,例如 --header 'Content-Type: application/json'
    --headers-file  一行一个 JSON 对象,连接按行轮转 —— 一个账号一个令牌,
                    写接口的 per-user 限流才不会被单账号额度卡死

令牌脱敏:结果 JSON 只记头名与头集套数,头的**值绝不落盘**(结果文件会进 git)。

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
    "api_upload": "/api/v1/im/images",
    # 混合场景的读侧默认用最轻的公开读接口;写侧必须显式给 --write-path
    "api_mixed": "/api/v1/app/config",
}

# 写场景刻意不给默认路径:写接口的请求体各不相同,猜一个默认值只会压出 400。
DEFAULT_METHODS = {
    "api_read": "GET",
    "api_health": "GET",
    "api_write": "POST",
    "api_upload": "POST",
    "api_mixed": "GET",
    "ws_burst": "GET",
    "ws_steady": "GET",
    "ws_reconnect": "GET",
}

HTTP_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}

# 上传场景的固定分隔符:一次压测里所有请求共用同一个 boundary,
# 这样请求体可以只拼一次(二进制文件体不会被反复复制)。
MULTIPART_BOUNDARY = "----chatappperfboundary"

UPLOAD_CONTENT_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

COUNTER_TOKEN = "{i}"      # 路径 / 请求体里的自增序号占位符

DEFAULT_HEADERS = {
    "Accept": "*/*",
    "Connection": "keep-alive",
    "User-Agent": "chatapp-perf",
    # 直连 gunicorn 时模拟 nginx 追加的两跳头;真走 nginx 时会被真实值覆盖/追加
    "X-Forwarded-Proto": "https",
    "X-Real-IP": "10.99.0.1",
}

BENCH_WS = Path(__file__).resolve().parent.parent / "imserver" / "scripts" / "bench_ws.py"
BENCH_WS_RECONNECT = (Path(__file__).resolve().parent.parent
                      / "imserver" / "scripts" / "bench_ws_reconnect.py")


def parse_header_arg(text: str) -> tuple[str, str]:
    """把 ``Name: Value`` 解析成二元组(argparse 的 type 回调)。

    Args:
        text: 命令行传入的原始头,例如 ``Authorization: Bearer xxx``。

    Returns:
        (头名, 头值)。

    Raises:
        argparse.ArgumentTypeError: 缺少冒号或头名为空,由 argparse 转成退出码 2。
    """
    name, sep, value = text.partition(":")
    if not sep or not name.strip():
        raise argparse.ArgumentTypeError(f"头部格式应为 'Name: Value',收到 {text!r}")
    return name.strip(), value.strip()


def merge_headers(*layers: dict[str, str]) -> dict[str, str]:
    """按顺序合并多层请求头,同名(大小写不敏感)时后者覆盖前者。

    Args:
        *layers: 若干 ``{名: 值}`` 字典。

    Returns:
        合并后的字典(键名用最后一次出现的写法,顺序保持稳定)。
    """
    merged: dict[str, str] = {}
    spelling: dict[str, str] = {}
    for layer in layers:
        for name, value in layer.items():
            low = name.lower()
            if low in spelling:
                merged.pop(spelling[low], None)
            spelling[low] = name
            merged[name] = value
    return merged


def has_header(headers: dict[str, str], name: str) -> bool:
    """判断头集合里是否已有某个头(大小写不敏感)。

    Args:
        headers: 请求头字典。
        name: 要查的头名。

    Returns:
        存在即 True。
    """
    return any(key.lower() == name.lower() for key in headers)


def build_request(method: str, path: str, headers: dict[str, str], body: str,
                  encoding: str = "utf-8") -> bytes:
    """拼一个 HTTP/1.1 请求(带 Content-Length,供 keep-alive 复用)。

    Args:
        method: 请求方法。
        path: 请求路径(可带查询串)。
        headers: 已合并的请求头;``Host`` 需由调用方放入。
        body: 请求体文本,空串表示无体。
        encoding: 请求体编码。上传场景用 ``latin-1`` —— multipart 体里混着图片
            二进制,``latin-1`` 是唯一能把 bytes 与 str 无损互转的单字节编码。

    Returns:
        可直接写进 socket 的字节串。
    """
    final = dict(headers)
    payload = body.encode(encoding)
    if payload:
        if not has_header(final, "Content-Type"):
            final["Content-Type"] = "application/json"
        final["Content-Length"] = str(len(payload))
    head = "".join(f"{name}: {value}\r\n" for name, value in final.items())
    return f"{method} {path} HTTP/1.1\r\n{head}\r\n".encode() + payload


def load_body(text: str) -> str:
    """解析 ``--body``:``@路径`` 表示读文件,其余当字面量。

    Args:
        text: 命令行原值。

    Returns:
        请求体文本。

    Raises:
        ValueError: 指定了 ``@文件`` 但文件不存在或读不出来。
    """
    if not text.startswith("@"):
        return text
    path = Path(text[1:])
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"读取 --body 文件失败:{path}({error})") from error


def load_upload(path: str, field: str = "file",
                extra_fields: dict[str, str] | None = None) -> tuple[str, str]:
    """把一张图片包成 multipart/form-data 请求体。

    Args:
        path: 图片文件路径(``.jpg`` / ``.png`` / ``.webp``,按扩展名定 Content-Type)。
        field: 文件字段名,服务端 ``request.FILES`` 里用的那个键。
        extra_fields: 附带提交的普通表单字段(如 ``visibility: public``)。

    Returns:
        ``(请求体文本, Content-Type 头值)``;请求体用 ``latin-1`` 才能和 bytes 无损互转。

    Raises:
        ValueError: 文件不存在、读不出来,或扩展名不在支持列表里。
    """
    file_path = Path(path)
    try:
        content = file_path.read_bytes()
    except OSError as error:
        raise ValueError(f"读取 --file 失败:{file_path}({error})") from error
    ctype = UPLOAD_CONTENT_TYPES.get(file_path.suffix.lower())
    if not ctype:
        raise ValueError(
            f"--file 只支持 {'/'.join(sorted(UPLOAD_CONTENT_TYPES))},收到 {file_path.suffix!r}")
    lines = []
    for name, value in (extra_fields or {}).items():
        lines.append(f'--{MULTIPART_BOUNDARY}\r\n'
                     f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                     f'{value}\r\n')
    lines.append(f'--{MULTIPART_BOUNDARY}\r\n'
                 f'Content-Disposition: form-data; name="{field}"; filename="{file_path.name}"\r\n'
                 f'Content-Type: {ctype}\r\n\r\n')
    head = "".join(lines)
    tail = f"\r\n--{MULTIPART_BOUNDARY}--\r\n"
    return head + content.decode("latin-1") + tail, f"multipart/form-data; boundary={MULTIPART_BOUNDARY}"


def load_header_sets(path: str) -> list[dict[str, str]]:
    """读「每连接一套头」的文件:一行一个 JSON 对象,连接按行轮转。

    为什么按连接轮转而不是按请求:一个账号的令牌可以给多条连接共用,但写接口的
    限流是**按用户**计的,要压出真实容量就得一条连接一个账号。

    Args:
        path: 文件路径;空行与 ``#`` 开头的行忽略。

    Returns:
        头集合列表(至少一项)。

    Raises:
        ValueError: 文件不可读、某行不是 JSON 对象,或键值不是字符串。
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as error:
        raise ValueError(f"读取 --headers-file 失败:{path}({error})") from error
    sets: list[dict[str, str]] = []
    for lineno, line in enumerate(raw.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path} 第 {lineno} 行不是合法 JSON:{error}") from error
        if not isinstance(item, dict) or not all(
                isinstance(key, str) and isinstance(value, str)
                for key, value in item.items()):
            raise ValueError(f"{path} 第 {lineno} 行必须是 {{头名: 头值}} 的 JSON 对象")
        sets.append(item)
    if not sets:
        raise ValueError(f"{path} 里没有任何头集")
    return sets


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


async def one_conn(args, stats: dict, stop: asyncio.Event, index: int,
                   counter: dict, header_sets: list[dict[str, str]],
                   spec: dict, start_delay: float = 0.0) -> None:
    """一条连接上的闭循环(发请求 → 读完 → 再发),等价于 wrk 的 -c。

    Args:
        args: 命令行参数。
        stats: 共享统计容器。
        stop: 停止信号。
        index: 连接序号,用来轮转 ``--headers-file`` 里的头集。
        counter: ``{"i": 下一个序号}``,``{i}`` 占位符的取值来源(全局唯一)。
        header_sets: 每连接一套的额外请求头;空列表表示没有。
        spec: 这条连接要发的请求(``method`` / ``path`` / ``body`` / ``encoding``)。
            混合场景下由调用方按角色挑好,单场景下所有连接共用同一份。
        start_delay: 建连前的等待秒数,``--ramp`` 用它把连接摊开。
    """
    ctx = None
    if args.tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    if start_delay:
        await asyncio.sleep(start_delay)
    try:
        reader, writer = await asyncio.open_connection(
            args.host, args.port, ssl=ctx,
            server_hostname=args.sni if args.tls else None)
    except Exception as exc:  # noqa: BLE001  连接失败要计入错误率而不是崩掉
        stats["codes"][f"connect:{type(exc).__name__}"] += 1
        return
    headers = merge_headers(
        DEFAULT_HEADERS,
        {"Host": args.sni or args.host},
        dict(args.header),
        header_sets[index % len(header_sets)] if header_sets else {})
    templated = COUNTER_TOKEN in spec["path"] or COUNTER_TOKEN in spec["body"]
    static = None if templated else build_request(
        spec["method"], spec["path"], headers, spec["body"], spec["encoding"])
    try:
        while not stop.is_set():
            if static is not None:
                request = static
            else:
                value = counter["i"]
                counter["i"] += 1
                request = build_request(
                    spec["method"],
                    spec["path"].replace(COUNTER_TOKEN, str(value)),
                    headers,
                    spec["body"].replace(COUNTER_TOKEN, str(value)),
                    spec["encoding"])
            started = time.perf_counter()
            writer.write(request)
            await writer.drain()
            status, _ = await read_response(reader)
            stats["lat"].append(time.perf_counter() - started)
            stats["codes"][str(status)] += 1
            stats["n"] += 1
            if spec.get("interval"):
                # 按用户配额限速:写接口都是 per-user 限流,不打散节奏会压出成片 429
                await asyncio.sleep(spec["interval"])
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


def read_swap_mb() -> float | None:
    """读一次已用 swap(MB);非 Linux 返回 None。

    Returns:
        已用 swap 的 MB 数。
    """
    try:
        meminfo = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, _, rest = line.partition(":")
            meminfo[key] = int(rest.strip().split()[0])
        return round((meminfo["SwapTotal"] - meminfo["SwapFree"]) / 1024, 1)
    except Exception:  # noqa: BLE001
        return None


async def sample_resources(stats: dict, stop: asyncio.Event, interval: float = 1.0,
                           curve_every: float = 15.0) -> None:
    """每秒采一次负载/内存(记峰值),另外按 ``curve_every`` 记一条内存曲线。

    峰值只回答「最高到多少」;30 分钟的长跑还需要「什么时候开始换页」,
    所以曲线点带相对时间戳,写进结果 JSON 的 ``resources.mem_curve``。

    Args:
        stats: 共享统计容器(写 ``load_peak`` / ``mem_peak`` / ``curve``)。
        stop: 停止信号。
        interval: 采样间隔(秒)。
        curve_every: 曲线点间隔(秒);0 表示不记曲线。
    """
    started = time.perf_counter()
    next_curve = 0.0
    while not stop.is_set():
        load1, used_mb = read_load()
        if load1 is not None:
            stats["load_peak"] = max(stats.get("load_peak") or 0, load1)
        if used_mb is not None:
            stats["mem_peak"] = max(stats.get("mem_peak") or 0, used_mb)
        now = time.perf_counter() - started
        if curve_every and now >= next_curve:
            next_curve = now + curve_every
            stats.setdefault("curve", []).append(
                [round(now, 1), used_mb, read_swap_mb(), load1])
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
        except asyncio.TimeoutError:
            pass


def role_is_write(index: int, ratio: float) -> bool:
    """按连接序号决定混合场景里的角色(写/读)。

    用 ``int((index+1)*ratio) > int(index*ratio)`` 而不是 ``index < ratio*n``:
    前者把写连接**均匀摊开**在全部连接里,后者在连接数少时会把写角色全挤到前几个号,
    压出来的是「前面几条连接很忙、后面全闲」的假象。

    Args:
        index: 连接序号(从 0 开始)。
        ratio: 写连接占比(0~1)。

    Returns:
        True 表示这条连接走写路径。
    """
    if ratio <= 0:
        return False
    if ratio >= 1:
        return True
    return int((index + 1) * ratio) > int(index * ratio)


def request_specs(args) -> tuple[list[dict], list[dict]]:
    """按场景给出「读请求」与「写请求」两份 spec。

    Args:
        args: 命令行参数(已归一)。

    Returns:
        ``(read_specs, write_specs)``;单场景下两份里只有一份非空,
        混合场景两份都有,``pick_spec`` 再按角色挑。
    """
    encoding = getattr(args, "body_encoding", "utf-8")
    read_spec = {"method": args.method, "path": args.path, "body": args.body,
                 "encoding": encoding,
                 "interval": getattr(args, "read_interval", 0) or 0}
    if args.scenario != "api_mixed":
        return [read_spec], []
    write_spec = {"method": args.write_method, "path": args.write_path,
                  "body": args.write_body, "encoding": "utf-8",
                  "interval": getattr(args, "write_interval", 0) or 0}
    return [read_spec], [write_spec]


def pick_spec(args, read_specs: list[dict], write_specs: list[dict], index: int) -> dict:
    """给第 ``index`` 条连接挑一份请求 spec。

    Args:
        args: 命令行参数。
        read_specs: 读路径 spec 列表。
        write_specs: 写路径 spec 列表。
        index: 连接序号。

    Returns:
        该连接固定使用的 spec(整条连接生命周期内不变)。
    """
    if write_specs and role_is_write(index, args.write_ratio):
        return write_specs[0]
    return read_specs[0]


async def run_http(args, header_sets: list[dict[str, str]]) -> dict:
    """跑 HTTP 场景。

    Args:
        args: 命令行参数。
        header_sets: 每连接一套的额外请求头;空列表表示只用 ``--header``。

    Returns:
        结果字典(``requests`` / ``rps`` / ``error_rate`` / ``lat_ms`` 等)。
    """
    stats = {"n": 0, "lat": [], "codes": Counter()}
    stop = asyncio.Event()
    counter = {"i": args.i_start}
    read_specs, write_specs = request_specs(args)
    ramp = float(getattr(args, "ramp", 0) or 0)
    started = time.perf_counter()
    tasks = [asyncio.create_task(
        one_conn(args, stats, stop, index, counter, header_sets,
                 pick_spec(args, read_specs, write_specs, index),
                 start_delay=(ramp * index / args.conns) if ramp else 0.0))
        for index in range(args.conns)]
    sampler = asyncio.create_task(sample_resources(
        stats, stop, curve_every=float(getattr(args, "sample_interval", 15) or 0)))
    await asyncio.sleep(args.dur)
    stop.set()
    await asyncio.wait(tasks, timeout=10)
    await asyncio.wait([sampler], timeout=3)
    for task in tasks:
        task.cancel()
    elapsed = time.perf_counter() - started

    codes = dict(stats["codes"])
    failures = sum(count for code, count in codes.items() if not code.startswith("2"))
    result = {
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
    if stats.get("curve"):
        result["mem_curve"] = stats["curve"]
    if write_specs:
        # 混合场景的读写各自耗时不同,分开报分位数,否则平均值毫无意义
        result["mixed"] = {
            "write_ratio": args.write_ratio,
            "write_conns": sum(1 for i in range(args.conns)
                               if role_is_write(i, args.write_ratio)),
            "read_conns": sum(1 for i in range(args.conns)
                              if not role_is_write(i, args.write_ratio)),
        }
    return result


def run_ws_reconnect(args) -> dict:
    """跑 WS 重连风暴:先让全部客户端连上,再重启服务端,测「多快全部回来」。

    编排放在这里而不是脚本里:脚本只管连/断/重连,「重启服务端」是环境动作
    (``docker restart imserver``),用 ``--restart-cmd`` 显式传进来 —— 压测脚本
    不该自己猜怎么重启别人的服务。

    Args:
        args: 命令行参数(需 ``--restart-cmd``)。

    Returns:
        bench_ws_reconnect 的结果字典。

    Raises:
        RuntimeError: 缺少脚本/缺少 ``--restart-cmd``/脚本失败。
    """
    if not BENCH_WS_RECONNECT.exists():
        raise RuntimeError(f"缺少 {BENCH_WS_RECONNECT}")
    if not args.restart_cmd:
        raise RuntimeError("ws_reconnect 必须给 --restart-cmd(例如 'docker restart imserver')")
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as handle:
        out_path = handle.name
    command = [sys.executable, str(BENCH_WS_RECONNECT), "--n", str(args.conns),
               "--duration", str(args.dur), "--out", out_path]
    if args.uri:
        command += ["--uri", args.uri]
    process = subprocess.Popen(command, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    restarted = False
    deadline = time.time() + 180
    try:
        while True:
            line = process.stdout.readline()
            if not line:
                break
            print(line.rstrip(), flush=True)
            if not restarted and line.startswith("ready"):
                subprocess.run(args.restart_cmd, shell=True, check=True,
                               capture_output=True, text=True, timeout=120)
                restarted = True
                print(f"restarted via: {args.restart_cmd}", flush=True)
            if time.time() > deadline:
                process.kill()
                raise RuntimeError("ws_reconnect 超时(180s)")
        process.wait(timeout=60)
    finally:
        if process.poll() is None:
            process.kill()
    if process.returncode != 0:
        raise RuntimeError("bench_ws_reconnect 失败:\n" + (process.stderr.read() or "")[-2000:])
    if not restarted:
        raise RuntimeError("bench_ws_reconnect 没有输出 ready 行,重启没触发")
    with open(out_path, encoding="utf-8") as handle:
        result = json.load(handle)
    os.unlink(out_path)
    return {
        "connected": result.get("connected_initial"),
        "reconnects": result.get("reconnects_ok"),
        "requests": result.get("reconnects_ok"),
        "rps": None,
        "error_rate": round(result.get("reconnects_fail", 0)
                            / max(result.get("reconnects_ok", 1), 1), 4),
        "lat_ms": result.get("recovery_ms"),
        "codes": {"connect_fail": result.get("connect_fail"),
                  "auth_fail": result.get("auth_fail"),
                  "reconnects_fail": result.get("reconnects_fail")},
        "cycles": result.get("cycles"),
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
    if args.scenario == "ws_reconnect":
        return run_ws_reconnect(args)
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


def build_payload(args, header_sets: list[dict[str, str]], result: dict,
                  started_at: str) -> dict:
    """组装要落盘的结果 JSON。

    令牌类信息绝不落盘:``--header`` 只记头名,``--headers-file`` 只记套数 ——
    结果文件会进 git,把 ``Authorization`` 的值写进去等于泄露登录态。

    Args:
        args: 命令行参数(已归一:path / method / body 都有值)。
        header_sets: ``--headers-file`` 读到的头集。
        result: 压测结果字典,其中的 ``load_peak`` / ``mem_peak`` 会被移到 resources。
        started_at: 开始时间(ISO 字符串)。

    Returns:
        结果 payload。
    """
    header_names = {name for name, _ in args.header}
    for extra in header_sets:
        header_names |= set(extra)
    params = {
        "target": f"{args.host}:{args.port}{args.path}",
        "method": args.method,
        "path": args.path,
        "conns": args.conns,
        "duration_s": args.dur,
        "count": args.count if args.scenario == "ws_burst" else None,
        "interval": args.interval if args.scenario == "ws_steady" else None,
        "read_interval_s": getattr(args, "read_interval", 0) or 0,
        "write_interval_s": getattr(args, "write_interval", 0) or 0,
        "tls": args.tls,
        "body_bytes": len(args.body.encode(getattr(args, "body_encoding", "utf-8")))
        if args.body else 0,
        "body_template": COUNTER_TOKEN in args.path or COUNTER_TOKEN in args.body,
        "headers": {"names": sorted(header_names), "sets": len(header_sets)},
        "ramp_s": getattr(args, "ramp", 0) or 0,
        "sample_interval_s": getattr(args, "sample_interval", 0) or 0,
    }
    if args.scenario == "api_mixed":
        params["write"] = {
            "method": args.write_method,
            "path": args.write_path,
            "body_bytes": len(args.write_body.encode()) if args.write_body else 0,
            "ratio": args.write_ratio,
        }
    if args.scenario == "api_upload":
        params["upload"] = {"file": Path(args.file).name, "field": args.field,
                            "form_fields": sorted(dict(args.form))}
    if args.scenario == "ws_reconnect":
        params["restart_cmd"] = args.restart_cmd
    return {
        "schema": 1,
        "scenario": args.scenario,
        "started_at": started_at,
        "machine": machine_spec(),
        "params": params,
        "result": result,
        "resources": {
            "load1_peak": result.pop("load_peak", None),
            "mem_used_mb_peak": result.pop("mem_peak", None),
        },
    }


def normalize_args(args) -> str:
    """把 ``--path`` / ``--method`` / ``--body`` 归一,并做参数期校验。

    Args:
        args: argparse 解析结果(会被就地改写)。

    Returns:
        空字符串表示通过;否则是要打印的中文错误说明(不含「参数错误」前缀)。
    """
    if args.method:
        method = args.method.upper()
        if method not in HTTP_METHODS:
            return f"--method 只支持 {'/'.join(sorted(HTTP_METHODS))},收到 {args.method!r}"
        args.method = method
    else:
        args.method = DEFAULT_METHODS.get(args.scenario, "GET")

    if args.scenario.startswith("api"):
        args.path = args.path or SCENARIO_PATHS.get(args.scenario, "")
        if not args.path:
            return (f"{args.scenario} 必须显式给 --path"
                    "(写接口没有通用默认值)")
        if not args.path.startswith("/"):
            return f"--path 要以 / 开头,收到 {args.path!r}"

    args.body_encoding = "utf-8"
    if args.scenario == "api_upload":
        if not args.file:
            return "api_upload 必须给 --file(要上传的图片)"
        try:
            args.body, content_type = load_upload(args.file, args.field, dict(args.form))
        except ValueError as error:
            return str(error)
        # 文件体是二进制,只有 latin-1 能无损塞进 str 再编码回 bytes
        args.body_encoding = "latin-1"
        args.header = list(args.header) + [("Content-Type", content_type)]

    if getattr(args, "read_interval", 0) < 0:
        return f"--read-interval 不能为负,收到 {args.read_interval}"

    if args.scenario == "api_mixed":
        if not args.write_path:
            return "api_mixed 必须给 --write-path(写侧接口)"
        if not args.write_path.startswith("/"):
            return f"--write-path 要以 / 开头,收到 {args.write_path!r}"
        if not 0 < args.write_ratio <= 1:
            return f"--write-ratio 要在 (0, 1] 之间,收到 {args.write_ratio}"
        if args.write_interval < 0:
            return f"--write-interval 不能为负,收到 {args.write_interval}"
        args.write_method = (args.write_method or "POST").upper()
        if args.write_method not in HTTP_METHODS:
            return (f"--write-method 只支持 {'/'.join(sorted(HTTP_METHODS))},"
                    f"收到 {args.write_method!r}")
        try:
            args.write_body = load_body(args.write_body)
        except ValueError as error:
            return str(error)

    try:
        args.body = load_body(args.body)
    except ValueError as error:
        return str(error)
    return ""


def main() -> int:
    """解析参数、跑场景、写结果 JSON。

    Returns:
        进程退出码。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True,
                        choices=["api_read", "api_health", "api_write", "api_upload",
                                 "api_mixed", "ws_burst", "ws_steady", "ws_reconnect"])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--path", default="",
                        help="请求路径;{i} 会替换成自增序号")
    parser.add_argument("--method", default="",
                        help="HTTP 方法;默认按场景(GET;api_write=POST)")
    parser.add_argument("--body", default="",
                        help="请求体;@文件 表示从文件读;{i} 会替换成自增序号")
    parser.add_argument("--file", default="", help="api_upload:要上传的图片路径")
    parser.add_argument("--field", default="file", help="api_upload:文件字段名,默认 file")
    parser.add_argument("--form", action="append", type=parse_header_arg, default=[],
                        metavar="'Name: Value'",
                        help="api_upload:附带的普通表单字段,可重复")
    parser.add_argument("--write-path", default="", help="api_mixed:写侧接口路径")
    parser.add_argument("--write-method", default="POST", help="api_mixed:写侧方法")
    parser.add_argument("--write-body", default="", help="api_mixed:写侧请求体")
    parser.add_argument("--write-ratio", type=float, default=0.3,
                        help="api_mixed:写连接占比,默认 0.3(即 70 读 30 写)")
    parser.add_argument("--write-interval", type=float, default=0,
                        help="api_mixed:写连接每次请求后的间隔秒(0=不限速;"
                             "写接口都是 per-user 限流,长跑时要靠它打散节奏)")
    parser.add_argument("--read-interval", type=float, default=0,
                        help="读连接每次请求后的间隔秒(0=闭循环不限速;"
                             "压 per-user 限流的读接口时靠它把每账号请求数压在额度内)")
    parser.add_argument("--ramp", type=float, default=0,
                        help="建连爬坡秒数:0=全部立刻建(瞬间突发),N=在 N 秒内摊开")
    parser.add_argument("--sample-interval", type=float, default=15,
                        help="内存曲线采样间隔秒;0=不记曲线")
    parser.add_argument("--i-start", type=int, default=1,
                        help="{i} 的起始值(压已造数数据时用来对准目标 id)")
    parser.add_argument("--header", action="append", type=parse_header_arg,
                        default=[], metavar="'Name: Value'",
                        help="公共请求头,可重复,例如 --header 'Authorization: Bearer xxx'")
    parser.add_argument("--headers-file", default="",
                        help="每连接一套头:一行一个 JSON 对象,连接按行轮转")
    parser.add_argument("--conns", type=int, default=100)
    parser.add_argument("--dur", type=int, default=20)
    parser.add_argument("--count", type=int, default=1, help="ws_burst:每连接发送条数")
    parser.add_argument("--interval", type=float, default=1.0, help="ws_steady:发送间隔秒")
    parser.add_argument("--uri", default="", help="ws_reconnect:WS 地址(默认用脚本内置)")
    parser.add_argument("--restart-cmd", default="",
                        help="ws_reconnect:连上后执行的重启命令,例如 'docker restart imserver'")
    parser.add_argument("--tls", action="store_true")
    parser.add_argument("--sni", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    problem = normalize_args(args)
    if problem:
        print(f"参数错误: {problem}", file=sys.stderr)
        return 2

    header_sets: list[dict[str, str]] = []
    if args.headers_file:
        try:
            header_sets = load_header_sets(args.headers_file)
        except ValueError as error:
            print(f"参数错误: {error}", file=sys.stderr)
            return 2

    started_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    try:
        if args.scenario.startswith("ws"):
            result = run_ws(args)
        else:
            result = asyncio.run(run_http(args, header_sets))
    except Exception as error:  # noqa: BLE001
        print(f"压测失败: {error}", file=sys.stderr)
        return 3

    payload = build_payload(args, header_sets, result, started_at)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    print(text)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
