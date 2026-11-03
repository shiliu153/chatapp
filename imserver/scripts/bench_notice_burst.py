"""IM 通知突发压测:对比「不限速」与「按速率平滑」两种投递方式对 imserver 的影响。

背景(2026-11-03 削峰):配对高峰时 500 对同时匹配 → 1000 条灰条通知瞬间入队。
imserver 单机天花板 ~215 msg/s,不限速会把 ack p99 从 93ms 推到秒级。
本脚本直接打 imserver 的内部发送接口(绕过 Celery),用同一批数据对比两种投递方式。

用法(在 imserver 测试容器里,MySQL/Redis 已就绪):
    python3 /src/scripts/bench_notice_burst.py --n 500 --threads 20 --mode burst
    python3 /src/scripts/bench_notice_burst.py --n 500 --mode paced --rate 50

输出:成功率、错误码分布、延迟 p50/p95/p99。
退出码:0 全部成功;1 有失败。
"""

import argparse
import hashlib
import hmac
import http.client
import json
import os
import signal
import subprocess
import sys
import threading
import time
import urllib.parse

import pymysql

BASE_UID = 910001
HTTP_PORT = 9101
PATH = "/internal/send"


def parse_dsn(dsn: str) -> dict:
    """把 ``mysql://user:pass@host:port/db`` 解析成 pymysql 参数。

    Args:
        dsn: imserver 使用的 MySQL 连接串。

    Returns:
        pymysql.connect 需要的参数字典。
    """
    parsed = urllib.parse.urlparse(dsn)
    return {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "user": parsed.username,
        "password": parsed.password,
        "database": (parsed.path or "/").lstrip("/"),
        "charset": "utf8mb4",
        "autocommit": True,
    }


def seed(conn, n: int) -> list[tuple[int, int]]:
    """造 N 个账号与 N 对全新配对(每对都是冷会话)。

    Args:
        conn: pymysql 连接。
        n: 配对数量。

    Returns:
        (发送方, 接收方) 列表。
    """
    now = int(time.time() * 1000)
    users = [(BASE_UID + i, f"burst{i}", "", now) for i in range(2 * n)]
    pairs = [(BASE_UID + i, BASE_UID + n + i) for i in range(n)]
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO im_user (user_id,nickname,avatar_url,updated_at) "
            "VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE nickname=VALUES(nickname)",
            users)
        cur.executemany(
            "INSERT IGNORE INTO im_pair (user_a,user_b,created_at) VALUES (%s,%s,%s)",
            [(a, b, now) for a, b in pairs])
    return pairs


def cleanup(conn, n: int) -> None:
    """删掉本次造的数据。

    Args:
        conn: pymysql 连接。
        n: 配对数量。
    """
    lo, hi = BASE_UID, BASE_UID + 2 * n
    with conn.cursor() as cur:
        cur.execute("DELETE FROM im_message WHERE from_id>=%s AND from_id<%s", (lo, hi))
        cur.execute("DELETE FROM im_conversation_state WHERE owner_id>=%s AND owner_id<%s",
                    (lo, hi))
        cur.execute("DELETE FROM im_conversation WHERE user_a>=%s AND user_a<%s", (lo, hi))
        cur.execute("DELETE FROM im_pair WHERE user_a>=%s AND user_a<%s", (lo, hi))
        cur.execute("DELETE FROM im_user WHERE user_id>=%s AND user_id<%s", (lo, hi))


def send_one(secret: str, a: int, b: int,
             samples: list, codes: dict, lock: threading.Lock) -> None:
    """发一条内部通知并记录延迟/状态码。

    每条请求新建连接:imserver 的 HTTP 处理是「一问一答后关闭」,没有 keep-alive,
    复用连接会得到 ``CannotSendRequest``(第一次压测就踩到了)。

    Args:
        secret: ``IM_INTERNAL_SECRET``。
        a: 发送方 uid。
        b: 接收方 uid。
        samples: 延迟样本列表(秒)。
        codes: 状态码计数。
        lock: 保护共享容器的锁。
    """
    body = json.dumps({"from": a, "to": b, "kind": "text", "text": "burst"})
    timestamp = str(int(time.time()))
    signing = f"{timestamp}\nPOST\n{PATH}\n{body}".encode()
    signature = hmac.new(secret.encode(), signing, hashlib.sha256).hexdigest()
    started = time.perf_counter()
    conn = None
    try:
        conn = http.client.HTTPConnection("127.0.0.1", HTTP_PORT, timeout=30)
        conn.request("POST", PATH, body=body, headers={
            "Content-Type": "application/json",
            "X-IM-Timestamp": timestamp,
            "X-IM-Signature": signature,
        })
        response = conn.getresponse()
        response.read()
        code = response.status
    except Exception as exc:  # noqa: BLE001  连接错误也要计入
        code = f"io:{type(exc).__name__}"
    finally:
        if conn is not None:
            conn.close()
    elapsed = time.perf_counter() - started
    with lock:
        samples.append(elapsed)
        codes[code] = codes.get(code, 0) + 1


def run(pairs, secret: str, threads: int, mode: str, rate: float) -> dict:
    """按指定模式投递全部通知。

    Args:
        pairs: (发送方, 接收方) 列表。
        secret: 内部接口密钥。
        threads: 并发线程数。
        mode: ``burst``(全速)或 ``paced``(按 rate 平滑)。
        rate: paced 模式下的每秒条数。

    Returns:
        结果字典(成功率、延迟分位、状态码分布)。
    """
    samples: list[float] = []
    codes: dict = {}
    lock = threading.Lock()

    def worker(chunk, delay_every: float):
        for index, (a, b) in enumerate(chunk):
            if mode == "paced" and delay_every > 0:
                time.sleep(delay_every)
            send_one(secret, a, b, samples, codes, lock)

    started = time.perf_counter()
    chunks = [pairs[i::threads] for i in range(threads)]
    delay_every = (threads / rate) if (mode == "paced" and rate > 0) else 0.0
    workers = [threading.Thread(target=worker, args=(chunk, delay_every))
               for chunk in chunks]
    for item in workers:
        item.start()
    for item in workers:
        item.join()
    elapsed = time.perf_counter() - started

    ordered = sorted(samples)

    def pct(p):
        if not ordered:
            return None
        idx = min(len(ordered) - 1, max(0, int(round(p / 100 * len(ordered) + 0.5)) - 1))
        return round(ordered[idx] * 1000, 1)

    failures = sum(count for code, count in codes.items()
                   if not str(code).startswith("2"))
    return {
        "mode": mode,
        "threads": threads,
        "rate": rate,
        "total": len(pairs),
        "elapsed_s": round(elapsed, 2),
        "throughput_per_s": round(len(pairs) / elapsed, 1) if elapsed else 0,
        "failures": failures,
        "codes": {str(k): v for k, v in codes.items()},
        "latency_ms": {"p50": pct(50), "p95": pct(95), "p99": pct(99),
                       "max": round(max(ordered) * 1000, 1) if ordered else None},
    }


def wait_ready(timeout_s: int = 60) -> bool:
    """等 imserver 的 readyz 返回 200。

    Args:
        timeout_s: 最长等待秒数。

    Returns:
        True 表示就绪。
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", HTTP_PORT, timeout=2)
            conn.request("GET", "/internal/readyz")
            if conn.getresponse().status == 200:
                conn.close()
                return True
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
    return False


def main() -> int:
    """造数 → 起服务 → 按模式投递 → 清理。

    Returns:
        进程退出码。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--threads", type=int, default=20)
    parser.add_argument("--mode", choices=["burst", "paced"], default="burst")
    parser.add_argument("--rate", type=float, default=50.0)
    parser.add_argument("--no-server", action="store_true", help="外部已起 imserver")
    args = parser.parse_args()

    secret = os.environ["IM_INTERNAL_SECRET"]
    conn = pymysql.connect(**parse_dsn(os.environ["IM_MYSQL_DSN"]))
    cleanup(conn, args.n)
    pairs = seed(conn, args.n)

    server = None
    if not args.no_server:
        server = subprocess.Popen(["/src/build/imserver"],
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_ready():
            print("FAIL: imserver 未就绪")
            return 1
        result = run(pairs, secret, args.threads, args.mode, args.rate)
    finally:
        if server is not None:
            server.send_signal(signal.SIGTERM)
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()

    cleanup(conn, args.n)
    conn.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["failures"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
