"""500 连接压测:直连 imserver,按连接伪造 X-Real-IP 模拟不同客户端。

两种模式:
- burst(默认):所有连接在 1 秒内各发 2 条,测极限突发能力;
- steady:每条连接每隔 --interval 秒发 1 条,持续 --duration 秒,测正常聊天速率下的延迟。

用法:
    IM_JWT_SECRET=... python3 bench_ws.py --n 500 --interval 10 --duration 40 --out /tmp/bench_steady.json

说明:
- imserver 单 IP 最多 20 条连接(IpCounter),所以不能都从 127.0.0.1 进;
  生产里每个用户一个 IP,这里用 10.20.x.y 逐连接伪造,等价于 500 个客户端。
- 测的是 WS 握手 + 鉴权 + 发送到 ack 的端到端延迟(同机 loopback,不含公网 RTT)。
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
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def mint(uid: int, secret: str) -> str:
    now = int(time.time())
    header = {'alg': 'HS256', 'typ': 'JWT'}
    payload = {'sub': f'u{uid}', 'uid': uid, 'iat': now, 'exp': now + 3600,
               'jti': uuid.uuid4().hex[:16]}
    signing = f"{b64url(json.dumps(header, separators=(',', ':')).encode())}." \
              f"{b64url(json.dumps(payload, separators=(',', ':')).encode())}"
    sig = hmac.new(secret.encode(), signing.encode(), hashlib.sha256).digest()
    return f'{signing}.{b64url(sig)}'


def pct(values, p):
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round(p / 100 * len(ordered) + 0.5)) - 1))
    return ordered[idx]


def summary(values):
    if not values:
        return {}
    return {'count': len(values), 'p50': round(pct(values, 50) * 1000, 2),
            'p95': round(pct(values, 95) * 1000, 2),
            'p99': round(pct(values, 99) * 1000, 2),
            'max': round(max(values) * 1000, 2),
            'avg': round(sum(values) / len(values) * 1000, 2)}


async def send_one(ws, res, uid, k, peer, run_id):
    cid = f'{run_id}-{uid}-{k}'
    t0 = time.perf_counter()
    await ws.send(json.dumps({'v': 1, 'type': 'send', 'id': cid,
                              'data': {'to': f'u{peer}', 'text': f'bench {uid} {k}',
                                       'client_msg_id': cid}}))
    deadline = time.perf_counter() + 40
    while True:
        left = deadline - time.perf_counter()
        if left <= 0:
            raise asyncio.TimeoutError('ack timeout')
        frame = json.loads(await asyncio.wait_for(ws.recv(), left))
        kind = frame.get('type')
        if kind == 'ack' and frame.get('id') == cid:
            res['ack_lat'].append(time.perf_counter() - t0)
            res['ack_samples'].append((k, res['ack_lat'][-1]))
            return True
        if kind == 'message':
            res['recv'] += 1
        elif kind == 'error':
            res['errors'].append(f'send:{frame}')
            return False


async def run_client(i, token, start_evt, stop_evt, res, args, run_id):
    uid = 900001 + i
    peer = 900001 + ((i + 1) % res['n'])
    ip = f'10.20.{i // 250}.{i % 250 + 1}'
    ws = None
    try:
        t0 = time.perf_counter()
        ws = await websockets.connect(args.uri, additional_headers={'X-Real-IP': ip},
                                      open_timeout=20, close_timeout=5, max_size=1 << 20)
        await ws.send(json.dumps({'v': 1, 'type': 'auth', 'data': {'token': token}}))
        frame = json.loads(await asyncio.wait_for(ws.recv(), 20))
        if frame.get('type') != 'auth_ok':
            res['auth_fail'] += 1
            res['errors'].append(f'auth:{frame}')
            await ws.close()
            return
        res['auth_lat'].append(time.perf_counter() - t0)
        res['connected'] += 1
    except Exception as exc:  # noqa: BLE001
        res['connect_fail'] += 1
        res['errors'].append(f'connect:{type(exc).__name__}:{exc}')
        if ws is not None:
            await ws.close()
        return

    await start_evt.wait()
    try:
        if args.interval > 0 and i < (args.senders or res['n']):
            # steady:按序号把发送时刻摊平到 interval 窗口内
            await asyncio.sleep((i / max(1, args.senders or res['n'])) * args.interval)
            end = time.perf_counter() + args.duration
            k = 0
            while not stop_evt.is_set() and time.perf_counter() < end:
                await send_one(ws, res, uid, k, peer, run_id)
                k += 1
                await asyncio.sleep(args.interval)
        elif args.interval > 0:
            while not stop_evt.is_set():
                await asyncio.sleep(1)
        else:
            await asyncio.sleep((i % 50) * 0.01)
            for k in range(2):
                await send_one(ws, res, uid, k, peer, run_id)
                await asyncio.sleep(0.05)
            # burst 模式:保持连接,测稳态内存
            end = time.perf_counter() + args.hold
            last_ping = 0.0
            while not stop_evt.is_set() and time.perf_counter() < end:
                try:
                    frame = json.loads(await asyncio.wait_for(ws.recv(), 2.0))
                    if frame.get('type') == 'message':
                        res['recv'] += 1
                    elif frame.get('type') == 'pong':
                        sent = res['ping_sent'].pop(i, None)
                        if sent is not None:
                            res['pong_lat'].append(time.perf_counter() - sent)
                except asyncio.TimeoutError:
                    pass
                now = time.perf_counter()
                if i % 10 == 0 and now - last_ping > 10:
                    last_ping = now
                    res['ping_sent'][i] = now
                    await ws.send(json.dumps({'v': 1, 'type': 'ping', 'id': f'p-{uid}'}))
    except Exception as exc:  # noqa: BLE001
        res['closed_early'] += 1
        res['errors'].append(f'hold:{type(exc).__name__}:{exc}')
    finally:
        try:
            await ws.close()
        except Exception:
            pass


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--n', type=int, default=500)
    ap.add_argument('--hold', type=int, default=60)
    ap.add_argument('--interval', type=float, default=0)
    ap.add_argument('--duration', type=int, default=40)
    ap.add_argument('--uri', default=URI)
    ap.add_argument('--senders', type=int, default=0, help='steady 模式下只有前 N 个连接发消息,0=全部')
    ap.add_argument('--out', default='/tmp/bench_result.json')
    args = ap.parse_args()

    secret = os.environ['IM_JWT_SECRET']
    run_id = uuid.uuid4().hex[:6]
    res = {'n': args.n, 'connected': 0, 'connect_fail': 0, 'auth_fail': 0,
           'send_fail': 0, 'closed_early': 0, 'recv': 0, 'errors': [],
           'auth_lat': [], 'ack_lat': [], 'pong_lat': [], 'ping_sent': {}, 'ack_samples': []}

    tokens = [mint(900001 + i, secret) for i in range(args.n)]
    start_evt = asyncio.Event()
    stop_evt = asyncio.Event()
    t_start = time.perf_counter()

    tasks = []
    for i in range(args.n):
        tasks.append(asyncio.create_task(run_client(i, tokens[i], start_evt, stop_evt, res,
                                                    args, run_id)))
        if (i + 1) % 25 == 0:
            await asyncio.sleep(0.1)

    deadline = time.perf_counter() + 40
    while time.perf_counter() < deadline:
        if res['connected'] + res['connect_fail'] + res['auth_fail'] >= args.n:
            break
        await asyncio.sleep(0.2)
    ramp = time.perf_counter() - t_start
    print(f'ramp done in {ramp:.2f}s connected={res["connected"]} '
          f'fail={res["connect_fail"]} auth_fail={res["auth_fail"]}', flush=True)

    start_evt.set()
    if args.interval > 0:
        wait_s = args.duration + 3
    else:
        wait_s = 3 + args.hold + 3
    print(f'running {wait_s}s ...', flush=True)
    await asyncio.sleep(wait_s)
    stop_evt.set()
    await asyncio.gather(*tasks, return_exceptions=True)

    out = {
        'n': args.n,
        'mode': 'steady' if args.interval > 0 else 'burst',
        'interval': args.interval,
        'duration': args.duration,
        'ramp_seconds': round(ramp, 2),
        'connected': res['connected'],
        'connect_fail': res['connect_fail'],
        'auth_fail': res['auth_fail'],
        'send_fail': res['send_fail'],
        'closed_early': res['closed_early'],
        'recv_messages': res['recv'],
        'ack_total': len(res['ack_lat']),
        'auth_ms': summary(res['auth_lat']),
        'ack_ms': summary(res['ack_lat']),
        'ack_ms_first': summary([v for k, v in res['ack_samples'] if k == 0]),
        'ack_ms_after': summary([v for k, v in res['ack_samples'] if k > 0]),
        'ack_ms_by_wave': {str(k): summary([v for kk, v in res['ack_samples'] if kk == k]) for k in sorted({kk for kk, _ in res['ack_samples']})},
        'pong_ms': summary(res['pong_lat']),
        'errors_sample': res['errors'][:10],
        'errors_total': len(res['errors']),
    }
    with open(args.out, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())




