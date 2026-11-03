"""冷启动压测:500 对全新配对同时发第一条消息,验证 imserver 不再因间隙锁死锁。

背景(2026-11-01 压测 P0-1):`im_conversation` 的唯一键 `(user_a,user_b)` 上,
`lock_pair` 先对「不存在的行」做 `SELECT ... FOR UPDATE`,REPEATABLE READ 下加的是
间隙锁;500 个事务抢同一段间隙 → 1213 死锁,实测 819/1000 失败。

修复后 `INSERT ... ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)` 放在事务最前面,
并发插入退化成唯一键上的等锁,同一脚本应 0 失败。

用法(在 imserver 测试容器里,MySQL/Redis 已就绪):
    python3 /src/scripts/bench_cold_start.py --n 500

脚本自己负责:造 N 个账号与环形配对 → 拉起 imserver → 跑 bench_ws(每个连接发 1 条)
→ 断言 0 失败 → 清理数据。退出码 0 = 通过。
"""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request

import pymysql

BASE_UID = 900001


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


def seed(conn, n: int) -> None:
    """造 N 个账号与环形配对(900001→900002→…→900001)。

    Args:
        conn: pymysql 连接。
        n: 账号数量,同时也是「全新会话」的数量。
    """
    now = int(time.time() * 1000)
    users = [(BASE_UID + i, f"cold{i}", "", now) for i in range(n)]
    pairs = []
    for i in range(n):
        a = BASE_UID + i
        b = BASE_UID + ((i + 1) % n)
        pairs.append((min(a, b), max(a, b), now))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO im_user (user_id,nickname,avatar_url,updated_at) "
            "VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE nickname=VALUES(nickname)",
            users)
        cur.executemany(
            "INSERT IGNORE INTO im_pair (user_a,user_b,created_at) VALUES (%s,%s,%s)",
            pairs)


def cleanup(conn, n: int) -> None:
    """删掉本次造的账号、配对与它们产生的会话/消息。

    Args:
        conn: pymysql 连接。
        n: 账号数量。
    """
    lo, hi = BASE_UID, BASE_UID + n
    with conn.cursor() as cur:
        cur.execute("DELETE FROM im_message WHERE from_id>=%s AND from_id<%s", (lo, hi))
        cur.execute("DELETE FROM im_conversation_state WHERE owner_id>=%s AND owner_id<%s",
                    (lo, hi))
        cur.execute("DELETE FROM im_conversation WHERE user_a>=%s AND user_a<%s", (lo, hi))
        cur.execute("DELETE FROM im_pair WHERE user_a>=%s AND user_a<%s", (lo, hi))
        cur.execute("DELETE FROM im_user WHERE user_id>=%s AND user_id<%s", (lo, hi))


def wait_ready(port: int, timeout_s: int = 60) -> bool:
    """轮询 imserver 的 ``/internal/readyz``,直到 200 或超时。

    Args:
        port: imserver HTTP 端口。
        timeout_s: 最长等待秒数。

    Returns:
        True 表示就绪。
    """
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/internal/readyz", timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:  # noqa: BLE001  启动期连不上是常态
            pass
        time.sleep(0.5)
    return False


def main() -> int:
    """造数 → 起服务 → 压测 → 断言 → 清理。

    Returns:
        进程退出码:0 通过,1 失败。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=500)
    parser.add_argument("--http-port", type=int, default=9101)
    parser.add_argument("--out", default="/tmp/cold_start.json")
    args = parser.parse_args()

    conn = pymysql.connect(**parse_dsn(os.environ["IM_MYSQL_DSN"]))
    cleanup(conn, args.n)          # 上一次失败的残留先清掉,保证「全新会话」
    seed(conn, args.n)

    server = subprocess.Popen(["/src/build/imserver"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        if not wait_ready(args.http_port):
            print("FAIL: imserver 未在 60s 内就绪")
            return 1
        bench = subprocess.run(
            [sys.executable, "/src/scripts/bench_ws.py",
             "--n", str(args.n), "--count", "1", "--out", args.out],
            capture_output=True, text=True, timeout=300)
        if bench.returncode != 0:
            print(bench.stdout[-2000:])
            print(bench.stderr[-2000:])
            print("FAIL: bench_ws 退出码非 0")
            return 1
        with open(args.out, encoding="utf-8") as fh:
            result = json.load(fh)
    finally:
        server.send_signal(signal.SIGTERM)
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()

    send_fail = result.get("send_fail", -1)
    errors = result.get("errors_total", -1)
    acked = result.get("ack_total", 0)
    print(json.dumps({
        "n": args.n,
        "connected": result.get("connected"),
        "send_fail": send_fail,
        "errors_total": errors,
        "ack_total": acked,
        "ack_ms": result.get("ack_ms"),
        "errors_sample": result.get("errors_sample"),
    }, ensure_ascii=False, indent=2))

    cleanup(conn, args.n)
    conn.close()

    ok = send_fail == 0 and errors == 0 and acked == args.n
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
