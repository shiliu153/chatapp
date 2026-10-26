"""灰度三项手测:在真实服务器上验证「单设备踢下线 / 封禁拒连 / 拉黑发送失败」。

对应核对单 ``docs/superpowers/plans/2026-10-20-self-hosted-im-rollout.md``
「隔离测试号灰度」里三个未勾选项。脚本只碰两个隔离测试号的 IM 状态,
结束时会把封禁键与黑名单还原(幂等,可反复跑)。

为什么要有这个脚本:这三项原先只能靠双端手点,既不可重复也说不清证据;
脚本把服务端契约(帧类型 / 错误码 / 关闭码)变成可断言的输出。

用法(在服务器上,复用压测的 venv,不装新依赖):

    set -a; . /www/server/imserver/imserver.env; set +a
    /root/bench-venv/bin/python imserver/scripts/verify_graylist.py \
        --uid-a 7 --uid-b 8

退出码 0 = 三项全过;非 0 = 有断言失败(逐条打印原因)。
"""

import argparse
import asyncio
import base64
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

import websockets

DEFAULT_WS = "ws://127.0.0.1:9100/im/ws"
DEFAULT_HTTP = "http://127.0.0.1:9101"


def b64url(raw: bytes) -> str:
    """无填充的 base64url 编码(JWT 用)。

    Args:
        raw: 待编码字节。

    Returns:
        不含 ``=`` 的 base64url 字符串。
    """
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def mint(uid: int, secret: str, ttl: int = 3600) -> str:
    """手工签发一枚 HS256 JWT(与 imserver 校验逻辑一致)。

    Args:
        uid: 用户 id。
        secret: ``IM_JWT_SECRET``。
        ttl: 有效期秒数。

    Returns:
        ``header.payload.signature`` 形式的 token。
    """
    now = int(time.time())
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + ttl,
               "jti": uuid.uuid4().hex[:16]}
    signing = (f"{b64url(json.dumps(header, separators=(',', ':')).encode())}."
               f"{b64url(json.dumps(payload, separators=(',', ':')).encode())}")
    signature = hmac.new(secret.encode(), signing.encode(), hashlib.sha256).digest()
    return f"{signing}.{b64url(signature)}"


class Internal:
    """HMAC 内部 API 的最小客户端(只用到 kick/unblock/blacklist)。"""

    def __init__(self, base: str, secret: str) -> None:
        """保存地址与签名密钥。

        Args:
            base: 例如 ``http://127.0.0.1:9101``。
            secret: ``IM_INTERNAL_SECRET``。
        """
        self.base = base.rstrip("/")
        self.secret = secret

    def call(self, path: str, payload: dict | None = None) -> dict:
        """调用一次内部 API。

        Args:
            path: 以 ``/internal/`` 开头的路径。
            payload: JSON 请求体;``None`` 表示 GET。

        Returns:
            解析后的 JSON 响应。

        Raises:
            urllib.error.HTTPError: 非 2xx 时抛出。
        """
        method = "POST" if payload is not None else "GET"
        body = "" if payload is None else json.dumps(
            payload, ensure_ascii=False, separators=(",", ":"))
        timestamp = str(int(time.time()))
        signature = hmac.new(
            self.secret.encode(),
            f"{timestamp}\n{method}\n{path}\n{body}".encode(),
            hashlib.sha256,
        ).hexdigest()
        request = urllib.request.Request(
            self.base + path,
            data=body.encode() if method == "POST" else None,
            method=method,
            headers={
                "Content-Type": "application/json",
                "X-IM-Timestamp": timestamp,
                "X-IM-Signature": signature,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")
            raise RuntimeError(f"{path} 返回 HTTP {exc.code}: {detail}") from exc


def close_code(exc: BaseException) -> int | None:
    """从 websockets 的关闭异常里取关闭码。

    Args:
        exc: ``ConnectionClosed`` 或其子类实例。

    Returns:
        关闭码;取不到时为 ``None``。
    """
    rcvd = getattr(exc, "rcvd", None)
    code = getattr(rcvd, "code", None)
    if code is None:
        code = getattr(exc, "code", None)
    return code


async def recv_frame(ws, timeout: float = 5.0) -> dict:
    """读一帧;连接被关闭时返回 ``{"type": "closed", "code": ...}``。

    Args:
        ws: 已连接的 WebSocket。
        timeout: 单帧等待秒数。

    Returns:
        解析后的帧,或关闭事件的占位字典。
    """
    try:
        return json.loads(await asyncio.wait_for(ws.recv(), timeout))
    except asyncio.TimeoutError:
        return {"type": "timeout"}
    except websockets.exceptions.ConnectionClosed as exc:
        return {"type": "closed", "code": close_code(exc)}


async def wait_frame(ws, want: str, timeout: float = 5.0) -> dict:
    """读到 ``want`` 类型的帧为止(丢弃中间帧)。

    Args:
        ws: 已连接的 WebSocket。
        want: 期望的 ``type``。
        timeout: 总等待秒数。

    Returns:
        匹配的帧;期间连接关闭则返回关闭占位帧。
    """
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return {"type": "timeout"}
        frame = await recv_frame(ws, left)
        if frame["type"] in (want, "closed", "timeout"):
            return frame


async def wait_close(ws, timeout: float = 5.0) -> int | None:
    """等服务端主动关闭连接,返回关闭码。

    Args:
        ws: 已连接的 WebSocket。
        timeout: 等待秒数。

    Returns:
        关闭码;超时返回 ``None``。
    """
    deadline = time.monotonic() + timeout
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            return None
        frame = await recv_frame(ws, left)
        if frame["type"] == "closed":
            return frame["code"]


async def auth(uid: int, ws_url: str, jwt_secret: str, timeout: float = 5.0):
    """建连并完成 auth 首帧。

    Args:
        uid: 用户 id。
        ws_url: WS 地址。
        jwt_secret: ``IM_JWT_SECRET``。
        timeout: 握手与首帧的超时秒数。

    Returns:
        ``(ws, frame, close_code)``:成功时 ``ws`` 非空、``frame`` 为 ``auth_ok``;
        被拒时 ``ws`` 为 ``None``、``frame`` 为 ``error`` 帧、``close_code`` 为服务端关闭码。
    """
    ws = await websockets.connect(ws_url, open_timeout=timeout)
    await ws.send(json.dumps({"v": 1, "type": "auth",
                              "data": {"token": mint(uid, jwt_secret)}}))
    deadline = time.monotonic() + timeout
    frame = {"type": "timeout"}
    while True:
        left = deadline - time.monotonic()
        if left <= 0:
            break
        frame = await recv_frame(ws, left)
        if frame["type"] in ("auth_ok", "error", "closed", "timeout"):
            break
    if frame["type"] == "auth_ok":
        return ws, frame, None
    code = frame.get("code") if frame["type"] == "closed" else await wait_close(ws, timeout)
    try:
        await ws.close()
    except Exception:
        pass
    return None, frame, code


async def send_text(ws, to_uid: int, text: str, cid: str) -> None:
    """发一条文本消息帧。

    Args:
        ws: 已鉴权的连接。
        to_uid: 接收方 id。
        text: 正文。
        cid: ``client_msg_id``(同时作为帧 id)。
    """
    await ws.send(json.dumps({"v": 1, "type": "send", "id": cid,
                              "data": {"to": f"u{to_uid}", "text": text,
                                       "client_msg_id": cid}}))


class Report:
    """收集断言结果并统一输出。"""

    def __init__(self) -> None:
        """初始化空结果集。"""
        self.rows: list[tuple[bool, str, str]] = []

    def check(self, ok: bool, title: str, detail: str) -> bool:
        """记录一条断言。

        Args:
            ok: 是否通过。
            title: 断言标题。
            detail: 证据(实际观测到的值)。

        Returns:
            原样返回 ``ok``,方便 ``if not report.check(...)`` 串联。
        """
        self.rows.append((ok, title, detail))
        print(f"  {'PASS' if ok else 'FAIL'}  {title}  |  {detail}", flush=True)
        return ok

    def summary(self) -> int:
        """打印汇总并返回退出码。

        Returns:
            全部通过为 0,否则为失败条数。
        """
        failed = [row for row in self.rows if not row[0]]
        print()
        print(f"共 {len(self.rows)} 条断言,通过 {len(self.rows) - len(failed)},"
              f"失败 {len(failed)}")
        for _, title, detail in failed:
            print(f"  - {title}: {detail}")
        return len(failed)


async def case_multi_device(uid: int, ws_url: str, jwt_secret: str,
                            report: Report) -> None:
    """用例 1:同账号第二处登录,第一处被踢并强退。

    Args:
        uid: 测试号 id。
        ws_url: WS 地址。
        jwt_secret: JWT 密钥。
        report: 断言收集器。
    """
    print(f"\n[1/3] 单设备互踢 (uid={uid})")
    first, frame, _ = await auth(uid, ws_url, jwt_secret)
    if not report.check(first is not None, "第一处登录成功",
                        json.dumps(frame.get("data"), ensure_ascii=False)):
        return
    second, frame2, _ = await auth(uid, ws_url, jwt_secret)
    if not report.check(second is not None, "第二处登录成功",
                        json.dumps(frame2.get("data"), ensure_ascii=False)):
        await first.close()
        return

    kicked = await wait_frame(first, "kicked")
    report.check(kicked["type"] == "kicked", "第一处收到 kicked 帧",
                 f"type={kicked['type']} data={kicked.get('data')}")
    report.check(kicked.get("data", {}).get("reason") == "multi_device",
                 "踢人原因 = multi_device", f"reason={kicked.get('data', {}).get('reason')}")
    code = await wait_close(first)
    report.check(code == 4001, "第一处被服务端关闭(code=4001)", f"close={code}")

    await second.send(json.dumps({"v": 1, "type": "ping"}))
    pong = await wait_frame(second, "pong")
    report.check(pong["type"] == "pong", "第二处连接仍然可用", f"type={pong['type']}")
    await second.close()


async def case_ban(uid: int, ws_url: str, jwt_secret: str, internal: Internal,
                   report: Report) -> None:
    """用例 2:封禁后踢下线并拒连,解封后恢复。

    Args:
        uid: 测试号 id。
        ws_url: WS 地址。
        jwt_secret: JWT 密钥。
        internal: 内部 API 客户端。
        report: 断言收集器。
    """
    print(f"\n[2/3] 封禁拒连 (uid={uid})")
    online, frame, _ = await auth(uid, ws_url, jwt_secret)
    if not report.check(online is not None, "封禁前可登录",
                        json.dumps(frame.get("data"), ensure_ascii=False)):
        return

    internal.call("/internal/kick", {"uid": uid, "block": True})
    kicked = await wait_frame(online, "kicked")
    report.check(kicked["type"] == "kicked" and
                 kicked.get("data", {}).get("reason") == "banned",
                 "在线连接收到 kicked(banned)",
                 f"type={kicked['type']} reason={kicked.get('data', {}).get('reason')}")
    report.check(await wait_close(online) == 4001, "在线连接被关闭(code=4001)", "")

    denied, frame, code = await auth(uid, ws_url, jwt_secret)
    report.check(denied is None and frame.get("type") == "error" and
                 frame.get("data", {}).get("code") == 40301,
                 "封禁期间重连被拒(error 40301)",
                 f"type={frame.get('type')} code={frame.get('data', {}).get('code')}")
    report.check(code == 4003, "拒连后服务端关闭(code=4003)", f"close={code}")

    internal.call("/internal/unblock", {"uid": uid})
    restored, frame, _ = await auth(uid, ws_url, jwt_secret)
    report.check(restored is not None, "解封后可重新登录",
                 json.dumps(frame.get("data"), ensure_ascii=False))
    if restored is not None:
        await restored.close()


async def case_blacklist(owner: int, peer: int, ws_url: str, jwt_secret: str,
                         internal: Internal, report: Report) -> None:
    """用例 3:拉黑后发送失败,解除后恢复。

    Args:
        owner: 拉黑方 id。
        peer: 被拉黑方 id。
        ws_url: WS 地址。
        jwt_secret: JWT 密钥。
        internal: 内部 API 客户端。
        report: 断言收集器。
    """
    print(f"\n[3/3] 拉黑拦截 (uid {owner} -> {peer})")
    a, frame_a, _ = await auth(owner, ws_url, jwt_secret)
    b, frame_b, _ = await auth(peer, ws_url, jwt_secret)
    if not report.check(a is not None and b is not None, "双方在线",
                        f"a={frame_a.get('type')} b={frame_b.get('type')}"):
        return

    run = uuid.uuid4().hex[:8]
    internal.call("/internal/blacklist", {"owner": owner, "peer": peer, "action": "add"})
    await send_text(a, peer, f"graylist blocked {run}", f"{run}-blocked")
    error = await wait_frame(a, "error")
    report.check(error.get("data", {}).get("code") == 40302,
                 "拉黑后发送返回 error 40302",
                 f"code={error.get('data', {}).get('code')} msg={error.get('data', {}).get('message')}")
    silent = await wait_frame(b, "message", timeout=1.0)
    report.check(silent["type"] == "timeout", "被拉黑方没有收到该消息",
                 f"type={silent['type']}")

    internal.call("/internal/blacklist", {"owner": owner, "peer": peer, "action": "remove"})
    await send_text(a, peer, f"graylist after-remove {run}", f"{run}-after")
    ack = await wait_frame(a, "ack")
    report.check(ack.get("type") == "ack" and ack.get("id") == f"{run}-after",
                 "解除拉黑后发送成功(ack)", f"type={ack.get('type')} id={ack.get('id')}")
    delivered = await wait_frame(b, "message")
    report.check(delivered.get("type") == "message" and
                 delivered.get("data", {}).get("text") == f"graylist after-remove {run}",
                 "对端收到该消息",
                 f"type={delivered.get('type')} text={delivered.get('data', {}).get('text')}")
    await a.close()
    await b.close()


def reset_state(uid_a: int, uid_b: int, internal: Internal) -> None:
    """把两个测试号的封禁键与双向黑名单清干净(幂等)。

    Args:
        uid_a: 测试号 A。
        uid_b: 测试号 B。
        internal: 内部 API 客户端。
    """
    for uid in (uid_a, uid_b):
        try:
            internal.call("/internal/unblock", {"uid": uid})
        except Exception as exc:  # 清理失败不应掩盖用例结果
            print(f"  warn: unblock {uid} 失败 {exc}", flush=True)
    for owner, peer in ((uid_a, uid_b), (uid_b, uid_a)):
        try:
            internal.call("/internal/blacklist",
                          {"owner": owner, "peer": peer, "action": "remove"})
        except Exception as exc:
            print(f"  warn: blacklist remove {owner}->{peer} 失败 {exc}", flush=True)


async def main() -> int:
    """依次跑三个用例并返回退出码。

    Returns:
        0 表示全部通过。
    """
    parser = argparse.ArgumentParser(description="自建 IM 灰度三项手测")
    parser.add_argument("--uid-a", type=int, default=7)
    parser.add_argument("--uid-b", type=int, default=8)
    parser.add_argument("--ws", default=os.getenv("IM_TEST_WS", DEFAULT_WS))
    parser.add_argument("--http", default=os.getenv("IM_TEST_HTTP", DEFAULT_HTTP))
    parser.add_argument("--jwt-secret", default=os.getenv("IM_JWT_SECRET", ""))
    parser.add_argument("--internal-secret", default=os.getenv("IM_INTERNAL_SECRET", ""))
    parser.add_argument("--only", choices=("all", "multi", "ban", "blacklist"),
                        default="all", help="只跑某一个用例(排障用)")
    args = parser.parse_args()

    if not args.jwt_secret or not args.internal_secret:
        print("缺少 IM_JWT_SECRET / IM_INTERNAL_SECRET(先 source imserver.env)")
        return 2
    if args.uid_a == args.uid_b:
        print("--uid-a 与 --uid-b 不能相同")
        return 2

    internal = Internal(args.http, args.internal_secret)
    report = Report()

    reset_state(args.uid_a, args.uid_b, internal)
    try:
        if args.only in ("all", "multi"):
            await case_multi_device(args.uid_a, args.ws, args.jwt_secret, report)
        if args.only in ("all", "ban"):
            await case_ban(args.uid_b, args.ws, args.jwt_secret, internal, report)
        if args.only in ("all", "blacklist"):
            await case_blacklist(args.uid_a, args.uid_b, args.ws, args.jwt_secret,
                                 internal, report)
    finally:
        reset_state(args.uid_a, args.uid_b, internal)

    return report.summary()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
