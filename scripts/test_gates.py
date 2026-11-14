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

    Args:
        argv: 命令行参数(不含程序名)。

    Returns:
        ``(退出码, stdout, stderr)``。
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = run_gates.main(argv)
    return code, out.getvalue(), err.getvalue()


class RegistryTestCase(unittest.TestCase):
    """公共脚手架:临时目录 + 写一份注册表 + 临时接管 ``$CHATAPP_PY``。"""

    def setUp(self):
        """建临时目录,并把 ``$CHATAPP_PY`` 指向当前解释器(让 ``python`` 门禁真能跑)。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._saved_py = os.environ.get("CHATAPP_PY")
        os.environ["CHATAPP_PY"] = sys.executable

    def tearDown(self):
        """还原环境变量并删临时目录。"""
        if self._saved_py is None:
            os.environ.pop("CHATAPP_PY", None)
        else:
            os.environ["CHATAPP_PY"] = self._saved_py
        self.tmp.cleanup()

    def config(self, text: str) -> Path:
        """把一份 TOML 写进临时目录并返回路径。

        Args:
            text: TOML 内容。

        Returns:
            注册表路径。
        """
        path = self.root / "gates.toml"
        path.write_text(text, encoding="utf-8")
        return path


class RealRegistryTests(unittest.TestCase):
    """真实注册表(``scripts/gates.toml``)的结构约束。"""

    def setUp(self):
        """读取生产注册表。"""
        self.gates = run_gates.load_registry(run_gates.DEFAULT_CONFIG)

    def test_covers_every_scope(self):
        """五个 scope 都必须有门禁 —— 空 scope 意味着那条栈其实没进注册表。"""
        self.assertEqual({gate.scope for gate in self.gates}, set(run_gates.SCOPES))

    def test_ids_unique(self):
        """id 是失败时被点名到的东西,不能重。"""
        ids = [gate.id for gate in self.gates]
        self.assertEqual(len(ids), len(set(ids)))

    def test_file_order_is_posix_sorted(self):
        """文件里的顺序必须就是 id 的 POSIX 字节序 —— 执行器按这个顺序输出。"""
        with run_gates.DEFAULT_CONFIG.open("rb") as handle:
            raw = tomllib.load(handle)
        ids = [entry["id"] for entry in raw["gate"]]
        self.assertEqual(ids, sorted(ids, key=lambda value: value.encode("utf-8")))

    def test_contract_track_absorbed_the_orphans(self):
        """第 4 节的三处「此前没有 owner / 只在一侧」必须在 contract 组里。"""
        ids = {gate.id for gate in self.gates if gate.scope == "contract"}
        self.assertIn("contract-verify-selftest", ids)  # 两边都没跑的空头 owner
        self.assertIn("contract-start-superagent-selftest", ids)  # 只有本地跑
        self.assertIn("contract-stickers", ids)  # 只有 CI 跑
        # 第 4 节之前 CI 是 19 道;收进来的净增量是 2 道(启动脚本 + verify 自测)
        self.assertGreaterEqual(len(ids), 21)

    def test_every_gate_is_well_formed(self):
        """每道门禁都要有 id / scope / kind / command / reason。"""
        for gate in self.gates:
            with self.subTest(gate=gate.id):
                self.assertTrue(gate.id)
                self.assertIn(gate.scope, run_gates.SCOPES)
                self.assertIn(gate.kind, run_gates.KINDS)
                self.assertTrue(gate.command.strip())
                self.assertTrue(gate.reason.strip())

    def test_python_gates_start_with_python(self):
        """kind = python 的命令必须以 python 开头,否则解释器替换不生效(会偷偷用系统 python)。"""
        for gate in self.gates:
            if gate.kind == "python":
                with self.subTest(gate=gate.id):
                    self.assertIn(gate.command.split()[0], run_gates.PYTHON_PREFIXES)


class RegistryErrorTests(RegistryTestCase):
    """注册表或调用方式有问题 → 退出码 2(不是 0 也不是 1)。"""

    def test_missing_file(self):
        """文件不存在。"""
        code, _, err = call_main(["--config", str(self.root / "nope.toml"), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("读不到注册表", err)

    def test_invalid_toml(self):
        """TOML 语法错误。"""
        code, _, err = call_main(["--config", str(self.config("[[gate]\n")), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("不是合法 TOML", err)

    def test_no_entries(self):
        """一个 [[gate]] 都没有 —— 空注册表会让「全绿」变成没有门禁的绿。"""
        code, _, err = call_main(["--config", str(self.config("")), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("没有任何", err)

    def test_duplicate_id(self):
        """id 重复。"""
        text = GATE_OK + GATE_OK
        code, _, err = call_main(["--config", str(self.config(text)), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("重复", err)

    def test_empty_command(self):
        """命令为空(去空白后)。"""
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
        """gate 的 scope 不在允许集合里。"""
        text = GATE_OK.replace('scope = "contract"', 'scope = "nope"')
        code, _, err = call_main(["--config", str(self.config(text)), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("scope 不合法", err)

    def test_unknown_kind(self):
        """kind 只允许 python / shell。"""
        text = GATE_OK.replace('kind = "python"', 'kind = "ruby"')
        code, _, err = call_main(["--config", str(self.config(text)), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("kind 不合法", err)

    def test_python_kind_requires_python_prefix(self):
        """kind = python 但命令不是 python 开头 —— 必须报错,不能静默不替换解释器。"""
        text = GATE_OK.replace("command = 'python", "command = 'bash")
        code, _, err = call_main(["--config", str(self.config(text)), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("必须以 python 开头", err)

    def test_cwd_must_stay_inside_repo(self):
        """cwd 不许是绝对路径或跳出仓库。"""
        text = GATE_OK.replace('reason = "自测:应当通过"', 'cwd = "../.."\nreason = "自测"')
        code, _, err = call_main(["--config", str(self.config(text)), "--list"])
        self.assertEqual(code, 2)
        self.assertIn("相对路径", err)

    def test_unknown_scope_argument(self):
        """--scope 不在允许集合里:argparse 直接退出 2。"""
        with self.assertRaises(SystemExit) as caught:
            with contextlib.redirect_stderr(io.StringIO()):
                run_gates.main(["--scope", "nope", "--list"])
        self.assertEqual(caught.exception.code, 2)

    def test_run_without_scope(self):
        """真跑必须显式指定 scope —— 不指定就等于「跑全部」,会顺手起容器 / 装依赖。"""
        code, _, err = call_main(["--config", str(self.config(GATE_OK))])
        self.assertEqual(code, 2)
        self.assertIn("--scope", err)

    def test_skip_unknown_id(self):
        """--skip 点了不存在的门禁:拼错 id 不能静默跳过别的。"""
        code, _, err = call_main(
            ["--config", str(self.config(GATE_OK)), "--scope", "contract", "--skip", "nope"]
        )
        self.assertEqual(code, 2)
        self.assertIn("不存在的门禁", err)


class BuildArgvTests(unittest.TestCase):
    """命令 → 参数向量:解释器替换与引号语义。"""

    def test_python_prefix_is_replaced(self):
        """kind = python 的开头 python 换成 $CHATAPP_PY,其余原样。"""
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
        """``-p 'test_*.py'`` 的引号要由 shlex 吃掉,星号不能交给 shell 展开。"""
        gate = run_gates.Gate(
            id="x",
            scope="contract",
            kind="python",
            command="python -m unittest discover -s deploy/observability -p 'test_*.py' -v",
            reason="r",
        )
        self.assertEqual(run_gates.build_argv(gate, "python3")[-2], "test_*.py")

    def test_shell_kind_uses_bash_c(self):
        """kind = shell 整条交给 bash -c(多行脚本 / 进程替换都能用)。"""
        gate = run_gates.Gate(
            id="x", scope="contract", kind="shell", command="echo a\necho b", reason="r"
        )
        self.assertEqual(
            run_gates.build_argv(gate, "python3"), ["bash", "-c", "echo a\necho b"]
        )


class OutputTests(RegistryTestCase):
    """``--list`` / ``--dry-run``:顺序、条数、解释器。"""

    def setUp(self):
        """读真实注册表(输出口径要按生产清单验)。"""
        super().setUp()
        self.gates = run_gates.load_registry(run_gates.DEFAULT_CONFIG)

    def test_list_human_order_matches_registry(self):
        """``--list`` 的 id 顺序 == 注册表顺序(第 4 节验收口径)。"""
        code, out, _ = call_main(["--list"])
        self.assertEqual(code, 0)
        ids = [
            line.split()[0]
            for line in out.splitlines()
            if line.strip() and not line.startswith("    ")
        ]
        self.assertEqual(ids, [gate.id for gate in self.gates])

    def test_list_json_matches_registry(self):
        """``--list --json`` 是机器读的同一份清单(供 L4 与 lint 比对)。"""
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
        """输出不带时间戳 / 耗时 —— 否则每次跑都算「有变化」。"""
        _, first, _ = call_main(["--list", "--json"])
        _, second, _ = call_main(["--list", "--json"])
        self.assertEqual(first, second)

    def test_dry_run_prints_one_plus_line_per_gate(self):
        """``--dry-run`` 每道门禁恰好一行以 ``+ `` 开头(自测按这个数条数)。"""
        code, out, _ = call_main(["--dry-run", "--scope", "contract"])
        self.assertEqual(code, 0)
        expected = len([gate for gate in self.gates if gate.scope == "contract"])
        self.assertEqual(
            sum(1 for line in out.splitlines() if line.startswith("+ ")), expected
        )

    def test_dry_run_count_matches_list_for_every_scope(self):
        """每个 scope 的 ``--dry-run`` 条数 == ``--list`` 条数。"""
        for scope in run_gates.SCOPES:
            with self.subTest(scope=scope):
                _, listed, _ = call_main(["--list", "--json", "--scope", scope])
                expected = len(json.loads(listed))
                _, printed, _ = call_main(["--dry-run", "--scope", scope])
                got = sum(1 for line in printed.splitlines() if line.startswith("+ "))
                self.assertEqual(got, expected)
                self.assertGreater(expected, 0)

    def test_dry_run_renders_resolved_interpreter(self):
        """``--dry-run`` 打的是**实际会执行**的命令(解释器已替换),否则老断言会形同虚设。"""
        _, out, _ = call_main(["--dry-run", "--scope", "contract"])
        expected = shlex.join([sys.executable, "scripts/sync_version.py", "--check"])
        self.assertIn(f"+ {expected}", out)

    def test_dry_run_does_not_execute(self):
        """``--dry-run`` 不执行任何命令:命令本身会写文件,文件不该出现。"""
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
        """全绿 → 退出码 0,结果里 status = ok。"""
        code, out, _ = call_main(
            ["--config", str(self.config(GATE_OK)), "--scope", "contract", "--json"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            json.loads(out),
            [{"id": "demo-ok", "scope": "contract", "status": "ok", "exit_code": 0}],
        )

    def test_failure_exits_one(self):
        """有门禁红 → 退出码 1,并带上真实退出码。"""
        code, out, err = call_main(
            ["--config", str(self.config(GATE_FAIL)), "--scope", "contract", "--json"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)[0]["status"], "failed")
        self.assertEqual(json.loads(out)[0]["exit_code"], 3)
        self.assertIn("demo-fail", err)

    def test_missing_tool_fails_closed(self):
        """缺外部工具 → 判红(127)并给安装命令;跳过 + WARN 会让 C5 以新形态复发。"""
        code, out, err = call_main(
            ["--config", str(self.config(GATE_MISSING_TOOL)), "--scope", "contract", "--json"]
        )
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out)[0]["exit_code"], 127)
        self.assertIn("sudo apt-get install -y definitely-not-installed-tool", err)

    def test_skip_marks_skipped_and_exits_zero(self):
        """``--skip`` 把门禁标成 skipped,不算红(本地排障用,CI 不用)。"""
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
        """门禁专用 env 只进子进程:执行器进程自己的环境不被污染。"""
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
        """读注册表,并列出「不许出现门禁命令」的文件(contract.yml / verify.sh / stacks)。"""
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

        Args:
            path: 待读文件。

        Returns:
            空白折叠后的内容。
        """
        return " ".join(path.read_text(encoding="utf-8").split())

    @staticmethod
    def _needle(gate: run_gates.Gate) -> str:
        """取一道门禁的「命令字面量」用于反向断言。

        Args:
            gate: 门禁。

        Returns:
            ``kind = python`` 时是去掉解释器后的命令;``kind = shell`` 时是折叠后的整条命令。
        """
        if gate.kind == "python":
            return " ".join(run_gates.build_argv(gate, "python")[1:])
        return " ".join(gate.command.split())

    def test_no_gate_command_literal_in_wiring(self):
        """任何门禁命令都不许以字面量出现在 contract.yml / verify.sh / stacks/*.sh。"""
        for path in self.files:
            content = self._collapsed(path)
            for gate in self.gates:
                with self.subTest(file=path.name, gate=gate.id):
                    self.assertNotIn(
                        self._needle(gate),
                        content,
                        f"{path.name} 里出现了门禁 {gate.id} 的命令字面量:门禁只能写在 gates.toml",
                    )

    def test_named_literals_are_gone(self):
        """第 4 节验收点名的四条字面量:归零。"""
        for path in self.files:
            content = self._collapsed(path)
            for needle in self.NAMED:
                with self.subTest(file=path.name, needle=needle):
                    self.assertNotIn(needle, content)

    def test_contract_workflow_has_one_executor_step(self):
        """CI 的 contract 轨只剩一个门禁 step:装工具 + 调执行器。"""
        content = (run_gates.ROOT / ".github" / "workflows" / "contract.yml").read_text(
            encoding="utf-8"
        )
        self.assertEqual(content.count("scripts/run_gates.py --scope contract"), 1)
        self.assertEqual(content.count("\n      - name:"), 2)  # 装外部工具 + 门禁注册表
        self.assertNotIn("python -m unittest", content)
        self.assertNotIn("scripts/docs_", content)

    def test_verify_sh_delegates_contract_to_executor(self):
        """本地 contract 分支调的是同一个执行器,而不是自己抄一份命令。"""
        content = (run_gates.ROOT / "scripts" / "verify.sh").read_text(encoding="utf-8")
        self.assertIn("contract) run_gates contract ;;", content)
        self.assertNotIn("python -m unittest", content)

    def test_heavy_workflows_call_shared_stack_scripts(self):
        """D3-B:四条重活轨都调 ``scripts/stacks/*.sh``(本地 verify.sh 调的是同一份)。"""
        for name in ("backend", "web", "imserver", "app"):
            with self.subTest(stack=name):
                workflow = (
                    run_gates.ROOT / ".github" / "workflows" / f"{name}.yml"
                ).read_text(encoding="utf-8")
                self.assertIn(f"bash scripts/stacks/{name}.sh", workflow)

    def test_line_budgets(self):
        """§3.3 的行数预算:contract.yml ≤ 50、verify.sh ≤ 160。"""
        contract = run_gates.ROOT / ".github" / "workflows" / "contract.yml"
        verify = run_gates.ROOT / "scripts" / "verify.sh"
        self.assertLessEqual(len(contract.read_text(encoding="utf-8").splitlines()), 50)
        self.assertLessEqual(len(verify.read_text(encoding="utf-8").splitlines()), 160)


if __name__ == "__main__":
    unittest.main()
