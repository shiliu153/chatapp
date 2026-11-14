"""``scripts/l4_intake.py`` 的自测(纯离线:全部输入都是 JSON 快照 / 临时目录)。

进 CI 的 `contract` 轨。L4 是**唯一会替人决定「做什么」**的一级,所以它的判定器坏掉
不能静默:多判会把假需求塞进待办(污染),少判会让真失败没人管。两类都由下面钉住。

覆盖的验收口径(设计见阶梯 spec §6.4):
    - 该开单的信号 → 开单
    - 不该开单的信号 → 不开(不含判断类:严重度不足 / 无修复版本 / 生态越白名单 / 留给人)
    - 判定失败 → 不开(fail-closed)+ 整轮标红
    - 重复失败 → 去重不重开(open 追加评论 / closed 重开)
    - 工单格式与安全边界(不 @ 任何人、正文含事实 / 验收 / 栈)

文件信息:
    文件名称          scripts/test_l4_intake.py
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

import json
import tempfile
import unittest
from pathlib import Path

from scripts import l4_intake

NOW = "2026-11-13T01:20:00Z"


def run_fixture(
    name: str,
    conclusion: str = "failure",
    sha: str = "abcdef1234567890",
    created: str = "2026-11-13T00:00:00Z",
    run_id: int = 1,
) -> dict:
    """造一条 GitHub Actions run 记录。

    参数说明:
        name: workflow 显示名。
        conclusion: run 结论。
        sha: 触发提交 SHA。
        created: 创建时间(ISO)。
        run_id: run 编号。

    返回参数:
        runs API 形状的字典。

    使用示例:
        ``run_fixture(name, conclusion, sha, created, run_id)``

    备注信息:
        无特殊约束。
    """
    return {
        "id": run_id,
        "name": name,
        "conclusion": conclusion,
        "head_sha": sha,
        "created_at": created,
        "html_url": f"https://example.invalid/runs/{run_id}",
    }


def alert_fixture(
    package: str = "vite",
    ecosystem: str = "npm",
    manifest: str = "web/package-lock.json",
    severity: str = "high",
    patched: str = "8.3.3",
    vulnerable: str = ">= 8.3.0, <= 8.3.2",
    ghsa: str = "GHSA-aaaa-bbbb-cccc",
    state: str = "open",
    dismissed: bool = False,
) -> dict:
    """造一条 Dependabot 告警记录。

    参数说明:
        package: 包名。
        ecosystem: 生态。
        manifest: 清单路径。
        severity: 严重度。
        patched: 首个修复版本;空串表示没有修复版本。
        vulnerable: 受影响区间。
        ghsa: 公告编号。
        state: 状态。
        dismissed: 是否已 dismiss。

    返回参数:
        告警 API 形状的字典。

    使用示例:
        ``alert_fixture(package, ecosystem, manifest, severity, patched, vulnerable, ghsa, state, dismissed)``

    备注信息:
        无特殊约束。
    """
    return {
        "state": state,
        "dismissed_at": "2026-11-01T00:00:00Z" if dismissed else None,
        "html_url": "https://example.invalid/alerts/1",
        "dependency": {
            "package": {"name": package, "ecosystem": ecosystem},
            "manifest_path": manifest,
        },
        "security_advisory": {
            "ghsa_id": ghsa,
            "severity": severity,
            "summary": "测试用公告",
        },
        "security_vulnerability": {
            "vulnerable_version_range": vulnerable,
            "first_patched_version": {"identifier": patched} if patched else None,
        },
    }


class VersionRangeTests(unittest.TestCase):
    """受影响区间判定:依赖信号不信任告警 state,只信「锁文件里的版本落在哪」。"""

    def test_affected_range_matches(self):
        """锁定版本落在区间内 → True。

        参数说明:
            无。
        """
        self.assertTrue(l4_intake.version_in_range("7.30.0", ">= 7.0.0, < 7.30.1"))
        self.assertTrue(l4_intake.version_in_range("8.3.2", ">= 8.3.0, <= 8.3.2"))

    def test_already_fixed_is_outside(self):
        """2026-11-12 的真实情形:告警还开着,但锁文件里早就修好了。

        参数说明:
            无。
        """
        self.assertFalse(l4_intake.version_in_range("7.30.2", ">= 7.0.0, < 7.30.1"))
        self.assertFalse(l4_intake.version_in_range("8.3.8", ">= 8.3.0, <= 8.3.2"))
        self.assertFalse(l4_intake.version_in_range("1.16.3", ">= 1.16.0, <= 1.16.1"))
        self.assertFalse(l4_intake.version_in_range("11.0.8", ">= 7.0.0, < 11.0.1"))

    def test_caret_and_tilde(self):
        """`^` / `~` 两种常用简写。

        参数说明:
            无。
        """
        self.assertTrue(l4_intake.version_in_range("1.5.0", "^1.0.0"))
        self.assertFalse(l4_intake.version_in_range("2.0.0", "^1.0.0"))
        self.assertTrue(l4_intake.version_in_range("1.2.9", "~1.2.3"))
        self.assertFalse(l4_intake.version_in_range("1.3.0", "~1.2.3"))

    def test_npm_space_separated_range(self):
        """**npm 的区间是空格分隔**(`>=8.3.0 <=8.3.2`),GitHub 公告是逗号分隔。

        参数说明:
            无。

        备注信息:
            换成 `npm audit` 做事实源后这是主路径:旧版只按逗号切,会把整串当一个比较式,
            于是判不出来(None)→ 全部不开单,机制静默失效。
        """
        self.assertTrue(l4_intake.version_in_range("8.3.2", ">=8.3.0 <=8.3.2"))
        self.assertFalse(l4_intake.version_in_range("8.3.8", ">=8.3.0 <=8.3.2"))
        self.assertTrue(l4_intake.version_in_range("7.30.0", ">=7.0.0 <7.30.1"))
        self.assertFalse(l4_intake.version_in_range("7.30.2", ">=7.0.0 <7.30.1"))

    def test_or_groups(self):
        """`||` 表示「或」。

        参数说明:
            无。
        """
        self.assertTrue(l4_intake.version_in_range("3.0.0", "< 2.0.0 || >= 3.0.0"))

    def test_unparseable_is_none(self):
        """判不出来必须是 None(调用方据此不开单),不能默认 False。

        参数说明:
            无。
        """
        self.assertIsNone(l4_intake.version_in_range("1.0.0", "weird"))
        self.assertIsNone(l4_intake.version_in_range("1.0.0", ""))
        self.assertIsNone(l4_intake.version_in_range("not-a-version", ">= 1.0.0"))


class LockedVersionTests(unittest.TestCase):
    """锁文件解析:这才是「现在还受影响吗」的事实来源。"""

    def setUp(self):
        """建一个只有锁文件的临时仓库。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "web").mkdir()
        (self.root / "chatapp").mkdir()

    def tearDown(self):
        """清理临时仓库。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp.cleanup()

    def _write_npm(self, packages: dict) -> None:
        """写一份 npm 锁文件。

        参数说明:
            packages: `packages` 字段的内容。

        返回参数:
            无返回值。

        使用示例:
            ``obj._write_npm(packages)``

        备注信息:
            无特殊约束。
        """
        (self.root / "web/package-lock.json").write_text(
            json.dumps({"lockfileVersion": 3, "packages": packages}), encoding="utf-8"
        )

    def test_npm_exact(self):
        """npm:精确键命中。

        参数说明:
            无。
        """
        self._write_npm({"node_modules/vite": {"version": "8.3.8"}})
        self.assertEqual(l4_intake.locked_version(self.root, "npm", "vite"), "8.3.8")

    def test_npm_nested_single(self):
        """npm:嵌套安装只有唯一版本时可用。

        参数说明:
            无。
        """
        self._write_npm({"node_modules/a/node_modules/vite": {"version": "8.3.8"}})
        self.assertEqual(l4_intake.locked_version(self.root, "npm", "vite"), "8.3.8")

    def test_npm_nested_ambiguous(self):
        """npm:同包多个版本 → 判不出来(None),不猜。

        参数说明:
            无。
        """
        self._write_npm(
            {
                "node_modules/a/node_modules/vite": {"version": "8.3.8"},
                "node_modules/b/node_modules/vite": {"version": "8.3.2"},
            }
        )
        self.assertIsNone(l4_intake.locked_version(self.root, "npm", "vite"))

    def test_npm_missing(self):
        """npm:锁文件里没有该包 → None。

        参数说明:
            无。
        """
        self._write_npm({"node_modules/vite": {"version": "8.3.8"}})
        self.assertIsNone(l4_intake.locked_version(self.root, "npm", "undici"))

    def test_pip_name_normalized(self):
        """pip:包名按 PEP 503 归一化(`-` / `_` 等价)。

        参数说明:
            无。
        """
        (self.root / "chatapp/requirements.lock").write_text(
            "Django==5.2.1\ntyping_extensions==4.15.0\n", encoding="utf-8"
        )
        self.assertEqual(l4_intake.locked_version(self.root, "pip", "django"), "5.2.1")
        self.assertEqual(
            l4_intake.locked_version(self.root, "pip", "typing-extensions"), "4.15.0"
        )

    def test_pip_missing_file(self):
        """pip:没有锁文件 → None。

        参数说明:
            无。
        """
        self.assertIsNone(l4_intake.locked_version(self.root, "pip", "django"))


class CiRedTests(unittest.TestCase):
    """ci-red 信号:默认分支上最新一次 push run 是红的,且该栈能自证。"""

    def _runs(self, *runs):
        """把若干 run 包成 API 响应。

        参数说明:
            *runs: run 记录。

        返回参数:
            `{"workflow_runs": [...]}`。

        使用示例:
            ``obj._runs(*runs)``

        备注信息:
            无特殊约束。
        """
        return {"workflow_runs": list(runs)}

    def test_whitelisted_red_opens_ticket(self):
        """白名单栈(backend)红 → 开单,且标题符合 `<type>(<scope>): …`。

        参数说明:
            无。
        """
        decisions, undecidable = l4_intake.decide_ci_red(
            self._runs(run_fixture("Backend (Django)")), NOW
        )
        self.assertEqual(undecidable, [])
        self.assertEqual([d.action for d in decisions], ["create"])
        self.assertRegex(decisions[0].title, r"^fix\(backend\): .+")
        self.assertIn("scripts/verify.sh backend", decisions[0].body)
        self.assertIn("`chatapp/`", decisions[0].body)

    def test_latest_run_wins(self):
        """同一 workflow 老的红、新的绿 → 不开单(最新的绿了)。

        参数说明:
            无。
        """
        runs = self._runs(
            run_fixture("Web (Vue)", conclusion="failure", created="2026-11-12T00:00:00Z"),
            run_fixture("Web (Vue)", conclusion="success", created="2026-11-13T00:00:00Z", run_id=2),
        )
        decisions, _ = l4_intake.decide_ci_red(runs, NOW)
        self.assertEqual(decisions, [])

    def test_green_opens_nothing(self):
        """全绿 → 什么都不开。

        参数说明:
            无。
        """
        decisions, undecidable = l4_intake.decide_ci_red(
            self._runs(run_fixture("Backend (Django)", conclusion="success")), NOW
        )
        self.assertEqual((decisions, undecidable), ([], []))

    def test_human_only_workflow_is_skipped(self):
        """契约轨失败横跨四栈且多属发版动作 → 明确留给人。

        参数说明:
            无。
        """
        decisions, undecidable = l4_intake.decide_ci_red(
            self._runs(run_fixture("跨栈契约")), NOW
        )
        self.assertEqual(undecidable, [])
        self.assertEqual([d.action for d in decisions], ["skip"])
        self.assertIn("留给人", decisions[0].reason)

    def test_self_workflow_never_opens_ticket(self):
        """本 workflow 自己红了不开单(防自环、防「判定器坏了就给自己开单」)。

        参数说明:
            无。
        """
        decisions, _ = l4_intake.decide_ci_red(
            self._runs(run_fixture("L4 需求自动入队")), NOW
        )
        self.assertNotIn("create", [d.action for d in decisions])

    def test_unknown_workflow_is_undecidable(self):
        """没登记的 workflow 判不出该派给谁 → fail-closed(不开单 + 标红)。

        参数说明:
            无。
        """
        decisions, undecidable = l4_intake.decide_ci_red(
            self._runs(run_fixture("某个新加的轨")), NOW
        )
        self.assertEqual(decisions, [])
        self.assertEqual(len(undecidable), 1)
        self.assertIn("没有栈映射", undecidable[0])

    def test_malformed_runs_is_undecidable(self):
        """响应形状不对 → 判不出来,不开单。

        参数说明:
            无。
        """
        decisions, undecidable = l4_intake.decide_ci_red({"oops": True}, NOW)
        self.assertEqual(decisions, [])
        self.assertTrue(undecidable)

    def test_summary_is_reused_by_main_health(self):
        """`ci-red-summary` 与 `main-health.yml` 同一个解析器(不复制扫描逻辑)。

        参数说明:
            无。
        """
        summary = l4_intake.render_ci_red_summary(
            self._runs(
                run_fixture("Backend (Django)", sha="0123456789ab"),
                run_fixture("Web (Vue)", conclusion="success", run_id=2),
            )
        )
        self.assertIn("`Backend (Django)` @ 0123456", summary)
        self.assertIn("/runs/1", summary)
        self.assertNotIn("Web (Vue)", summary)

    def test_summary_empty_when_green(self):
        """全绿时 summary 是空串(main-health 据此走「关掉告警 issue」分支)。

        参数说明:
            无。
        """
        self.assertEqual(
            l4_intake.render_ci_red_summary(
                self._runs(run_fixture("Backend (Django)", conclusion="success"))
            ),
            "",
        )


class CiRedConclusionTests(unittest.TestCase):
    """判红口径 = 结论**红集合**,不是「等于 `failure`」(#285,重开 #283)。

    旧口径只认 `failure`,于是 `cancelled` / `timed_out` / `startup_failure` /
    `action_required` / `stale` 都被静默当绿 —— 默认分支红着,却没人为它开单。
    这里每个结论都同时钉住两个入口:`red_runs()`(事实提取)与 `decide_ci_red()`(开单)。
    """

    #: 六个红结论。
    RED = ("failure", "cancelled", "timed_out", "startup_failure", "action_required", "stale")
    #: 三个不判红的结论(`skipped` 在「按改动面跑」里是正常结果)。
    GREEN = ("success", "skipped", "neutral")

    def _runs(self, conclusion, name="Backend (Django)"):
        """把一条 run 包成 API 响应。

        参数说明:
            conclusion: run 结论(可为 `None`,表示仍在跑)。
            name: workflow 显示名。

        返回参数:
            `{"workflow_runs": [...]}`。

        使用示例:
            ``obj._runs(conclusion, name)``

        备注信息:
            无特殊约束。
        """
        return {"workflow_runs": [run_fixture(name, conclusion=conclusion)]}

    def _assert_red(self, conclusion):
        """断言该结论在 `red_runs` 与 `decide_ci_red` 两处都判红。

        参数说明:
            conclusion: run 结论。

        返回参数:
            无返回值。

        使用示例:
            ``obj._assert_red(conclusion)``

        备注信息:
            无特殊约束。
        """
        runs = self._runs(conclusion)
        self.assertEqual(
            [run.get("conclusion") for run in l4_intake.red_runs(runs)],
            [conclusion],
            f"red_runs 应把 {conclusion} 判红",
        )
        decisions, undecidable = l4_intake.decide_ci_red(runs, NOW)
        self.assertEqual(undecidable, [])
        self.assertEqual([d.action for d in decisions], ["create"], f"{conclusion} 应开单")
        self.assertIn(f"`{conclusion}`", decisions[0].body)

    def _assert_not_red(self, conclusion):
        """断言该结论在 `red_runs` 与 `decide_ci_red` 两处都不判红。

        参数说明:
            conclusion: run 结论(`None` 表示仍在跑)。

        返回参数:
            无返回值。

        使用示例:
            ``obj._assert_not_red(conclusion)``

        备注信息:
            无特殊约束。
        """
        runs = self._runs(conclusion)
        self.assertEqual(l4_intake.red_runs(runs), [], f"red_runs 不该把 {conclusion} 判红")
        decisions, undecidable = l4_intake.decide_ci_red(runs, NOW)
        self.assertEqual((decisions, undecidable), ([], []), f"{conclusion} 不该开单")

    def test_failure_is_red(self):
        """`failure` 一直是红(旧口径就在这一种上)。

        参数说明:
            无。
        """
        self._assert_red("failure")

    def test_cancelled_is_red(self):
        """`cancelled`:并发组被顶 / 手动取消 → 没跑绿,判红。

        参数说明:
            无。
        """
        self._assert_red("cancelled")

    def test_timed_out_is_red(self):
        """`timed_out`:整轮超时 → 判红。

        参数说明:
            无。
        """
        self._assert_red("timed_out")

    def test_startup_failure_is_red(self):
        """`startup_failure`:workflow 文件解析失败、run 没起来 → 判红。

        参数说明:
            无。
        """
        self._assert_red("startup_failure")

    def test_action_required_is_red(self):
        """`action_required`:要人工批准才跑 → 没跑绿,判红。

        参数说明:
            无。
        """
        self._assert_red("action_required")

    def test_stale_is_red(self):
        """`stale`:排队太久被 GitHub 判废 → 判红。

        参数说明:
            无。
        """
        self._assert_red("stale")

    def test_success_is_not_red(self):
        """`success`:绿。

        参数说明:
            无。
        """
        self._assert_not_red("success")

    def test_skipped_is_not_red(self):
        """`skipped`:`ci-scope.sh` 按改动面跳过是正常结果,与 required check 语义一致。

        参数说明:
            无。
        """
        self._assert_not_red("skipped")

    def test_neutral_is_not_red(self):
        """`neutral`:不算红。

        参数说明:
            无。
        """
        self._assert_not_red("neutral")

    def test_running_conclusion_is_not_red(self):
        """`conclusion is None`(还在跑)→ 不判红,也不开单,等下一轮快照。

        参数说明:
            无。
        """
        self._assert_not_red(None)

    def test_red_set_matches_deploy_gate_complement(self):
        """红集合与 `deploy_gate.py::OK_CONCLUSIONS` 互补(同一字段两个方向,不能有缝)。

        参数说明:
            无。
        """
        from scripts import deploy_gate

        self.assertIsInstance(l4_intake.RED_CONCLUSIONS, frozenset)
        self.assertEqual(l4_intake.RED_CONCLUSIONS & deploy_gate.OK_CONCLUSIONS, set())

    def test_scan_info_counts_red_collectively(self):
        """`scan_info` 的 `red_workflows` 同口径:`cancelled` + `success` → 红 1 条。

        参数说明:
            无。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            runs = {
                "workflow_runs": [
                    run_fixture("Web (Vue)", conclusion="cancelled"),
                    run_fixture("Backend (Django)", conclusion="success", run_id=2),
                    run_fixture("App (Flutter)", conclusion=None, run_id=3),
                ]
            }
            info = l4_intake.scan_info(root, runs, [])
        self.assertEqual(info["workflows_seen"], 3)
        self.assertEqual(info["red_workflows"], 1)

    def test_summary_line_carries_conclusion(self):
        """summary 每行带结论:非 `failure` 的红要看得出红在哪。

        参数说明:
            无。
        """
        summary = l4_intake.render_ci_red_summary(
            {
                "workflow_runs": [
                    run_fixture("Backend (Django)", conclusion="cancelled", sha="0123456789ab"),
                    run_fixture("Web (Vue)", conclusion="startup_failure", run_id=2),
                    run_fixture("App (Flutter)", conclusion="success", run_id=3),
                ]
            }
        )
        lines = summary.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("结论 `cancelled`", lines[0])
        self.assertIn("结论 `startup_failure`", lines[1])
        self.assertNotIn("App (Flutter)", summary)


class DepAdvisoryTests(unittest.TestCase):
    """依赖信号:still-affected 才开单;已经修好的、判不出来的都不开。"""

    def setUp(self):
        """建临时仓库并写入 npm 锁文件(vite 已升到 8.3.8 / undici 7.30.2)。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "web").mkdir()
        (self.root / "chatapp").mkdir()
        (self.root / "web/package-lock.json").write_text(
            json.dumps(
                {
                    "lockfileVersion": 3,
                    "packages": {
                        "node_modules/vite": {"version": "8.3.8"},
                        "node_modules/undici": {"version": "7.30.2"},
                    },
                }
            ),
            encoding="utf-8",
        )
        (self.root / "chatapp/requirements.lock").write_text("Django==5.2.1\n", encoding="utf-8")

    def tearDown(self):
        """清理临时仓库。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp.cleanup()

    def test_still_affected_opens_ticket(self):
        """锁定版本仍在受影响区间 → 开单。

        参数说明:
            无。
        """
        alert = alert_fixture(package="undici", vulnerable=">= 7.0.0, < 7.31.0", patched="7.31.0")
        decisions, undecidable = l4_intake.decide_dep([alert], self.root, NOW)
        self.assertEqual(undecidable, [])
        self.assertEqual([d.action for d in decisions], ["create"])
        self.assertIn("`7.30.2`", decisions[0].body)
        self.assertIn("7.31.0", decisions[0].body)
        self.assertIn("scripts/verify.sh web", decisions[0].body)

    def test_stale_alert_is_not_a_ticket(self):
        """**关键口径**:告警还 open,但锁文件里早已修好 → 不开单。

        参数说明:
            无。

        备注信息:
            2026-11-12 实测:修复后仍有 13 条 open 告警;只信 state 会为已修好的漏洞开单。
        """
        alert = alert_fixture(package="vite", vulnerable=">= 8.3.0, <= 8.3.2", patched="8.3.3")
        decisions, undecidable = l4_intake.decide_dep([alert], self.root, NOW)
        self.assertEqual(undecidable, [])
        self.assertEqual([d.action for d in decisions], ["skip"])
        self.assertIn("告警滞后", decisions[0].reason)

    def test_low_severity_is_not_a_ticket(self):
        """低于阈值(默认 high)只记录不开单 —— 那是「值不值得修」的判断。

        参数说明:
            无。
        """
        alert = alert_fixture(
            package="vite", severity="medium", vulnerable=">= 8.3.0, <= 8.9.0", patched="8.9.1"
        )
        decisions, _ = l4_intake.decide_dep([alert], self.root, NOW)
        self.assertEqual([d.action for d in decisions], ["skip"])
        self.assertIn("低于阈值", decisions[0].reason)

    def test_no_patched_version_is_human(self):
        """没有修复版本 → 「怎么办」变成判断,留给人。

        参数说明:
            无。
        """
        alert = alert_fixture(package="vite", patched="", vulnerable=">= 8.3.0, <= 8.9.0")
        decisions, _ = l4_intake.decide_dep([alert], self.root, NOW)
        self.assertEqual([d.action for d in decisions], ["skip"])
        self.assertIn("没有修复版本", decisions[0].reason)

    def test_non_whitelisted_ecosystem_is_skipped(self):
        """docker / actions 的修复动的是 worker 不可写或必须人审的文件 → 不开单。

        参数说明:
            无。
        """
        alert = alert_fixture(
            package="nginx", ecosystem="docker", manifest="deploy/Dockerfile",
            vulnerable="< 1.31", patched="1.31",
        )
        decisions, _ = l4_intake.decide_dep([alert], self.root, NOW)
        self.assertEqual([d.action for d in decisions], ["skip"])
        self.assertIn("不在白名单", decisions[0].reason)

    def test_dismissed_alert_ignored(self):
        """已 dismiss → 连 skip 记录都不产生(不是我们的信号)。

        参数说明:
            无。
        """
        alert = alert_fixture(package="undici", vulnerable=">= 7.0.0, < 7.31.0", dismissed=True)
        decisions, undecidable = l4_intake.decide_dep([alert], self.root, NOW)
        self.assertEqual((decisions, undecidable), ([], []))

    def test_missing_lock_entry_is_undecidable(self):
        """锁文件里找不到该包 → 判不出来,不开单。

        参数说明:
            无。
        """
        alert = alert_fixture(package="left-pad", vulnerable="< 9.9.9", patched="9.9.9")
        decisions, undecidable = l4_intake.decide_dep([alert], self.root, NOW)
        self.assertEqual(decisions, [])
        self.assertEqual(len(undecidable), 1)
        self.assertIn("锁文件里找不到", undecidable[0])

    def test_pip_alert_is_out_of_whitelist(self):
        """pip 侧没有等价的本地扫描器(私有仓库上告警接口 403)→ 明确留给人,不假装覆盖。

        参数说明:
            无。
        """
        alert = alert_fixture(
            package="Django", ecosystem="pip", manifest="chatapp/requirements.txt",
            vulnerable=">= 5.0.0, < 5.2.2", patched="5.2.2",
        )
        decisions, undecidable = l4_intake.decide_dep([alert], self.root, NOW)
        self.assertEqual(undecidable, [])
        self.assertEqual([d.action for d in decisions], ["skip"])
        self.assertIn("不在白名单", decisions[0].reason)

    def test_malformed_alerts_is_undecidable(self):
        """告警响应形状不对 → 判不出来,不开单。

        参数说明:
            无。
        """
        decisions, undecidable = l4_intake.decide_dep({"oops": 1}, self.root, NOW)
        self.assertEqual(decisions, [])
        self.assertTrue(undecidable)


class NpmAuditSourceTests(unittest.TestCase):
    """`npm audit --json` → 告警记录(依赖信号的事实源)。

    换源的原因:私有仓库上 `GITHUB_TOKEN` 读 `/dependabot/alerts` 是
    **403 Resource not accessible by integration**(2026-11-12 实测),
    而 `npm audit` 用同一套公告库、直接读锁文件,任何 token 都能跑。
    """

    def _report(self, fix_version: str = "8.3.3") -> dict:
        """造一份 npm audit v2 报告(形状按真实输出,含一条字符串 via)。

        参数说明:
            fix_version: `fixAvailable.version`;空串表示「没有可用修复」(`false`)。

        返回参数:
            `npm audit --json` 形状的字典。

        使用示例:
            ``obj._report(fix_version)``

        备注信息:
            无特殊约束。
        """
        return {
            "auditReportVersion": 2,
            "vulnerabilities": {
                "vite": {
                    "name": "vite",
                    "severity": "high",
                    "isDirect": True,
                    "via": [
                        {
                            "source": 1,
                            "name": "vite",
                            "dependency": "vite",
                            "title": "vite 允许任意命令执行",
                            "url": "https://github.com/advisories/GHSA-587h-7wmj-h5pm",
                            "severity": "high",
                            "range": ">=8.3.0 <=8.3.2",
                        },
                        {
                            "source": 2,
                            "name": "vite",
                            "dependency": "vite",
                            "title": "vite 的 fs.deny 可被绕过",
                            "url": "https://github.com/advisories/GHSA-698v-4r3x-3vcv",
                            "severity": "medium",
                            "range": ">=8.3.0 <=8.3.2",
                        },
                        "some-transitive-pkg",
                    ],
                    "effects": [],
                    "range": ">=8.3.0 <=8.3.2",
                    "nodes": ["node_modules/vite"],
                    "fixAvailable": (
                        {"name": "vite", "version": fix_version, "isSemVerMajor": False}
                        if fix_version
                        else False
                    ),
                }
            },
            "metadata": {"vulnerabilities": {"high": 1, "medium": 1}},
        }

    def test_one_record_per_advisory(self):
        """一个包命中两条公告 → 两条记录(指纹按公告区分);字符串 via 被跳过。

        参数说明:
            无。
        """
        records = l4_intake.normalize_npm_audit(self._report())
        self.assertEqual(len(records), 2)
        self.assertEqual(
            sorted(r["security_advisory"]["ghsa_id"] for r in records),
            ["GHSA-587H-7WMJ-H5PM", "GHSA-698V-4R3X-3VCV"],
        )
        self.assertEqual(records[0]["dependency"]["package"]["ecosystem"], "npm")
        self.assertEqual(records[0]["dependency"]["manifest_path"], "web/package.json")
        self.assertEqual(
            records[0]["security_vulnerability"]["first_patched_version"]["identifier"],
            "8.3.3",
        )

    def test_no_fix_available_means_human(self):
        """`fixAvailable: false` → 没有修复版本 → 判定器不开单(要判断绕开还是接受风险)。

        参数说明:
            无。
        """
        records = l4_intake.normalize_npm_audit(self._report(fix_version=""))
        self.assertTrue(records)
        self.assertIsNone(records[0]["security_vulnerability"]["first_patched_version"])

    def test_empty_or_odd_report(self):
        """没有 vulnerabilities 字段时返回空列表,不炸。

        参数说明:
            无。
        """
        self.assertEqual(l4_intake.normalize_npm_audit({}), [])
        self.assertEqual(l4_intake.normalize_npm_audit({"vulnerabilities": []}), [])

    def test_end_to_end_still_affected_opens_ticket(self):
        """规整 → 判定 → 开单:锁文件里 8.3.2 仍在区间内。

        参数说明:
            无。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "web").mkdir()
            (root / "chatapp").mkdir()
            (root / "web/package-lock.json").write_text(
                json.dumps({"packages": {"node_modules/vite": {"version": "8.3.2"}}}),
                encoding="utf-8",
            )
            (root / "chatapp/requirements.lock").write_text("", encoding="utf-8")
            records = l4_intake.normalize_npm_audit(self._report())
            decisions, undecidable = l4_intake.decide_dep(records, root, NOW)
            self.assertEqual(undecidable, [])
            creates = [d for d in decisions if d.action == "create"]
            skips = [d for d in decisions if d.action == "skip"]
            # 两条公告里只有 high 那条开单;medium 那条按阈值只记录(值不值得修是判断)
            self.assertEqual(len(creates), 1)
            self.assertEqual(len(skips), 1)
            self.assertIn("GHSA-587H-7WMJ-H5PM", creates[0].title)
            self.assertRegex(creates[0].title, r"^fix\(web\): ")
            self.assertIn("npm audit --audit-level=high", creates[0].body)
            self.assertIn("低于阈值", skips[0].reason)

    def test_end_to_end_already_fixed_opens_nothing(self):
        """锁文件里升到 8.3.8 → 不在区间 → 一张都不开(与「告警滞后」同一个道理)。

        参数说明:
            无。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "web").mkdir()
            (root / "chatapp").mkdir()
            (root / "web/package-lock.json").write_text(
                json.dumps({"packages": {"node_modules/vite": {"version": "8.3.8"}}}),
                encoding="utf-8",
            )
            (root / "chatapp/requirements.lock").write_text("", encoding="utf-8")
            records = l4_intake.normalize_npm_audit(self._report())
            decisions, undecidable = l4_intake.decide_dep(records, root, NOW)
            self.assertEqual(undecidable, [])
            self.assertNotIn("create", [d.action for d in decisions])

    def test_cli_rejects_bad_input(self):
        """输入不是 audit 报告 → 退出码 2(判不出来,不是「没有漏洞」)。

        参数说明:
            无。
        """
        with tempfile.TemporaryDirectory() as tmp:
            bad = Path(tmp) / "bad.json"
            bad.write_text("{}", encoding="utf-8")
            self.assertEqual(l4_intake.main(["from-npm-audit", "--input", str(bad)]), 2)
            missing = Path(tmp) / "nope.json"
            self.assertEqual(l4_intake.main(["from-npm-audit", "--input", str(missing)]), 2)

    def test_cli_writes_records(self):
        """正常输入 → 退出码 0 并写出记录。

        参数说明:
            无。
        """
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "audit.json"
            src.write_text(json.dumps(self._report()), encoding="utf-8")
            out = Path(tmp) / "alerts.json"
            code = l4_intake.main(
                ["from-npm-audit", "--input", str(src), "--out", str(out)]
            )
            self.assertEqual(code, 0)
            self.assertEqual(len(json.loads(out.read_text(encoding="utf-8"))), 2)


class ScanInfoTests(unittest.TestCase):
    """扫描面统计:日报必须能区分「没命中」与「根本没扫」。"""

    def test_counts_are_reported(self):
        """扫了多少 workflow / 告警 / .md 都要出现在计划里。

        参数说明:
            无。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "web").mkdir()
            (root / "chatapp").mkdir()
            (root / "docs").mkdir()
            (root / "web/package-lock.json").write_text('{"packages": {}}', encoding="utf-8")
            (root / "chatapp/requirements.lock").write_text("", encoding="utf-8")
            (root / "docs/a.md").write_text("[坏](missing.md)\n", encoding="utf-8")
            (root / "docs/b.md").write_text("# 好的\n", encoding="utf-8")
            plan = l4_intake.build_plan(
                runs={"workflow_runs": [run_fixture("Backend (Django)", conclusion="success")]},
                alerts=[],
                issues=[],
                repo_root=root,
                judged_at=NOW,
                today="2026-11-13",
            )
            scan = plan["scan"]
            self.assertEqual(scan["workflows_seen"], 1)
            self.assertEqual(scan["red_workflows"], 0)
            self.assertEqual(scan["alerts_seen"], 0)
            self.assertEqual(scan["docs_markdown_files"], 2)
            self.assertEqual(scan["broken_links"], 1)
            self.assertEqual(scan["broken_files"], 1)
            self.assertIn("扫描面", l4_intake.render_plan_markdown(plan))

    def test_empty_docs_dir_is_visible(self):
        """一个 .md 都没扫到 → 数字是 0(而不是与「没有断链」混为一谈)。

        参数说明:
            无。
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "web").mkdir()
            (root / "chatapp").mkdir()
            (root / "web/package-lock.json").write_text('{"packages": {}}', encoding="utf-8")
            (root / "chatapp/requirements.lock").write_text("", encoding="utf-8")
            plan = l4_intake.build_plan(
                runs={"workflow_runs": []}, alerts=[], issues=[],
                repo_root=root, judged_at=NOW, today="2026-11-13",
            )
            self.assertEqual(plan["scan"]["docs_markdown_files"], 0)
            self.assertEqual(plan["scan"]["broken_links"], 0)

    def test_relative_root_is_supported(self):
        """`--root .`(相对路径)必须能跑。

        参数说明:
            无。

        备注信息:
            2026-11-12 真跑就崩在这里:`rglob` 给出相对路径,而 `relative_to(resolve())` 要绝对。
            —— ValueError 直接把整轮判定打成 Traceback。本地自测全用绝对临时目录,所以漏了。
        """
        import os

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "web").mkdir()
            (root / "chatapp").mkdir()
            (root / "web/package-lock.json").write_text('{"packages": {}}', encoding="utf-8")
            (root / "chatapp/requirements.lock").write_text("", encoding="utf-8")
            (root / "docs/a.md").write_text("[坏](missing.md)\n", encoding="utf-8")
            original = os.getcwd()
            try:
                os.chdir(tmp)
                plan = l4_intake.build_plan(
                    runs={"workflow_runs": []}, alerts=[], issues=[],
                    repo_root=Path("."), judged_at=NOW, today="2026-11-13",
                )
            finally:
                os.chdir(original)
            scan = plan["scan"]
            self.assertEqual(scan["docs_markdown_files"], 1)
            self.assertEqual(scan["broken_links"], 1)
            self.assertEqual(scan["docs_sample"], ["docs/a.md"])
            self.assertTrue(scan["docs_root"].endswith("docs"))


class DocsLinksTests(unittest.TestCase):
    """机械一致性信号:文档断链,按文件聚合成一张单。"""

    def setUp(self):
        """建临时仓库,含一个断链文件。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs/specs").mkdir(parents=True)
        (self.root / "docs/real.md").write_text("# 真实文件\n", encoding="utf-8")
        (self.root / "docs/specs/a.md").write_text(
            "# 标题\n\n[好的](../real.md)\n[坏的](../../missing.md)\n[外链](https://example.com)\n",
            encoding="utf-8",
        )

    def tearDown(self):
        """清理临时仓库。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp.cleanup()

    def test_broken_link_opens_one_ticket_per_file(self):
        """一个文件多处的断链 → 合成一张单(不按链接数开单)。

        参数说明:
            无。
        """
        decisions, undecidable = l4_intake.decide_docs_links(self.root, NOW)
        self.assertEqual(undecidable, [])
        self.assertEqual([d.action for d in decisions], ["create"])
        self.assertIn("docs/specs/a.md", decisions[0].title)
        self.assertIn("第 4 行", decisions[0].body)
        self.assertIn("python scripts/check_docs_links.py", decisions[0].body)

    def test_clean_docs_opens_nothing(self):
        """没有断链 → 不开单。

        参数说明:
            无。
        """
        (self.root / "docs/specs/a.md").write_text("# 标题\n\n[好的](../real.md)\n", encoding="utf-8")
        decisions, undecidable = l4_intake.decide_docs_links(self.root, NOW)
        self.assertEqual((decisions, undecidable), ([], []))

    def test_missing_docs_dir_is_undecidable(self):
        """docs/ 不存在 → 判不出来,不开单。

        参数说明:
            无。
        """
        decisions, undecidable = l4_intake.decide_docs_links(self.root / "nope", NOW)
        self.assertEqual(decisions, [])
        self.assertTrue(undecidable)


class TicketSafetyTests(unittest.TestCase):
    """工单格式与安全边界:格式给 worker 接、正文不 @ 人(否则等于绕过人工派单)。"""

    def setUp(self):
        """收集三类信号各一张单。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "web").mkdir()
        (self.root / "chatapp").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "web/package-lock.json").write_text(
            json.dumps({"packages": {"node_modules/undici": {"version": "7.30.2"}}}),
            encoding="utf-8",
        )
        (self.root / "chatapp/requirements.lock").write_text("Django==5.2.1\n", encoding="utf-8")
        (self.root / "docs/a.md").write_text("[坏的](missing.md)\n", encoding="utf-8")

        tickets = []
        tickets += l4_intake.decide_ci_red(
            {"workflow_runs": [run_fixture("Backend (Django)")]}, NOW
        )[0]
        tickets += l4_intake.decide_dep(
            [alert_fixture(package="undici", vulnerable=">= 7.0.0, < 7.31.0", patched="7.31.0")],
            self.root,
            NOW,
        )[0]
        tickets += l4_intake.decide_docs_links(self.root, NOW)[0]
        self.tickets = [t for t in tickets if t.action == "create"]

    def tearDown(self):
        """清理临时仓库。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp.cleanup()

    def test_three_signals_produce_three_tickets(self):
        """三类信号各开一张,证明自测覆盖了全部检测器。

        参数说明:
            无。
        """
        self.assertEqual(len(self.tickets), 3)
        self.assertEqual(
            sorted({t.detector for t in self.tickets}),
            [l4_intake.SIG_CI_RED, l4_intake.SIG_DEP, l4_intake.SIG_DOCS_LINKS],
        )

    def test_no_at_mentions_anywhere(self):
        """**安全红线**:正文/标题不许出现 `@xxx` —— opening body 会被当成派工源。

        参数说明:
            无。
        """
        for ticket in self.tickets:
            self.assertNotIn("@", ticket.title)
            self.assertNotIn("@", ticket.body)

    def test_mention_scrubber(self):
        """即使事实字段里带了 @,也要被抹掉。

        参数说明:
            无。
        """
        self.assertEqual(l4_intake._scrub_mentions("问 @shiliu655 一下"), "问 shiliu655 一下")

    def test_ticket_has_fingerprint_facts_acceptance_and_stack(self):
        """正文必须自带:指纹行 + 事实表 + 验收命令 + 唯一栈。

        参数说明:
            无。
        """
        for ticket in self.tickets:
            self.assertRegex(ticket.body, r"<!-- l4-fingerprint: [0-9a-f]{16} -->")
            self.assertIn("## 事实(机器生成,勿手改)", ticket.body)
            self.assertIn("## 验收", ticket.body)
            self.assertIn("## 栈", ticket.body)
            self.assertIn(l4_intake.LABEL_AUTO, ticket.labels)

    def test_docs_ticket_forbids_creating_new_docs(self):
        """断链单不许「新建文档凑链接」—— 那等于替人决定写什么。

        参数说明:
            无。
        """
        docs_ticket = [t for t in self.tickets if t.detector == l4_intake.SIG_DOCS_LINKS][0]
        self.assertIn("新建文档", docs_ticket.body)

    def test_fingerprint_is_stable_and_distinct(self):
        """指纹稳定(同一失败不变)且区分得开(不同对象不同单)。

        参数说明:
            无。
        """
        first = l4_intake.fingerprint("ci-red|Backend (Django)")
        second = l4_intake.fingerprint("ci-red|Backend (Django)")
        other = l4_intake.fingerprint("ci-red|Web (Vue)")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertEqual(len(first), 16)


class DedupAndQuotaTests(unittest.TestCase):
    """去重(同一失败不重开)与每日限额。"""

    def _decision(self, fp: str = "0123456789abcdef") -> l4_intake.Decision:
        """造一条 create 判定。

        参数说明:
            fp: 指纹。

        返回参数:
            `create` 判定。

        使用示例:
            ``obj._decision(fp)``

        备注信息:
            无特殊约束。
        """
        return l4_intake.Decision(
            action="create",
            detector=l4_intake.SIG_CI_RED,
            fingerprint=fp,
            title="fix(backend): x",
            body="正文",
            labels=["l4-auto"],
        )

    def test_open_issue_becomes_comment(self):
        """已有同名 open issue → 只追加一次命中记录,不新建。

        参数说明:
            无。
        """
        existing = {self._decision().fingerprint: {"number": 42, "state": "open", "title": "t"}}
        out = l4_intake.apply_dedup([self._decision()], existing, 0, 5, NOW)
        self.assertEqual(out[0].action, "comment")
        self.assertEqual(out[0].issue, 42)
        self.assertIn("再次命中", out[0].body)

    def test_closed_issue_is_reopened(self):
        """停过又复发的同一失败 → 重开原单,而不是新开一条(保历史)。

        参数说明:
            无。
        """
        existing = {self._decision().fingerprint: {"number": 7, "state": "closed", "title": "t"}}
        out = l4_intake.apply_dedup([self._decision()], existing, 0, 5, NOW)
        self.assertEqual(out[0].action, "reopen")
        self.assertEqual(out[0].issue, 7)

    def test_quota_defers(self):
        """当天配额用满 → 不开单(defer),但去重类的动作照做。

        参数说明:
            无。
        """
        out = l4_intake.apply_dedup([self._decision()], {}, 5, 5, NOW)
        self.assertEqual(out[0].action, "defer")
        self.assertIn("配额已满", out[0].reason)

    def test_quota_zero_blocks_everything_new(self):
        """`L4_MAX_PER_DAY=0` 是第二道刹车:今天一张都不许新建。

        参数说明:
            无。
        """
        out = l4_intake.apply_dedup([self._decision()], {}, 0, 0, NOW)
        self.assertEqual(out[0].action, "defer")

    def test_existing_fingerprint_extraction(self):
        """能从 issue 正文里认出指纹;没有指纹的 issue 被忽略。

        参数说明:
            无。
        """
        issues = [
            {"number": 1, "state": "open", "body": "<!-- l4-fingerprint: 0123456789abcdef -->"},
            {"number": 2, "state": "open", "body": "人写的单,没有指纹"},
        ]
        index = l4_intake.existing_fingerprints(issues)
        self.assertEqual(list(index), ["0123456789abcdef"])
        self.assertEqual(index["0123456789abcdef"]["number"], 1)


class PlanTests(unittest.TestCase):
    """整条 plan 流水线(判定 → 去重 → 限额 → 日报)。"""

    def setUp(self):
        """建临时仓库,造「一条红轨 + 一条断链 + 一个已修好的告警」。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "web").mkdir()
        (self.root / "chatapp").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "web/package-lock.json").write_text(
            json.dumps({"packages": {"node_modules/vite": {"version": "8.3.8"}}}),
            encoding="utf-8",
        )
        (self.root / "chatapp/requirements.lock").write_text("", encoding="utf-8")
        (self.root / "docs/a.md").write_text("[坏的](missing.md)\n", encoding="utf-8")

    def tearDown(self):
        """清理临时仓库。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp.cleanup()

    def _plan(self, **kwargs) -> dict:
        """跑一次 build_plan,默认输入见 `setUp`。

        参数说明:
            **kwargs: 覆盖默认输入。

        返回参数:
            plan 字典。

        使用示例:
            ``obj._plan(**kwargs)``

        备注信息:
            无特殊约束。
        """
        defaults = dict(
            runs={"workflow_runs": [run_fixture("Web (Vue)")]},
            alerts=[alert_fixture(package="vite", vulnerable=">= 8.3.0, <= 8.3.2")],
            issues=[],
            repo_root=self.root,
            judged_at=NOW,
            today="2026-11-13",
        )
        defaults.update(kwargs)
        return l4_intake.build_plan(**defaults)

    def test_plan_counts(self):
        """2 个真信号开单,已修好的告警被跳过。

        参数说明:
            无。
        """
        plan = self._plan()
        actions = sorted(d["action"] for d in plan["decisions"])
        self.assertEqual(actions, ["create", "create", "skip"])
        self.assertEqual(plan["summary"]["create"], 2)

    def test_disabled_gate_does_nothing(self):
        """`L4_INTAKE=off` → 空计划(总闸)。

        参数说明:
            无。
        """
        plan = self._plan(enabled=False)
        self.assertEqual(plan["decisions"], [])
        self.assertFalse(plan["enabled"])

    def test_markdown_summary_lists_decisions(self):
        """日报里能看到「开了谁 / 跳过谁 / 为什么」。

        参数说明:
            无。
        """
        markdown = l4_intake.render_plan_markdown(self._plan())
        self.assertIn("| 信号 | 动作 | 对象 | 说明 |", markdown)
        self.assertIn("create", markdown)
        self.assertIn("skip", markdown)


class GhCommandsTests(unittest.TestCase):
    """计划 → gh 命令(纯函数,不执行)。"""

    def test_create_command(self):
        """create → `gh issue create` 带标题/正文/两个标签/仓库。

        参数说明:
            无。
        """
        plan = {
            "decisions": [
                {
                    "action": "create",
                    "detector": l4_intake.SIG_CI_RED,
                    "fingerprint": "0123456789abcdef",
                    "title": "fix(backend): x",
                    "body": "正文",
                    "labels": ["l4-auto"],
                    "issue": None,
                }
            ]
        }
        commands = l4_intake.build_gh_commands(plan, "o/r")
        issue = [c for c in commands if c[0] == "issue"]
        self.assertEqual(len(issue), 1)
        self.assertEqual(issue[0][:2], ["issue", "create"])
        self.assertIn("--repo", issue[0])
        self.assertIn("o/r", issue[0])
        self.assertIn(f"{l4_intake.LABEL_PREFIX}{l4_intake.SIG_CI_RED}", issue[0])
        labels = [c for c in commands if c[0] == "label"]
        self.assertTrue(all("--force" in c for c in labels))

    def test_reopen_command(self):
        """reopen → 先 reopen 再评论。

        参数说明:
            无。
        """
        plan = {
            "decisions": [
                {
                    "action": "reopen",
                    "detector": l4_intake.SIG_DEP,
                    "fingerprint": "0123456789abcdef",
                    "title": "",
                    "body": "再次命中",
                    "labels": [],
                    "issue": 9,
                }
            ]
        }
        commands = [c for c in l4_intake.build_gh_commands(plan, "o/r") if c[0] == "issue"]
        self.assertEqual(commands[0][:3], ["issue", "reopen", "9"])
        self.assertEqual(commands[1][:3], ["issue", "comment", "9"])

    def test_no_commands_when_nothing_to_do(self):
        """只有 skip / defer 时不产生任何 gh 命令(也不建标签)。

        参数说明:
            无。
        """
        plan = {"decisions": [{"action": "skip", "detector": l4_intake.SIG_DEP}]}
        self.assertEqual(l4_intake.build_gh_commands(plan, "o/r"), [])


class CommandLineTests(unittest.TestCase):
    """CLI 面:开关、退出码、坏输入 fail-closed。"""

    def setUp(self):
        """建临时仓库与 JSON 快照。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "web").mkdir()
        (self.root / "chatapp").mkdir()
        (self.root / "docs").mkdir()
        (self.root / "web/package-lock.json").write_text('{"packages": {}}', encoding="utf-8")
        (self.root / "chatapp/requirements.lock").write_text("", encoding="utf-8")
        self.runs = self.root / "runs.json"
        self.runs.write_text(
            json.dumps({"workflow_runs": [run_fixture("Backend (Django)")]}), encoding="utf-8"
        )
        self.alerts = self.root / "alerts.json"
        self.alerts.write_text("[]", encoding="utf-8")
        self.plan = self.root / "plan.json"

    def tearDown(self):
        """清理临时仓库。

        备注信息:
            由 ``unittest`` 框架调用,不直接调用。
        """
        self.tmp.cleanup()

    def test_plan_writes_json_and_summary(self):
        """`plan` 写出计划与日报,退出码 0(判不出来才有非零)。

        参数说明:
            无。
        """
        summary = self.root / "summary.md"
        code = l4_intake.main(
            [
                "plan",
                "--runs", str(self.runs),
                "--alerts", str(self.alerts),
                "--root", str(self.root),
                "--json-out", str(self.plan),
                "--summary-out", str(summary),
                "--today", "2026-11-13",
            ]
        )
        self.assertEqual(code, 0)
        plan = json.loads(self.plan.read_text(encoding="utf-8"))
        self.assertEqual(plan["summary"]["create"], 1)
        self.assertIn("L4 需求自动入队", summary.read_text(encoding="utf-8"))

    def test_broken_input_is_fail_closed(self):
        """输入坏掉 → 一条都不开,plan 里记 undecidable(`apply` 据此把 run 标红)。

        参数说明:
            无。
        """
        bad = self.root / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        l4_intake.main(
            [
                "plan",
                "--runs", str(bad),
                "--alerts", str(self.alerts),
                "--root", str(self.root),
                "--json-out", str(self.plan),
                "--today", "2026-11-13",
            ]
        )
        plan = json.loads(self.plan.read_text(encoding="utf-8"))
        self.assertEqual([d for d in plan["decisions"] if d["action"] == "create"], [])
        self.assertTrue(plan["undecidable"])
        # 日报(唯一的人工复核入口)不能报「开了 N 张」而实际一张没开
        self.assertNotIn("create", plan["summary"])

    def test_apply_dry_run_does_not_create(self):
        """`apply --dry-run` 只打印,退出码 0。

        参数说明:
            无。
        """
        l4_intake.main(
            [
                "plan",
                "--runs", str(self.runs),
                "--alerts", str(self.alerts),
                "--root", str(self.root),
                "--json-out", str(self.plan),
                "--today", "2026-11-13",
            ]
        )
        code = l4_intake.main(
            ["apply", "--plan", str(self.plan), "--repo", "o/r", "--dry-run"]
        )
        self.assertEqual(code, 0)

    def test_undecidable_makes_apply_red(self):
        """plan 里有 undecidable → `apply` 退出码 1(整轮 run 标红,不能静默)。

        参数说明:
            无。
        """
        undecidable_plan = self.root / "undecidable.json"
        undecidable_plan.write_text(
            json.dumps({"decisions": [], "undecidable": ["ci-red: 判不出来"]}), encoding="utf-8"
        )
        code = l4_intake.main(
            ["apply", "--plan", str(undecidable_plan), "--repo", "o/r", "--dry-run"]
        )
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
