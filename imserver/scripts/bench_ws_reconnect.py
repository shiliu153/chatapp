"""WS 重连风暴:全部客户端连上后服务端被重启,看「多久全部回来、失败几次」。

为什么要单独一支脚本:``bench_ws.py`` 测的是「连上之后能发多快」,而重启场景测的是
**握手/鉴权路径**在瞬时高并发下的表现 —— 1000 个客户端在同一个 TCP 窗口里重新握手,
先撞 nginx 连接数、再撞 imserver 的 ``IpCounter``(单 IP 20 条),最后撞 MySQL 的连接池。

编排约定(见 ``perf/run.py::run_ws_reconnect``):
    1. 脚本把所有客户端连上并鉴权成功,然后打印一行 ``ready ...`` 并 flush;
    2. 外部(压测器)看到 ``ready`` 后执行 ``--restart-cmd``(例如 ``docker restart imserver``);
    3. 脚本里的客户端发现连接被关闭后**不退避、立刻重连**,记录每次重连的耗时;
    4. 跑满 ``--duration`` 秒后落盘 JSON。

用法:
    IM_JWT_SECRET=... python3 bench_ws_reconnect.py --n 1000 --duration 60 --out /tmp/reconnect.json

说明:
- 与 ``bench_ws.py`` 一样按连接伪造 ``X-Real-IP``(imserver 单 IP 最多 20 条连接);
- 令牌是脚本自己按 ``IM_JWT_SECRET`` 现签的,不走 Django,所以不需要账号库;
- 「恢复耗时」= 从这条连接发现断开,到重新鉴权成功(``auth_ok``)的时间。
"""

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import time
import uuid

import websockets

URI = 'ws://127.0.0.1:9100/im/ws'


def b64url(raw: bytes) -> str:
    """base64url 编码并去掉尾部 ``=``(JWT 要求)。

    Args:
        raw: 原始字节。

    Returns:
        URL 安全的 base64 字符串。
    """
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def mint(uid: int, secret: str) -> str:
    """按 imserver 的约定现签一个 HS256 JWT。

    Args:
        uid: 用户 id(imserver 侧的 ``uid`` claim)。
        secret: ``IM_JWT_SECRET``。

    Returns:
        可直接放进 ``auth`` 帧的令牌字符串。
    """
    now = int(time.time())
    header = {'alg': 'HS256', 'typ': 'JWT'}
    payload = {'sub': f'u{uid}', 'uid': uid, 'iat': now, 'exp': now + 3600,
               'jti': uuid.uuid4().hex[:16]}
    signing = f"{b64url(json.dumps(header, separators=(',', ':')).encode())}." \
              f"{b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    sig = hmac.new(secret.encode(), signing.encode(), hashlib.sha256).digest()
    return f'{signing}.{b64url(sig)}'


def pct(values, p):
    """取分位数(秒)。

    Args:
        values: 秒为单位的样本列表。
        p: 百分位(0-100)。

    Returns:
        分位数;样本为空时 None。
    """
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(p / 100 * len(ordered) + 0.5)) - 1))
    return ordered[idx]


def summary(values):
    """把一串秒值汇总成毫秒级的分位数表。

    Args:
        values: 秒为单位的样本列表。

    Returns:
        含 count/p50/p95/p99/max/avg(毫秒)的字典;空列表返回空字典。
    """
    if not values:
        return {}
    return {'count': len(values), 'p50': round(pct(values, 50) * 1000, 2),
            'p95': round(pct(values, 95) * 1000, 2),
            'p99': round(pct(values, 99) * 1000, 2),
            'max': round(max(values) * 1000, 2),
            'avg': round(sum(values) / len(values) * 1000, 2)}


async def connect_once(uri: str, token: str, ip: str):
    """建一条 WS 连接并完成鉴权。

    Args:
        uri: WS 地址。
        token: 现签的 JWT。
        ip: 伪造的客户端 IP(imserver 按它做连接数限制)。

    Returns:
        (websocket, 握手+鉴权耗时秒)。

    Raises:
        RuntimeError: 鉴权被拒(帧类型不是 ``auth_ok``)。
    """
    started = time.perf_counter()
    ws = await websockets.connect(uri, additional_headers={'X-Real-IP': ip},
                                  open_timeout=20, close_timeout=5, max_size=1 << 20)
    await ws.send(json.dumps({'v': 1, 'type': 'auth', 'data': {'token': token}}))
    frame = json.loads(await asyncio.wait_for(ws.recv(), 20))
    if frame.get('type') != 'auth_ok':
        await ws.close()
        raise RuntimeError(f'auth:{frame}')
    return ws, time.perf_counter() - started


async def run_client(i, token, uri, res, args, stop_evt):
    """一条客户端的完整生命周期:连上 → 等断开 → 立刻重连,直到时间到。

    Args:
        i: 连接序号。
        token: 该客户端的 JWT。
        uri: WS 地址。
        res: 共享统计容器。
        args: 命令行参数。
        stop_evt: 停止信号。
    """
    ip = f'10.30.{i // 250}.{i % 250 + 1}'
    ws = None
    try:
        ws, first = await connect_once(uri, token, ip)
        res['connect_lat'].append(first)
        res['connected'] += 1
        res['initial_ok'] += 1
    except Exception as exc:  # noqa: BLE001
        res['connect_fail'] += 1
        res['errors'].append(f'initial:{type(exc).__name__}:{exc}')
        if ws is not None:
            await ws.close()
        return

    while not stop_evt.is_set():
        try:
            # 只等「连接被关」:收到任何帧都不影响,重启时 ws 会抛 ConnectionClosed
            await asyncio.wait_for(ws.recv(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        except Exception:  # noqa: BLE001  连接断了(服务端重启)
            break

    # 无退避重连:这就是「风暴」的定义 —— 1000 个客户端在同一刻一起回来
    while not stop_evt.is_set():
        started = time.perf_counter()
        try:
            ws, _ = await connect_once(uri, token, ip)
        except Exception as exc:  # noqa: BLE001
            res['reconnects_fail'] += 1
            res['errors'].append(f'reconnect:{type(exc).__name__}:{exc}')
            await asyncio.sleep(0.05)
            continue
        elapsed = time.perf_counter() - started
        res['reconnect_lat'].append(elapsed)
        res['reconnects_ok'] += 1
        res['cycles'] += 1
        if res['reconnects_ok'] == res['n'] and res['full_recovery_at'] is None:
            res['full_recovery_at'] = time.perf_counter() - res['t_start']
        # 回来后保持连接直到停止信号
        while not stop_evt.is_set():
            try:
                await asyncio.wait_for(ws.recv(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except Exception:  # noqa: BLE001
                res['closed_early'] += 1
                break
        try:
            await ws.close()
        except Exception:  # noqa: BLE001
            pass


async def main():
    """连满 N 个客户端 → 打印 ready → 等重启 → 统计重连,落盘 JSON。"""
    parser = argparse.ArgumentParser()
    parser.add_argument('--n', type=int, default=1000)
    parser.add_argument('--duration', type=int, default=60, help='ready 之后观测多少秒')
    parser.add_argument('--uri', default=URI)
    parser.add_argument('--uid-base', type=int, default=900001)
    parser.add_argument('--out', default='/tmp/bench_reconnect.json')
    args = parser.parse_args()

    secret = os.environ['IM_JWT_SECRET']
    res = {'n': args.n, 'connected': 0, 'initial_ok': 0, 'connect_fail': 0,
           'reconnects_ok': 0, 'reconnects_fail': 0, 'closed_early': 0, 'cycles': 0,
           'full_recovery_at': None, 't_start': time.perf_counter(),
           'errors': [], 'connect_lat': [], 'reconnect_lat': []}

    tokens = [mint(args.uid_base + i, secret) for i in range(args.n)]
    stop_evt = asyncio.Event()
    tasks = []
    for i in range(args.n):
        tasks.append(asyncio.create_task(run_client(i, tokens[i], args.uri, res, args, stop_evt)))
        if (i + 1) % 25 == 0:
            await asyncio.sleep(0.1)

    deadline = time.perf_counter() + 60
    while time.perf_counter() < deadline:
        if res['connected'] + res['connect_fail'] >= args.n:
            break
        await asyncio.sleep(0.2)
    ramp = time.perf_counter() - res['t_start']
    print(f'ready ramp={ramp:.2f}s connected={res["connected"]} '
          f'fail={res["connect_fail"]}', flush=True)

    await asyncio.sleep(args.duration)
    stop_evt.set()
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)

    out = {
        'n': args.n,
        'connected_initial': res['connected'],
        'connect_fail': res['connect_fail'],
        'ramp_s': round(ramp, 2),
        'reconnects_ok': res['reconnects_ok'],
        'reconnects_fail': res['reconnects_fail'],
        'cycles': res['cycles'],
        'full_recovery_s': (round(res['full_recovery_at'], 2)
                            if res['full_recovery_at'] is not None else None),
        'connect_ms': summary(res['connect_lat']),
        'recovery_ms': summary(res['reconnect_lat']),
        'errors': res['errors'][:20],
    }
    with open(args.out, 'w', encoding='utf-8') as handle:
        json.dump(out, handle, ensure_ascii=False, indent=2)
    print(f'reconnect ok={res["reconnects_ok"]} fail={res["reconnects_fail"]} '
          f'full_recovery={out["full_recovery_s"]}s', flush=True)


if __name__ == '__main__':
    asyncio.run(main())
