"""``scripts/l4_intake.py`` 的自测(纯离线:全部输入都是 JSON 快照 / 临时目录)。

进 CI 的 `contract` 轨。L4 是**唯一会替人决定「做什么」**的一级,所以它的判定器坏掉
不能静默:多判会把假需求塞进待办(污染),少判会让真失败没人管。两类都由下面钉住。

覆盖的验收口径(设计见阶梯 spec §6.4):
    - 该开单的信号 → 开单
    - 不该开单的信号 → 不开(不含判断类:严重度不足 / 无修复版本 / 生态越白名单 / 留给人)
    - 判定失败 → 不开(fail-closed)+ 整轮标红
    - 重复失败 → 去重不重开(open 追加评论 / closed 重开)
    - 工单格式与安全边界(不 @ 任何人、正文含事实 / 验收 / 栈)
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

    Args:
        name: workflow 显示名。
        conclusion: run 结论。
        sha: 触发提交 SHA。
        created: 创建时间(ISO)。
        run_id: run 编号。

    Returns:
        runs API 形状的字典。
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

    Args:
        package: 包名。
        ecosystem: 生态。
        manifest: 清单路径。
        severity: 严重度。
        patched: 首个修复版本;空串表示没有修复版本。
        vulnerable: 受影响区间。
        ghsa: 公告编号。
        state: 状态。
        dismissed: 是否已 dismiss。

    Returns:
        告警 API 形状的字典。
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
        """锁定版本落在区间内 → True。"""
        self.assertTrue(l4_intake.version_in_range("7.30.0", ">= 7.0.0, < 7.30.1"))
        self.assertTrue(l4_intake.version_in_range("8.3.2", ">= 8.3.0, <= 8.3.2"))

    def test_already_fixed_is_outside(self):
        """2026-11-12 的真实情形:告警还开着,但锁文件里早就修好了。"""
        self.assertFalse(l4_intake.version_in_range("7.30.2", ">= 7.0.0, < 7.30.1"))
        self.assertFalse(l4_intake.version_in_range("8.3.8", ">= 8.3.0, <= 8.3.2"))
        self.assertFalse(l4_intake.version_in_range("1.16.3", ">= 1.16.0, <= 1.16.1"))
        self.assertFalse(l4_intake.version_in_range("11.0.8", ">= 7.0.0, < 11.0.1"))

    def test_caret_and_tilde(self):
        """`^` / `~` 两种常用简写。"""
        self.assertTrue(l4_intake.version_in_range("1.5.0", "^1.0.0"))
        self.assertFalse(l4_intake.version_in_range("2.0.0", "^1.0.0"))
        self.assertTrue(l4_intake.version_in_range("1.2.9", "~1.2.3"))
        self.assertFalse(l4_intake.version_in_range("1.3.0", "~1.2.3"))

    def test_or_groups(self):
        """`||` 表示「或」。"""
        self.assertTrue(l4_intake.version_in_range("3.0.0", "< 2.0.0 || >= 3.0.0"))

    def test_unparseable_is_none(self):
        """判不出来必须是 None(调用方据此不开单),不能默认 False。"""
        self.assertIsNone(l4_intake.version_in_range("1.0.0", "weird"))
        self.assertIsNone(l4_intake.version_in_range("1.0.0", ""))
        self.assertIsNone(l4_intake.version_in_range("not-a-version", ">= 1.0.0"))


class LockedVersionTests(unittest.TestCase):
    """锁文件解析:这才是「现在还受影响吗」的事实来源。"""

    def setUp(self):
        """建一个只有锁文件的临时仓库。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "web").mkdir()
        (self.root / "chatapp").mkdir()

    def tearDown(self):
        """清理临时仓库。"""
        self.tmp.cleanup()

    def _write_npm(self, packages: dict) -> None:
        """写一份 npm 锁文件。

        Args:
            packages: `packages` 字段的内容。
        """
        (self.root / "web/package-lock.json").write_text(
            json.dumps({"lockfileVersion": 3, "packages": packages}), encoding="utf-8"
        )

    def test_npm_exact(self):
        """npm:精确键命中。"""
        self._write_npm({"node_modules/vite": {"version": "8.3.8"}})
        self.assertEqual(l4_intake.locked_version(self.root, "npm", "vite"), "8.3.8")

    def test_npm_nested_single(self):
        """npm:嵌套安装只有唯一版本时可用。"""
        self._write_npm({"node_modules/a/node_modules/vite": {"version": "8.3.8"}})
        self.assertEqual(l4_intake.locked_version(self.root, "npm", "vite"), "8.3.8")

    def test_npm_nested_ambiguous(self):
        """npm:同包多个版本 → 判不出来(None),不猜。"""
        self._write_npm(
            {
                "node_modules/a/node_modules/vite": {"version": "8.3.8"},
                "node_modules/b/node_modules/vite": {"version": "8.3.2"},
            }
        )
        self.assertIsNone(l4_intake.locked_version(self.root, "npm", "vite"))

    def test_npm_missing(self):
        """npm:锁文件里没有该包 → None。"""
        self._write_npm({"node_modules/vite": {"version": "8.3.8"}})
        self.assertIsNone(l4_intake.locked_version(self.root, "npm", "undici"))

    def test_pip_name_normalized(self):
        """pip:包名按 PEP 503 归一化(`-` / `_` 等价)。"""
        (self.root / "chatapp/requirements.lock").write_text(
            "Django==5.2.1\ntyping_extensions==4.15.0\n", encoding="utf-8"
        )
        self.assertEqual(l4_intake.locked_version(self.root, "pip", "django"), "5.2.1")
        self.assertEqual(
            l4_intake.locked_version(self.root, "pip", "typing-extensions"), "4.15.0"
        )

    def test_pip_missing_file(self):
        """pip:没有锁文件 → None。"""
        self.assertIsNone(l4_intake.locked_version(self.root, "pip", "django"))


class CiRedTests(unittest.TestCase):
    """ci-red 信号:默认分支上最新一次 push run 是红的,且该栈能自证。"""

    def _runs(self, *runs):
        """把若干 run 包成 API 响应。

        Args:
            *runs: run 记录。

        Returns:
            `{"workflow_runs": [...]}`。
        """
        return {"workflow_runs": list(runs)}

    def test_whitelisted_red_opens_ticket(self):
        """白名单栈(backend)红 → 开单,且标题符合 `<type>(<scope>): …`。"""
        decisions, undecidable = l4_intake.decide_ci_red(
            self._runs(run_fixture("Backend (Django)")), NOW
        )
        self.assertEqual(undecidable, [])
        self.assertEqual([d.action for d in decisions], ["create"])
        self.assertRegex(decisions[0].title, r"^fix\(backend\): .+")
        self.assertIn("scripts/verify.sh backend", decisions[0].body)
        self.assertIn("`chatapp/`", decisions[0].body)

    def test_latest_run_wins(self):
        """同一 workflow 老的红、新的绿 → 不开单(最新的绿了)。"""
        runs = self._runs(
            run_fixture("Web (Vue)", conclusion="failure", created="2026-11-12T00:00:00Z"),
            run_fixture("Web (Vue)", conclusion="success", created="2026-11-13T00:00:00Z", run_id=2),
        )
        decisions, _ = l4_intake.decide_ci_red(runs, NOW)
        self.assertEqual(decisions, [])

    def test_green_opens_nothing(self):
        """全绿 → 什么都不开。"""
        decisions, undecidable = l4_intake.decide_ci_red(
            self._runs(run_fixture("Backend (Django)", conclusion="success")), NOW
        )
        self.assertEqual((decisions, undecidable), ([], []))

    def test_human_only_workflow_is_skipped(self):
        """契约轨失败横跨四栈且多属发版动作 → 明确留给人。"""
        decisions, undecidable = l4_intake.decide_ci_red(
            self._runs(run_fixture("跨栈契约")), NOW
        )
        self.assertEqual(undecidable, [])
        self.assertEqual([d.action for d in decisions], ["skip"])
        self.assertIn("留给人", decisions[0].reason)

    def test_self_workflow_never_opens_ticket(self):
        """本 workflow 自己红了不开单(防自环、防「判定器坏了就给自己开单」)。"""
        decisions, _ = l4_intake.decide_ci_red(
            self._runs(run_fixture("L4 需求自动入队")), NOW
        )
        self.assertNotIn("create", [d.action for d in decisions])

    def test_unknown_workflow_is_undecidable(self):
        """没登记的 workflow 判不出该派给谁 → fail-closed(不开单 + 标红)。"""
        decisions, undecidable = l4_intake.decide_ci_red(
            self._runs(run_fixture("某个新加的轨")), NOW
        )
        self.assertEqual(decisions, [])
        self.assertEqual(len(undecidable), 1)
        self.assertIn("没有栈映射", undecidable[0])

    def test_malformed_runs_is_undecidable(self):
        """响应形状不对 → 判不出来,不开单。"""
        decisions, undecidable = l4_intake.decide_ci_red({"oops": True}, NOW)
        self.assertEqual(decisions, [])
        self.assertTrue(undecidable)

    def test_summary_is_reused_by_main_health(self):
        """`ci-red-summary` 与 `main-health.yml` 同一个解析器(不复制扫描逻辑)。"""
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
        """全绿时 summary 是空串(main-health 据此走「关掉告警 issue」分支)。"""
        self.assertEqual(
            l4_intake.render_ci_red_summary(
                self._runs(run_fixture("Backend (Django)", conclusion="success"))
            ),
            "",
        )


class DepAdvisoryTests(unittest.TestCase):
    """依赖信号:still-affected 才开单;已经修好的、判不出来的都不开。"""

    def setUp(self):
        """建临时仓库并写入 npm 锁文件(vite 已升到 8.3.8 / undici 7.30.2)。"""
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
        """清理临时仓库。"""
        self.tmp.cleanup()

    def test_still_affected_opens_ticket(self):
        """锁定版本仍在受影响区间 → 开单。"""
        alert = alert_fixture(package="undici", vulnerable=">= 7.0.0, < 7.31.0", patched="7.31.0")
        decisions, undecidable = l4_intake.decide_dep([alert], self.root, NOW)
        self.assertEqual(undecidable, [])
        self.assertEqual([d.action for d in decisions], ["create"])
        self.assertIn("`7.30.2`", decisions[0].body)
        self.assertIn("7.31.0", decisions[0].body)
        self.assertIn("scripts/verify.sh web", decisions[0].body)

    def test_stale_alert_is_not_a_ticket(self):
        """**关键口径**:告警还 open,但锁文件里早已修好 → 不开单。

        2026-11-12 实测:修复后仍有 13 条 open 告警;只信 state 会为已修好的漏洞开单。
        """
        alert = alert_fixture(package="vite", vulnerable=">= 8.3.0, <= 8.3.2", patched="8.3.3")
        decisions, undecidable = l4_intake.decide_dep([alert], self.root, NOW)
        self.assertEqual(undecidable, [])
        self.assertEqual([d.action for d in decisions], ["skip"])
        self.assertIn("告警滞后", decisions[0].reason)

    def test_low_severity_is_not_a_ticket(self):
        """低于阈值(默认 high)只记录不开单 —— 那是「值不值得修」的判断。"""
        alert = alert_fixture(
            package="vite", severity="medium", vulnerable=">= 8.3.0, <= 8.9.0", patched="8.9.1"
        )
        decisions, _ = l4_intake.decide_dep([alert], self.root, NOW)
        self.assertEqual([d.action for d in decisions], ["skip"])
        self.assertIn("低于阈值", decisions[0].reason)

    def test_no_patched_version_is_human(self):
        """没有修复版本 → 「怎么办」变成判断,留给人。"""
        alert = alert_fixture(package="vite", patched="", vulnerable=">= 8.3.0, <= 8.9.0")
        decisions, _ = l4_intake.decide_dep([alert], self.root, NOW)
        self.assertEqual([d.action for d in decisions], ["skip"])
        self.assertIn("没有修复版本", decisions[0].reason)

    def test_non_whitelisted_ecosystem_is_skipped(self):
        """docker / actions 的修复动的是 worker 不可写或必须人审的文件 → 不开单。"""
        alert = alert_fixture(
            package="nginx", ecosystem="docker", manifest="deploy/Dockerfile",
            vulnerable="< 1.31", patched="1.31",
        )
        decisions, _ = l4_intake.decide_dep([alert], self.root, NOW)
        self.assertEqual([d.action for d in decisions], ["skip"])
        self.assertIn("不在白名单", decisions[0].reason)

    def test_dismissed_alert_ignored(self):
        """已 dismiss → 连 skip 记录都不产生(不是我们的信号)。"""
        alert = alert_fixture(package="undici", vulnerable=">= 7.0.0, < 7.31.0", dismissed=True)
        decisions, undecidable = l4_intake.decide_dep([alert], self.root, NOW)
        self.assertEqual((decisions, undecidable), ([], []))

    def test_missing_lock_entry_is_undecidable(self):
        """锁文件里找不到该包 → 判不出来,不开单。"""
        alert = alert_fixture(package="left-pad", vulnerable="< 9.9.9", patched="9.9.9")
        decisions, undecidable = l4_intake.decide_dep([alert], self.root, NOW)
        self.assertEqual(decisions, [])
        self.assertEqual(len(undecidable), 1)
        self.assertIn("锁文件里找不到", undecidable[0])

    def test_pip_alert_opens_backend_ticket(self):
        """pip 告警 → backend 栈工单,验收用 requirements.lock。"""
        (self.root / "chatapp/requirements.lock").write_text("Django==5.2.1\n", encoding="utf-8")
        alert = alert_fixture(
            package="Django", ecosystem="pip", manifest="chatapp/requirements.txt",
            vulnerable=">= 5.0.0, < 5.2.2", patched="5.2.2",
        )
        decisions, _ = l4_intake.decide_dep([alert], self.root, NOW)
        self.assertEqual([d.action for d in decisions], ["create"])
        self.assertIn("scripts/verify.sh backend", decisions[0].body)
        self.assertRegex(decisions[0].title, r"^fix\(backend\): ")

    def test_malformed_alerts_is_undecidable(self):
        """告警响应形状不对 → 判不出来,不开单。"""
        decisions, undecidable = l4_intake.decide_dep({"oops": 1}, self.root, NOW)
        self.assertEqual(decisions, [])
        self.assertTrue(undecidable)


class DocsLinksTests(unittest.TestCase):
    """机械一致性信号:文档断链,按文件聚合成一张单。"""

    def setUp(self):
        """建临时仓库,含一个断链文件。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs/specs").mkdir(parents=True)
        (self.root / "docs/real.md").write_text("# 真实文件\n", encoding="utf-8")
        (self.root / "docs/specs/a.md").write_text(
            "# 标题\n\n[好的](../real.md)\n[坏的](../../missing.md)\n[外链](https://example.com)\n",
            encoding="utf-8",
        )

    def tearDown(self):
        """清理临时仓库。"""
        self.tmp.cleanup()

    def test_broken_link_opens_one_ticket_per_file(self):
        """一个文件多处的断链 → 合成一张单(不按链接数开单)。"""
        decisions, undecidable = l4_intake.decide_docs_links(self.root, NOW)
        self.assertEqual(undecidable, [])
        self.assertEqual([d.action for d in decisions], ["create"])
        self.assertIn("docs/specs/a.md", decisions[0].title)
        self.assertIn("第 4 行", decisions[0].body)
        self.assertIn("python scripts/check_docs_links.py", decisions[0].body)

    def test_clean_docs_opens_nothing(self):
        """没有断链 → 不开单。"""
        (self.root / "docs/specs/a.md").write_text("# 标题\n\n[好的](../real.md)\n", encoding="utf-8")
        decisions, undecidable = l4_intake.decide_docs_links(self.root, NOW)
        self.assertEqual((decisions, undecidable), ([], []))

    def test_missing_docs_dir_is_undecidable(self):
        """docs/ 不存在 → 判不出来,不开单。"""
        decisions, undecidable = l4_intake.decide_docs_links(self.root / "nope", NOW)
        self.assertEqual(decisions, [])
        self.assertTrue(undecidable)


class TicketSafetyTests(unittest.TestCase):
    """工单格式与安全边界:格式给 worker 接、正文不 @ 人(否则等于绕过人工派单)。"""

    def setUp(self):
        """收集三类信号各一张单。"""
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
        """清理临时仓库。"""
        self.tmp.cleanup()

    def test_three_signals_produce_three_tickets(self):
        """三类信号各开一张,证明自测覆盖了全部检测器。"""
        self.assertEqual(len(self.tickets), 3)
        self.assertEqual(
            sorted({t.detector for t in self.tickets}),
            [l4_intake.SIG_CI_RED, l4_intake.SIG_DEP, l4_intake.SIG_DOCS_LINKS],
        )

    def test_no_at_mentions_anywhere(self):
        """**安全红线**:正文/标题不许出现 `@xxx` —— opening body 会被当成派工源。"""
        for ticket in self.tickets:
            self.assertNotIn("@", ticket.title)
            self.assertNotIn("@", ticket.body)

    def test_mention_scrubber(self):
        """即使事实字段里带了 @,也要被抹掉。"""
        self.assertEqual(l4_intake._scrub_mentions("问 @shiliu655 一下"), "问 shiliu655 一下")

    def test_ticket_has_fingerprint_facts_acceptance_and_stack(self):
        """正文必须自带:指纹行 + 事实表 + 验收命令 + 唯一栈。"""
        for ticket in self.tickets:
            self.assertRegex(ticket.body, r"<!-- l4-fingerprint: [0-9a-f]{16} -->")
            self.assertIn("## 事实(机器生成,勿手改)", ticket.body)
            self.assertIn("## 验收", ticket.body)
            self.assertIn("## 栈", ticket.body)
            self.assertIn(l4_intake.LABEL_AUTO, ticket.labels)

    def test_docs_ticket_forbids_creating_new_docs(self):
        """断链单不许「新建文档凑链接」—— 那等于替人决定写什么。"""
        docs_ticket = [t for t in self.tickets if t.detector == l4_intake.SIG_DOCS_LINKS][0]
        self.assertIn("新建文档", docs_ticket.body)

    def test_fingerprint_is_stable_and_distinct(self):
        """指纹稳定(同一失败不变)且区分得开(不同对象不同单)。"""
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

        Args:
            fp: 指纹。

        Returns:
            `create` 判定。
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
        """已有同名 open issue → 只追加一次命中记录,不新建。"""
        existing = {self._decision().fingerprint: {"number": 42, "state": "open", "title": "t"}}
        out = l4_intake.apply_dedup([self._decision()], existing, 0, 5, NOW)
        self.assertEqual(out[0].action, "comment")
        self.assertEqual(out[0].issue, 42)
        self.assertIn("再次命中", out[0].body)

    def test_closed_issue_is_reopened(self):
        """停过又复发的同一失败 → 重开原单,而不是新开一条(保历史)。"""
        existing = {self._decision().fingerprint: {"number": 7, "state": "closed", "title": "t"}}
        out = l4_intake.apply_dedup([self._decision()], existing, 0, 5, NOW)
        self.assertEqual(out[0].action, "reopen")
        self.assertEqual(out[0].issue, 7)

    def test_quota_defers(self):
        """当天配额用满 → 不开单(defer),但去重类的动作照做。"""
        out = l4_intake.apply_dedup([self._decision()], {}, 5, 5, NOW)
        self.assertEqual(out[0].action, "defer")
        self.assertIn("配额已满", out[0].reason)

    def test_quota_zero_blocks_everything_new(self):
        """`L4_MAX_PER_DAY=0` 是第二道刹车:今天一张都不许新建。"""
        out = l4_intake.apply_dedup([self._decision()], {}, 0, 0, NOW)
        self.assertEqual(out[0].action, "defer")

    def test_existing_fingerprint_extraction(self):
        """能从 issue 正文里认出指纹;没有指纹的 issue 被忽略。"""
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
        """建临时仓库,造「一条红轨 + 一条断链 + 一个已修好的告警」。"""
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
        """清理临时仓库。"""
        self.tmp.cleanup()

    def _plan(self, **kwargs) -> dict:
        """跑一次 build_plan,默认输入见 `setUp`。

        Args:
            **kwargs: 覆盖默认输入。

        Returns:
            plan 字典。
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
        """2 个真信号开单,已修好的告警被跳过。"""
        plan = self._plan()
        actions = sorted(d["action"] for d in plan["decisions"])
        self.assertEqual(actions, ["create", "create", "skip"])
        self.assertEqual(plan["summary"]["create"], 2)

    def test_disabled_gate_does_nothing(self):
        """`L4_INTAKE=off` → 空计划(总闸)。"""
        plan = self._plan(enabled=False)
        self.assertEqual(plan["decisions"], [])
        self.assertFalse(plan["enabled"])

    def test_markdown_summary_lists_decisions(self):
        """日报里能看到「开了谁 / 跳过谁 / 为什么」。"""
        markdown = l4_intake.render_plan_markdown(self._plan())
        self.assertIn("| 信号 | 动作 | 对象 | 说明 |", markdown)
        self.assertIn("create", markdown)
        self.assertIn("skip", markdown)


class GhCommandsTests(unittest.TestCase):
    """计划 → gh 命令(纯函数,不执行)。"""

    def test_create_command(self):
        """create → `gh issue create` 带标题/正文/两个标签/仓库。"""
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
        """reopen → 先 reopen 再评论。"""
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
        """只有 skip / defer 时不产生任何 gh 命令(也不建标签)。"""
        plan = {"decisions": [{"action": "skip", "detector": l4_intake.SIG_DEP}]}
        self.assertEqual(l4_intake.build_gh_commands(plan, "o/r"), [])


class CommandLineTests(unittest.TestCase):
    """CLI 面:开关、退出码、坏输入 fail-closed。"""

    def setUp(self):
        """建临时仓库与 JSON 快照。"""
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
        """清理临时仓库。"""
        self.tmp.cleanup()

    def test_plan_writes_json_and_summary(self):
        """`plan` 写出计划与日报,退出码 0(判不出来才有非零)。"""
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
        """输入坏掉 → 一条都不开,plan 里记 undecidable(`apply` 据此把 run 标红)。"""
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
        """`apply --dry-run` 只打印,退出码 0。"""
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
        """plan 里有 undecidable → `apply` 退出码 1(整轮 run 标红,不能静默)。"""
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
