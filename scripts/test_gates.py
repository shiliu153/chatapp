"""``scripts/run_gates.py`` 与 ``scripts/gates.toml`` 的自测(纯离线,临时目录造样本)。

进 CI 的 `contract` 轨。钉住三类事,每一类的两个方向都不能静默:

- **注册表**:字段齐全、id 唯一且按 POSIX 字节序排列、scope / kind 合法、命令非空。
  注册表坏掉时执行器必须退出 2(**执行器自己出错**),而不是 0(没门禁)或 1(门禁红)——
  否则人会去修错的东西。
- **执行器**:``--list`` 与 ``--dry-run`` 的条数与顺序、``python`` → ``$CHATAPP_PY`` 的替换、
  退出码 0/1/2 的口径、缺外部工具时 fail-closed、``--skip`` 只影响本地排障。
- **两边同源**(这一节存在的理由):任何一条门禁命令都**不再以字面量**出现在
  ``.github/workflows/contract.yml`` / ``scripts/verify.sh`` / ``scripts/stacks/*.sh`` 里;
  四条重活轨的 workflow 调的是同一份 ``scripts/stacks/*.sh``。
  少了这条,「收成一行」可以靠手抄同义命令骗过验收,差额过两周就长回来。

文件信息:
    文件名称          scripts/test_gates.py
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

import contextlib
import io
import json
import os
import shlex
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

from scripts import run_gates

#: 一条能跑通的最小门禁(用当前解释器打印一行,不依赖仓库里任何东西)。
GATE_OK = """
[[gate]]
id = "demo-ok"
scope = "contract"
kind = "python"
command = 'python -c "print(1)"'
reason = "自测:应当通过"
"""

#: 一条必定失败的门禁(退出码 3)。
GATE_FAIL = """
[[gate]]
id = "demo-fail"
scope = "contract"
kind = "python"
command = 'python -c "raise SystemExit(3)"'
reason = "自测:应当判红"
"""

#: 一条依赖不存在的外部工具的门禁(fail-closed 的样本)。
GATE_MISSING_TOOL = """
[[gate]]
id = "demo-tool"
scope = "contract"
kind = "shell"
requires = ["definitely-not-installed-tool"]
command = "true"
reason = "自测:缺工具必须判红"
"""


def call_main(argv: list[str]) -> tuple[int, str, str]:
    """调 ``run_gates.main`` 并收集退出码与两路输出。

    参数说明:
        argv: 命令行参数(不含程序名)。

    返回参数:
        ``(退出码, stdout, stderr)``。

    使用示例:
        ``call_main(argv)``

    备注信息:
        无特殊约束。
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = run_gates.main(argv)
    return code, out.getvalue(), err.getvalue()


class RegistryTestCase(unittest.TestCase):
    """公共脚手架:临时目录 + 写一份注册表 + 临时接管 ``$CHATAPP_PY``。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``obj = RegistryTestCase(...)``

    备注信息:
        无特殊约束。
    """

    def setUp(self):
        """建临时目录,并把 ``$CHATAPP_PY`` 指向当前解释器(让 ``python`` 门禁真能跑)。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._saved_py = os.environ.get("CHATAPP_PY")
        os.environ["CHATAPP_PY"] = sys.executable

    def tearDown(self):
        """还原环境变量并删临时目录。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        if self._saved_py is None:
            os.environ.pop("CHATAPP_PY", None)
        else:
            os.environ["CHATAPP_PY"] = self._saved_py
        self.tmp.cleanup()

    def config(self, text: str) -> Path:
        """把一份 TOML 写进临时目录并返回路径。

        参数说明:
            text: TOML 内容。

        返回参数:
            注册表路径。

        使用示例:
            ``obj.config(text)``

        备注信息:
            无特殊约束。
        """
        path = self.root / "gates.toml"
        path.write_text(text, encoding="utf-8")
        return path


class RealRegistryTests(unittest.TestCase):
    """真实注册表(``scripts/gates.toml``)的结构约束。"""

    def setUp(self):
        """读取生产注册表。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.gates = run_gates.load_registry(run_gates.DEFAULT_CONFIG)

    def test_covers_every_scope(self):
        """五个 scope 都必须有门禁 —— 空 scope 意味着那条栈其实没进注册表。

        参数说明:
            无。
        """
        self.assertEqual({gate.scope for gate in self.gates}, set(run_gates.SCOPES))

    def test_ids_unique(self):
        """id 是失败时被点名到的东西,不能重。

        参数说明:
            无。
        """
        ids = [gate.id for gate in self.gates]
        self.assertEqual(len(ids), len(set(ids)))

    def test_file_order_is_posix_sorted(self):
        """文件里的顺序必须就是 id 的 POSIX 字节序 —— 执行器按这个顺序输出。

        参数说明:
            无。
        """
        with run_gates.DEFAULT_CONFIG.open("rb") as handle:
            raw = tomllib.load(handle)
        ids = [entry["id"] for entry in raw["gate"]]
        self.assertEqual(ids, sorted(ids, key=lambda value: value.encode("utf-8")))

    def test_contract_track_absorbed_the_orphans(self):
        """第 4 节的三处「此前没有 owner / 只在一侧」必须在 contract 组里。

        参数说明:
            无。
        """
        ids = {gate.id for gate in self.gates if gate.scope == "contract"}
        self.assertIn("contract-verify-selftest", ids)  # 两边都没跑的空头 owner
        self.assertIn("contract-start-superagent-selftest", ids)  # 只有本地跑
        self.assertIn("contract-stickers", ids)  # 只有 CI 跑
        # 第 4 节之前 CI 是 19 道;收进来的净增量是 2 道(启动脚本 + verify 自测)
        self.assertGreaterEqual(len(ids), 21)

    def test_every_gate_is_well_formed(self):
        """每道门禁都要有 id / scope / kind / command / reason。

        参数说明:
            无。
        """
        for gate in self.gates:
            with self.subTest(gate=gate.id):
                self.assertTrue(gate.id)
                self.assertIn(gate.scope, run_gates.SCOPES)
                self.assertIn(gate.kind, run_gates.KINDS)
                self.assertTrue(gate.command.strip())
                self.assertTrue(gate.reason.strip())

    def test_python_gates_start_with_python(self):
        """kind = python 的命令必须以 python 开头,否则解释器替换不生效(会偷偷用系统 python)。

        参数说明:
            无。
        """
        for gate in self.gates:
            if gate.kind == "python":
                with self.subTest(gate=gate.id):
                    self.assertIn(gate.command.split()[0], run_gates.PYTHON_PREFIXES)


class RegistryErrorTests(RegistryTestCase):
    """注册表或调用方式有问题 → 退出码 2(不是 0 也不是 1)。"""

    def test_missing_file(self):
        """文件不存在。

        参数说明:
            无。
        """
        code, _, err = call_main(["--config", str(self.root / "nope.toml"), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("读不到注册表", err)

    def test_invalid_toml(self):
        """TOML 语法错误。

        参数说明:
            无。
        """
        code, _, err = call_main(["--config", str(self.config("[[gate]\n")), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("不是合法 TOML", err)

    def test_no_entries(self):
        """一个 [[gate]] 都没有 —— 空注册表会让「全绿」变成没有门禁的绿。

        参数说明:
            无。
        """
        code, _, err = call_main(["--config", str(self.config("")), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("没有任何", err)

    def test_duplicate_id(self):
        """id 重复。

        参数说明:
            无。
        """
        text = GATE_OK + GATE_OK
        code, _, err = call_main(["--config", str(self.config(text)), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("重复", err)

    def test_empty_command(self):
        """命令为空(去空白后)。

        参数说明:
            无。
        """
        text = """
[[gate]]
id = "demo-empty"
scope = "contract"
kind = "shell"
command = "   "
reason = "自测"
"""
        code, _, err = call_main(["--config", str(self.config(text)), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("command", err)

    def test_unknown_scope_in_gate(self):
        """gate 的 scope 不在允许集合里。

        参数说明:
            无。
        """
        text = GATE_OK.replace('scope = "contract"', 'scope = "nope"')
        code, _, err = call_main(["--config", str(self.config(text)), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("scope 不合法", err)

    def test_unknown_kind(self):
        """kind 只允许 python / shell。

        参数说明:
            无。
        """
        text = GATE_OK.replace('kind = "python"', 'kind = "ruby"')
        code, _, err = call_main(["--config", str(self.config(text)), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("kind 不合法", err)

    def test_python_kind_requires_python_prefix(self):
        """kind = python 但命令不是 python 开头 —— 必须报错,不能静默不替换解释器。

        参数说明:
            无。
        """
        text = GATE_OK.replace("command = 'python", "command = 'bash")
        code, _, err = call_main(["--config", str(self.config(text)), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("必须以 python 开头", err)

    def test_cwd_must_stay_inside_repo(self):
        """cwd 不许是绝对路径或跳出仓库。

        参数说明:
            无。
        """
        text = GATE_OK.replace('reason = "自测:应当通过"', 'cwd = "../.."\nreason = "自测"')
        code, _, err = call_main(["--config", str(self.config(text)), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("相对路径", err)

    def test_unknown_scope_argument(self):
        """--scope 不在允许集合里:argparse 直接退出 2。

        参数说明:
            无。
        """
        with self.assertRaises(SystemExit) as caught:
            with contextlib.redirect_stderr(io.StringIO()):
                run_gates.main(["--scope", "nope", "--list"])
        self.assertEqual(caught.exception.code, 2)

    def test_run_without_scope(self):
        """真跑必须显式指定 scope —— 不指定就等于「跑全部」,会顺手起容器 / 装依赖。

        参数说明:
            无。
        """
        code, _, err = call_main(["--config", str(self.config(GATE_OK))])
        self.assertEqual(code, 2)
        self.assertIn("--scope", err)

    def test_skip_unknown_id(self):
        """--skip 点了不存在的门禁:拼错 id 不能静默跳过别的。

        参数说明:
            无。
        """
        code, _, err = call_main(
            ["--config", str(self.config(GATE_OK)), "--scope", "contract", "--skip", "nope"]
        )
        self.assertEqual(code, 2)
        self.assertIn("不存在的门禁", err)


class BuildArgvTests(unittest.TestCase):
    """命令 → 参数向量:解释器替换与引号语义。"""

    def test_python_prefix_is_replaced(self):
        """kind = python 的开头 python 换成 $CHATAPP_PY,其余原样。

        参数说明:
            无。
        """
        gate = run_gates.Gate(
            id="x",
            scope="contract",
            kind="python",
            command="python -m unittest scripts.test_docs_lint -v",
            reason="r",
        )
        self.assertEqual(
            run_gates.build_argv(gate, "/venv/bin/python"),
            ["/venv/bin/python", "-m", "unittest", "scripts.test_docs_lint", "-v"],
        )

    def test_quoted_glob_survives(self):
        """``-p 'test_*.py'`` 的引号要由 shlex 吃掉,星号不能交给 shell 展开。

        参数说明:
            无。
        """
        gate = run_gates.Gate(
            id="x",
            scope="contract",
            kind="python",
            command="python -m unittest discover -s deploy/observability -p 'test_*.py' -v",
            reason="r",
        )
        self.assertEqual(run_gates.build_argv(gate, "python3")[-2], "test_*.py")

    def test_shell_kind_uses_bash_c(self):
        """kind = shell 整条交给 bash -c(多行脚本 / 进程替换都能用)。

        参数说明:
            无。
        """
        gate = run_gates.Gate(
            id="x", scope="contract", kind="shell", command="echo a\necho b", reason="r"
        )
        self.assertEqual(
            run_gates.build_argv(gate, "python3"), ["bash", "-c", "echo a\necho b"]
        )


class OutputTests(RegistryTestCase):
    """``--list`` / ``--dry-run``:顺序、条数、解释器。"""

    def setUp(self):
        """读真实注册表(输出口径要按生产清单验)。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        super().setUp()
        self.gates = run_gates.load_registry(run_gates.DEFAULT_CONFIG)

    def test_list_human_order_matches_registry(self):
        """``--list`` 的 id 顺序 == 注册表顺序(第 4 节验收口径)。

        参数说明:
            无。
        """
        code, out, _ = call_main(["--list"])
        self.assertEqual(code, 0)
        ids = [
            line.split()[0]
            for line in out.splitlines()
            if line.strip() and not line.startswith("    ")
        ]
        self.assertEqual(ids, [gate.id for gate in self.gates])

    def test_list_json_matches_registry(self):
        """``--list --json`` 是机器读的同一份清单(供 L4 与 lint 比对)。

        参数说明:
            无。
        """
        code, out, _ = call_main(["--list", "--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        self.assertEqual([item["id"] for item in payload], [gate.id for gate in self.gates])
        for item in payload:
            self.assertEqual(
                set(item),
                {"id", "scope", "kind", "command", "reason", "cwd", "requires", "env"},
            )

    def test_list_json_has_no_timestamp(self):
        """输出不带时间戳 / 耗时 —— 否则每次跑都算「有变化」。

        参数说明:
            无。
        """
        _, first, _ = call_main(["--list", "--json"])
        _, second, _ = call_main(["--list", "--json"])
        self.assertEqual(first, second)

    def test_dry_run_prints_one_plus_line_per_gate(self):
        """``--dry-run`` 每道门禁恰好一行以 ``+ `` 开头(自测按这个数条数)。

        参数说明:
            无。
        """
        code, out, _ = call_main(["--dry-run", "--scope", "contract"])
        self.assertEqual(code, 0)
        expected = len([gate for gate in self.gates if gate.scope == "contract"])
        self.assertEqual(
            sum(1 for line in out.splitlines() if line.startswith("+ ")), expected
        )

    def test_dry_run_count_matches_list_for_every_scope(self):
        """每个 scope 的 ``--dry-run`` 条数 == ``--list`` 条数。

        参数说明:
            无。
        """
        for scope in run_gates.SCOPES:
            with self.subTest(scope=scope):
                _, listed, _ = call_main(["--list", "--json", "--scope", scope])
                expected = len(json.loads(listed))
                _, printed, _ = call_main(["--dry-run", "--scope", scope])
                got = sum(1 for line in printed.splitlines() if line.startswith("+ "))
                self.assertEqual(got, expected)
                self.assertGreater(expected, 0)

    def test_dry_run_renders_resolved_interpreter(self):
        """``--dry-run`` 打的是**实际会执行**的命令(解释器已替换),否则老断言会形同虚设。

        参数说明:
            无。
        """
        _, out, _ = call_main(["--dry-run", "--scope", "contract"])
        expected = shlex.join([sys.executable, "scripts/sync_version.py", "--check"])
        self.assertIn(f"+ {expected}", out)

    def test_dry_run_does_not_execute(self):
        """``--dry-run`` 不执行任何命令:命令本身会写文件,文件不该出现。

        参数说明:
            无。
        """
        marker = self.root / "should-not-exist"
        gate = (
            "[[gate]]\n"
            'id = "demo-write"\n'
            'scope = "contract"\n'
            'kind = "shell"\n'
            f'command = "touch {marker.as_posix()}"\n'
            'reason = "自测"\n'
        )
        code, _, _ = call_main(["--config", str(self.config(gate)), "--dry-run"])
        self.assertEqual(code, 0)
        self.assertFalse(marker.exists())


class ExecutionTests(RegistryTestCase):
    """真跑:退出码、结果汇总、fail-closed、--skip。"""

    def test_all_green_exits_zero(self):
        """全绿 → 退出码 0,结果里 status = ok。

        参数说明:
            无。
        """
        code, out, _ = call_main(
            ["--config", str(self.config(GATE_OK)), "--scope", "contract", "--json"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(out),
            [{"id": "demo-ok", "scope": "contract", "status": "ok", "exit_code": 0}],
        )

    def test_failure_exits_one(self):
        """有门禁红 → 退出码 1,并带上真实退出码。

        参数说明:
            无。
        """
        code, out, err = call_main(
            ["--config", str(self.config(GATE_FAIL)), "--scope", "contract", "--json"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)[0]["status"], "failed")
        self.assertEqual(json.loads(out)[0]["exit_code"], 3)
        self.assertIn("demo-fail", err)

    def test_missing_tool_fails_closed(self):
        """缺外部工具 → 判红(127)并给安装命令;跳过 + WARN 会让 C5 以新形态复发。

        参数说明:
            无。
        """
        code, out, err = call_main(
            ["--config", str(self.config(GATE_MISSING_TOOL)), "--scope", "contract", "--json"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)[0]["exit_code"], 127)
        self.assertIn("sudo apt-get install -y definitely-not-installed-tool", err)

    def test_skip_marks_skipped_and_exits_zero(self):
        """``--skip`` 把门禁标成 skipped,不算红(本地排障用,CI 不用)。

        参数说明:
            无。
        """
        text = GATE_OK + GATE_FAIL
        code, out, _ = call_main(
            [
                "--config",
                str(self.config(text)),
                "--scope",
                "contract",
                "--skip",
                "demo-fail",
                "--json",
            ]
        )
        self.assertEqual(code, 0)
        statuses = {item["id"]: item["status"] for item in json.loads(out)}
        self.assertEqual(statuses, {"demo-ok": "ok", "demo-fail": "skipped"})

    def test_gate_env_does_not_leak(self):
        """门禁专用 env 只进子进程:执行器进程自己的环境不被污染。

        参数说明:
            无。
        """
        text = (
            "[[gate]]\n"
            'id = "demo-env"\n'
            'scope = "contract"\n'
            'kind = "python"\n'
            'env = { DEMO_ONLY = "1" }\n'
            "command = 'python -c \"import os, sys; sys.exit(0 if os.environ.get(\\\"DEMO_ONLY\\\") == \\\"1\\\" else 1)\"'\n"
            'reason = "自测"\n'
        )
        code, _, _ = call_main(
            ["--config", str(self.config(text)), "--scope", "contract", "--json"]
        )
        self.assertEqual(code, 0)
        self.assertNotIn("DEMO_ONLY", os.environ)


class SameSourceTests(unittest.TestCase):
    """两边同源的机械判定 —— 这一节存在的理由。

    判据不是「文件里有那一行」,而是「门禁命令**不再以字面量**出现在两边的接线文件里」:
    命令只有 ``scripts/gates.toml`` 一个家,其余地方只允许出现执行器与栈脚本的名字。
    """

    #: 第 4 节验收里点名要归零的四条字面量。
    NAMED = (
        "sync_version.py --check",
        "test_l4_intake",
        "docs_index.py --check",
        "docs_lint.py",
    )

    def setUp(self):
        """读注册表,并列出「不许出现门禁命令」的文件(contract.yml / verify.sh / stacks)。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.gates = run_gates.load_registry(run_gates.DEFAULT_CONFIG)
        self.files = [
            run_gates.ROOT / ".github" / "workflows" / "contract.yml",
            run_gates.ROOT / "scripts" / "verify.sh",
        ]
        stacks = run_gates.ROOT / "scripts" / "stacks"
        # 文件枚举一律按 POSIX 字节序(Windows 大小写不敏感、Linux 敏感,顺序会不同)。
        self.files += sorted(stacks.glob("*.sh"), key=lambda path: path.name.encode("utf-8"))

    @staticmethod
    def _collapsed(path: Path) -> str:
        """把文件内容压成单行空白,避免「跨行抄一遍」绕过字面量检查。

        参数说明:
            path: 待读文件。

        返回参数:
            空白折叠后的内容。

        使用示例:
            ``obj._collapsed(path)``

        备注信息:
            无特殊约束。
        """
        return " ".join(path.read_text(encoding="utf-8").split())

    @staticmethod
    def _needle(gate: run_gates.Gate) -> str:
        """取一道门禁的「命令字面量」用于反向断言。

        参数说明:
            gate: 门禁。

        返回参数:
            ``kind = python`` 时是去掉解释器后的命令;``kind = shell`` 时是折叠后的整条命令; ``kind = artifact`` 时返回空串 —— 它的 ``command`` 是**生成物路径**而不是命令, 同一个路径出现在 ``stacks/backend.sh`` 的生成命令里 (``manage.py spectacular --file ../docs/api/openapi.yml``)是正常的,不算抄门禁。

        使用示例:
            ``obj._needle(gate)``

        备注信息:
            无特殊约束。
        """
        if gate.kind == "artifact":
            return ""
        if gate.kind == "python":
            return " ".join(run_gates.build_argv(gate, "python")[1:])
        return " ".join(gate.command.split())

    def test_no_gate_command_literal_in_wiring(self):
        """任何门禁命令都不许以字面量出现在 contract.yml / verify.sh / stacks/*.sh。

        参数说明:
            无。
        """
        for path in self.files:
            content = self._collapsed(path)
            for gate in self.gates:
                needle = self._needle(gate)
                if not needle:
                    continue
                with self.subTest(file=path.name, gate=gate.id):
                    self.assertNotIn(
                        needle,
                        content,
                        f"{path.name} 里出现了门禁 {gate.id} 的命令字面量:门禁只能写在 gates.toml",
                    )

    def test_named_literals_are_gone(self):
        """第 4 节验收点名的四条字面量:归零。

        参数说明:
            无。
        """
        for path in self.files:
            content = self._collapsed(path)
            for needle in self.NAMED:
                with self.subTest(file=path.name, needle=needle):
                    self.assertNotIn(needle, content)

    def test_contract_workflow_has_one_executor_step(self):
        """CI 的 contract 轨只剩一个门禁 step:装工具 + 调执行器。

        参数说明:
            无。
        """
        content = (run_gates.ROOT / ".github" / "workflows" / "contract.yml").read_text(
            encoding="utf-8"
        )
        self.assertEqual(content.count("scripts/run_gates.py --scope contract"), 1)
        self.assertEqual(content.count("\n      - name:"), 2)  # 装外部工具 + 门禁注册表
        self.assertNotIn("python -m unittest", content)
        self.assertNotIn("scripts/docs_", content)

    def test_verify_sh_delegates_contract_to_executor(self):
        """本地 contract 分支调的是同一个执行器,而不是自己抄一份命令。

        参数说明:
            无。
        """
        content = (run_gates.ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
        self.assertIn("contract) run_gates contract ;;", content)
        self.assertNotIn("python -m unittest", content)

    def test_heavy_workflows_call_shared_stack_scripts(self):
        """D3-B:四条重活轨都调 ``scripts/stacks/*.sh``(本地 verify.sh 调的是同一份)。

        参数说明:
            无。
        """
        for name in ("backend", "web", "imserver", "app"):
            with self.subTest(stack=name):
                workflow = (
                    run_gates.ROOT / ".github" / "workflows" / f"{name}.yml"
                ).read_text(encoding="utf-8")
                self.assertIn(f"bash scripts/stacks/{name}.sh", workflow)

    def test_line_budgets(self):
        """§3.3 的行数预算:contract.yml ≤ 50、verify.sh ≤ 160。

        参数说明:
            无。
        """
        contract = run_gates.ROOT / ".github" / "workflows" / "contract.yml"
        verify = run_gates.ROOT / "scripts" / "verify.sh"
        self.assertLessEqual(len(contract.read_text(encoding="utf-8").splitlines()), 50)
        self.assertLessEqual(len(verify.read_text(encoding="utf-8").splitlines()), 160)


class ArtifactGateTests(RegistryTestCase):
    """``kind = "artifact"``:生成物路径 → 共享比对器(C9)。

    这一节新增的 kind 有两条判据:注册表里**确实有**这两道门禁(此前它们是
    ``stacks/*.sh`` 里的裸调用,不在清单里),以及执行器把它们拼成
    ``python scripts/lib/artifacts.py <路径>`` —— 比对语义只有那一份实现。
    """

    def setUp(self):
        """读真实注册表(artifact 门禁是生产清单的一部分)。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        super().setUp()
        self.gates = run_gates.load_registry(run_gates.DEFAULT_CONFIG)
        self.artifacts = {gate.id: gate for gate in self.gates if gate.kind == "artifact"}

    def test_both_generated_artifacts_are_registered(self):
        """两条生成物校验都在清单里,且路径指向真实文件。

        参数说明:
            无。
        """
        self.assertEqual(
            set(self.artifacts), {"backend-openapi-artifact", "web-schema-artifact"})
        self.assertEqual(self.artifacts["backend-openapi-artifact"].command,
                         "docs/api/openapi.yml")
        self.assertEqual(self.artifacts["web-schema-artifact"].command,
                         "web/src/api/schema.d.ts")
        for gate in self.artifacts.values():
            with self.subTest(gate=gate.id):
                self.assertTrue((run_gates.ROOT / gate.command).is_file(), gate.command)

    def test_argv_goes_through_the_shared_checker(self):
        """执行器不自己实现比对:拼成 ``python scripts/lib/artifacts.py <路径>``。

        参数说明:
            无。
        """
        gate = self.artifacts["backend-openapi-artifact"]
        self.assertEqual(
            run_gates.build_argv(gate, "/venv/bin/python"),
            ["/venv/bin/python", "scripts/lib/artifacts.py", "docs/api/openapi.yml"],
        )
        self.assertTrue((run_gates.ROOT / run_gates.ARTIFACT_CHECKER).is_file())

    def test_dry_run_prints_the_real_command(self):
        """``--dry-run`` 打的是真会执行的命令(不是裸路径)。

        参数说明:
            无。
        """
        _, out, _ = call_main(["--dry-run", "--scope", "backend"])
        self.assertIn("scripts/lib/artifacts.py docs/api/openapi.yml", " ".join(out.split()))

    def test_artifact_path_must_be_repo_relative(self):
        """绝对路径 / ``..`` 会让本地与 CI 比到不同文件,加载即报错(退出码 2)。

        参数说明:
            无。
        """
        for bad in ("/etc/passwd", "../outside.yml"):
            with self.subTest(command=bad):
                text = (
                    "[[gate]]\n"
                    'id = "demo-artifact"\n'
                    'scope = "contract"\n'
                    'kind = "artifact"\n'
                    f'command = "{bad}"\n'
                    'reason = "自测"\n'
                )
                code, _, err = call_main(["--config", str(self.config(text)), "--list"])
                self.assertEqual(code, 2)
                self.assertIn("生成物相对路径", err)

    def test_mismatch_turns_the_gate_red(self):
        """生成物不在 HEAD / 与 HEAD 不一致 → 该门禁红(退出码 1),不是执行器错误(2)。

        参数说明:
            无。

        备注信息:
            用一条指向**不存在**的生成物的临时门禁来验证接线:比对器会判「不在 HEAD 里」,
            既不碰真实仓库里的任何文件,又能证明 kind = artifact 真的走了共享实现。
        """
        text = (
            "[[gate]]\n"
            'id = "demo-artifact-missing"\n'
            'scope = "contract"\n'
            'kind = "artifact"\n'
            'command = "docs/does-not-exist.yml"\n'
            'reason = "自测:生成物缺失必须判红"\n'
        )
        code, out, err = call_main(
            ["--config", str(self.config(text)), "--scope", "contract", "--json"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)[0]["status"], "failed")
        self.assertIn("不在 HEAD 里", err)


if __name__ == "__main__":
    unittest.main()
