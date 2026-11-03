"""`perf/run.py` 的自测:纯标准库,不需要被压服务在跑。

为什么放在 `perf/` 而不是 `chatapp/`:`manage.py test` 只发现 `chatapp/` 下的用例,
压测脚本在仓库根。CI 用 `python -m unittest perf.test_run` 跑这一份。

覆盖点(都是「改错了会静默压错」的地方):
    - `--header` 解析:缺冒号 / 空头名要给清晰错误,而不是把 ``Authorization Bearer x``
      当成头名发出去;
    - 多层头合并:大小写不敏感覆盖(``--headers-file`` 里的 ``authorization``
      必须能盖掉 ``--header`` 的 ``Authorization``);
    - `build_request`:方法行、请求体、``Content-Length``、缺省 ``Content-Type``;
    - ``{i}`` 自增替换:在真实 TCP 上跑一遍最小回显服务器,确认真发出去的是
      POST + 每个账号自己的鉴权头 + 递增的请求体;
    - 结果 JSON 脱敏:头名进结果,**头的值绝不进**(结果文件会进 git)。
"""

import argparse
import asyncio
import json
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

from perf import run as perf_run


def make_args(**overrides) -> Namespace:
    """造一份与 argparse 产物同形状的参数对象(只覆盖本文件用到的字段)。

    Args:
        **overrides: 要覆盖的字段。

    Returns:
        参数命名空间。
    """
    base = dict(
        scenario="api_write",
        host="127.0.0.1",
        port=8000,
        path="/api/v1/discovery/swipe",
        method="POST",
        body='{"target_user_id": {i}, "action": "like"}',
        i_start=1,
        header=[],
        headers_file="",
        conns=2,
        dur=0.3,
        count=1,
        interval=1.0,
        tls=False,
        sni="",
        out="",
    )
    base.update(overrides)
    return Namespace(**base)


class EchoServer:
    """记录请求的最小 HTTP/1.1 服务器(keep-alive,回 200 空体)。

    只在测试里用:目的不是模拟业务,而是把客户端**真正发出去的字节**抓下来看。
    """

    def __init__(self):
        """初始化空的请求记录与原位状态。"""
        self.requests: list[tuple[str, str, dict, bytes]] = []
        self._server = None
        self.port = 0

    async def start(self) -> None:
        """监听 127.0.0.1 的随机端口。"""
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self) -> None:
        """停止监听并等待连接关闭。"""
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader, writer) -> None:
        """读一条连接上的所有请求,逐个记录并回 200。

        Args:
            reader: asyncio 流读取器。
            writer: asyncio 流写入器。
        """
        try:
            while True:
                head = await reader.readuntil(b"\r\n\r\n")
                lines = head.decode("latin-1").split("\r\n")
                method, path, _ = lines[0].split(" ")
                headers = {}
                for line in lines[1:]:
                    if not line:
                        continue
                    name, _, value = line.partition(":")
                    headers[name.strip().lower()] = value.strip()
                length = int(headers.get("content-length") or 0)
                body = await reader.readexactly(length) if length else b""
                self.requests.append((method, path, headers, body))
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            writer.close()


class HeaderParsingTests(unittest.TestCase):
    """`--header` 解析与多层合并。"""

    def test_splits_on_first_colon(self):
        self.assertEqual(perf_run.parse_header_arg("Authorization: Bearer a:b"),
                         ("Authorization", "Bearer a:b"))

    def test_rejects_missing_colon(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            perf_run.parse_header_arg("Authorization Bearer xxx")

    def test_rejects_empty_name(self):
        with self.assertRaises(argparse.ArgumentTypeError):
            perf_run.parse_header_arg(": nope")

    def test_merge_is_case_insensitive_and_last_wins(self):
        merged = perf_run.merge_headers(
            {"Accept": "*/*", "Authorization": "old"},
            {"authorization": "new", "X-Forwarded-For": "10.0.0.9"})
        self.assertEqual(merged["authorization"], "new")
        self.assertNotIn("Authorization", merged)
        self.assertEqual(merged["Accept"], "*/*")
        self.assertEqual(merged["X-Forwarded-For"], "10.0.0.9")


class RequestBuildingTests(unittest.TestCase):
    """`build_request`:方法行、请求体、长度与缺省内容类型。"""

    def test_post_body_sets_length_and_json_default(self):
        request = perf_run.build_request("POST", "/x", {"Host": "h"}, '{"a": 1}')
        self.assertTrue(request.startswith(b"POST /x HTTP/1.1\r\n"))
        self.assertIn(b"Content-Length: 8", request)
        self.assertIn(b"Content-Type: application/json", request)
        self.assertTrue(request.endswith(b'{"a": 1}'))

    def test_explicit_content_type_is_not_duplicated(self):
        request = perf_run.build_request(
            "POST", "/x",
            {"Host": "h", "content-type": "application/x-www-form-urlencoded"},
            "text=hi")
        self.assertEqual(request.lower().count(b"content-type"), 1)

    def test_get_without_body_has_no_length(self):
        request = perf_run.build_request("GET", "/x", {"Host": "h"}, "")
        self.assertNotIn(b"Content-Length", request)
        self.assertTrue(request.endswith(b"\r\n\r\n"))

    def test_counter_token_is_left_untouched_by_builder(self):
        """占位符替换在连接循环里做(用 str.replace,不能过 str.format)。"""
        request = perf_run.build_request("POST", "/x", {"Host": "h"}, '{"id": {i}}')
        self.assertIn(b'{"id": {i}}', request)


class HeaderFileTests(unittest.TestCase):
    """`--headers-file`:一行一个头集,注释与空行忽略。"""

    def test_reads_json_lines_and_skips_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "headers.jsonl"
            path.write_text(
                "# 注释行\n"
                '\n'
                '{"Authorization": "Bearer a", "X-Forwarded-For": "10.0.0.1"}\n'
                '{"Authorization": "Bearer b"}\n',
                encoding="utf-8")
            sets = perf_run.load_header_sets(str(path))
        self.assertEqual(len(sets), 2)
        self.assertEqual(sets[0]["Authorization"], "Bearer a")
        self.assertEqual(sets[1], {"Authorization": "Bearer b"})

    def test_rejects_bad_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "headers.jsonl"
            path.write_text('{"Authorization": "Bearer a"}\nnot-json\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                perf_run.load_header_sets(str(path))

    def test_rejects_non_string_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "headers.jsonl"
            path.write_text('{"Authorization": 1}\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                perf_run.load_header_sets(str(path))

    def test_rejects_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "headers.jsonl"
            path.write_text("# 全是注释\n", encoding="utf-8")
            with self.assertRaises(ValueError):
                perf_run.load_header_sets(str(path))


class BodyAndNormalizeTests(unittest.TestCase):
    """`--body @文件` 与参数归一(默认路径 / 默认方法 / 必填校验)。"""

    def test_body_at_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "body.json"
            path.write_text('{"target_user_id": {i}}', encoding="utf-8")
            self.assertEqual(perf_run.load_body(f"@{path}"), '{"target_user_id": {i}}')

    def test_body_literal_passes_through(self):
        self.assertEqual(perf_run.load_body("text=hi"), "text=hi")

    def test_missing_body_file_is_parameter_error(self):
        with self.assertRaises(ValueError):
            perf_run.load_body("@/definitely/not/here.json")

    def test_api_read_gets_default_path_and_get(self):
        args = make_args(scenario="api_read", path="", method="", body="")
        self.assertEqual(perf_run.normalize_args(args), "")
        self.assertEqual(args.path, "/api/v1/app/config")
        self.assertEqual(args.method, "GET")

    def test_api_write_requires_explicit_path(self):
        args = make_args(scenario="api_write", path="", method="")
        self.assertIn("--path", perf_run.normalize_args(args))

    def test_api_write_defaults_to_post(self):
        args = make_args(scenario="api_write", method="")
        self.assertEqual(perf_run.normalize_args(args), "")
        self.assertEqual(args.method, "POST")

    def test_unknown_method_rejected(self):
        args = make_args(method="FETCH")
        self.assertIn("--method", perf_run.normalize_args(args))


class PayloadRedactionTests(unittest.TestCase):
    """结果 JSON 的脱敏:头名留下,头的值一个都不许留下。"""

    def test_header_values_never_reach_payload(self):
        args = make_args(header=[("Authorization", "Bearer top-secret")])
        payload = perf_run.build_payload(
            args,
            [{"Authorization": "Bearer another-secret", "X-Forwarded-For": "10.0.0.1"}],
            {"rps": 1.0, "load_peak": None, "mem_peak": None},
            "2026-11-03T20:00:00+08:00")
        text = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("secret", text)
        self.assertEqual(payload["params"]["headers"],
                         {"names": ["Authorization", "X-Forwarded-For"], "sets": 1})
        self.assertTrue(payload["params"]["body_template"])
        self.assertEqual(payload["params"]["method"], "POST")

    def test_static_body_is_not_marked_as_template(self):
        args = make_args(body='{"action": "like"}')
        payload = perf_run.build_payload(args, [], {}, "2026-11-03T20:00:00+08:00")
        self.assertFalse(payload["params"]["body_template"])
        self.assertEqual(payload["params"]["body_bytes"], len('{"action": "like"}'))


class LiveWriteLoopTests(unittest.TestCase):
    """真实 TCP 上跑一遍写场景:鉴权头、方法、自增请求体都要真的发出去。"""

    def _run(self, args, header_sets):
        """起回显服务器 → 跑 run_http → 收服务器记录。

        Args:
            args: 参数命名空间。
            header_sets: 每连接一套的请求头。

        Returns:
            (压测结果, 服务器收到的请求列表)。
        """
        async def scenario():
            """搭起服务器并跑一次 HTTP 场景。"""
            server = EchoServer()
            await server.start()
            args.port = server.port
            try:
                result = await perf_run.run_http(args, header_sets)
            finally:
                await server.stop()
            return result, list(server.requests)

        return asyncio.run(scenario())

    def test_connections_rotate_header_sets_and_bodies_are_unique(self):
        args = make_args(conns=2, dur=0.3)
        header_sets = [
            {"Authorization": "Bearer token-a", "X-Forwarded-For": "10.0.0.1"},
            {"Authorization": "Bearer token-b", "X-Forwarded-For": "10.0.0.2"},
        ]
        result, requests = self._run(args, header_sets)

        self.assertGreater(len(requests), 10)
        self.assertEqual(result["requests"], len(requests))
        self.assertEqual(result["error_rate"], 0.0)
        self.assertEqual({status for status in result["codes"]}, {"200"})

        for method, path, headers, _body in requests:
            self.assertEqual(method, "POST")
            self.assertEqual(path, "/api/v1/discovery/swipe")
            self.assertIn(headers["authorization"], {"Bearer token-a", "Bearer token-b"})
            self.assertIn(headers["x-forwarded-for"], {"10.0.0.1", "10.0.0.2"})

        ids = [json.loads(body)["target_user_id"] for *_rest, body in requests]
        self.assertEqual(len(ids), len(set(ids)), "自增序号必须全局唯一,否则压的是幂等路径")
        self.assertEqual(min(ids), 1)
        self.assertEqual(sorted(ids), list(range(1, len(ids) + 1)))

        tokens = {headers["authorization"] for _m, _p, headers, _b in requests}
        self.assertEqual(tokens, {"Bearer token-a", "Bearer token-b"})

    def test_base_header_is_overridden_by_per_connection_set(self):
        args = make_args(conns=1, dur=0.2, header=[("Authorization", "Bearer base")])
        result, requests = self._run(args, [{"authorization": "Bearer per-conn"}])
        self.assertEqual(result["error_rate"], 0.0)
        self.assertEqual(requests[0][2]["authorization"], "Bearer per-conn")

    def test_static_body_is_reused_verbatim(self):
        args = make_args(conns=1, dur=0.2, body='{"action": "like"}')
        _result, requests = self._run(args, [{"Authorization": "Bearer t"}])
        self.assertTrue(all(body == b'{"action": "like"}' for *_rest, body in requests))


if __name__ == "__main__":
    unittest.main()
