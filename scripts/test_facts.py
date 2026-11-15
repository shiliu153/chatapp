"""``scripts/facts.py`` 的自测(纯离线,临时目录里造样本)。

进 CI 的 `contract` 轨(`contract-facts-selftest`)。定位与 `test_docs_lint.py` 一致:
**判定器的两个方向都不能静默**。

- **漏报**:数字错了却不红 → 文档继续漂移,而这正是本节要消灭的东西
  (`capacity-and-reliability.md` 的「10 条告警 vs 17 条」就是这么漂了没人发现);
- **误报**:合规的写法被判红 → 人会去关整条规则,门禁退化成摆设。
  本仓库有前车之鉴:`term` 规则第一版差点红一片。

所以每条规则都成对写:该红的红(R1 / R2 / R3),不该红的**不红**:

- R1 值:哨兵值写错必红、写对不红、拼错 id 必红;
- R2 强制哨兵:**数值正确但没包哨兵也红**(这条最反直觉,必须有测试),
  加粗写法 ``**17 条**告警`` 仍被认出,不相关领域的 ``867 条规则`` 不误伤;
- R3 位置:标题与代码围栏里的哨兵必红,围栏里与标题里的裸数字不动它(改了就制造新违例);
- 豁免:整文件白名单、行内标记只豁免它那一行、历史目录不在作用域。

另钉三件事:``--write`` 必须**幂等**(跑两次第二次不落盘)、必须把值写成**唯一规范形态**
(``25/25`` → ``25 / 25``),以及真实仓库上 :func:`facts.compute_values` 能算出全部事实
(注册表里写坏了要当场炸)。

> 样本文本一律用**真实句式**(``workflow(当前 N 个)`` / ``N 条告警``):断言正则是刻意
> 收窄到词组的,用「共 N 个 workflow」这种倒装去测只会测到「正则没命中」,测不到判定逻辑。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts import check_cpp_comments, facts

#: 仓库根(自测在真实仓库上做只读冒烟;不依赖 cwd)。
REPO_ROOT = Path(__file__).resolve().parent.parent

#: 只启一个事实的取值集 —— 判定逻辑与「有哪些事实」解耦,加事实不会波及其它用例。
ONLY_WORKFLOWS = {"workflows": "10"}


def write_doc(root: Path, name: str, body: str) -> Path:
    """在临时仓库里写一份文档(父目录按需创建)。

    Args:
        root: 仓库根目录。
        name: 相对仓库根的路径。
        body: 全文内容。

    Returns:
        写入的文件路径。
    """
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body.encode("utf-8"))
    return path


class TempRepoCase(unittest.TestCase):
    """带临时仓库的用例基类(每个用例一个干净的根)。"""

    def setUp(self):
        """建临时仓库根。"""
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "docs").mkdir()

    def tearDown(self):
        """清理。"""
        self.tmp.cleanup()

    def check_text(self, body: str, values: dict | None = None) -> list[dict]:
        """把一段文本当成一份作用域内文档来判,返回违例列表。

        Args:
            body: 文档全文。
            values: 事实取值,缺省只有 ``workflows = 10``。

        Returns:
            :func:`facts.check_file` 的违例列表。
        """
        path = write_doc(self.root, "docs/ops/sample.md", body)
        problems, _fixed = facts.check_file(path, self.root, values or dict(ONLY_WORKFLOWS))
        return problems

    def fix_text(self, body: str, values: dict | None = None) -> str:
        """对一段文本跑一遍修复,返回修好之后的全文。

        Args:
            body: 文档全文。
            values: 事实取值,缺省只有 ``workflows = 10``。

        Returns:
            修好之后的全文。
        """
        return facts.apply_fixes(body, values or dict(ONLY_WORKFLOWS))


class SentinelValueTests(TempRepoCase):
    """R1:哨兵里的值必须等于事实。"""

    def test_matching_value_passes(self):
        """值对、位置对 → 0 违例。"""
        body = "workflow(当前 <!-- num:workflows -->10<!-- /num --> 个)\n"
        self.assertEqual(self.check_text(body), [])

    def test_wrong_value_reported(self):
        """值写错 → sentinel-value(并报出事实值)。"""
        problems = self.check_text("workflow(当前 <!-- num:workflows -->9<!-- /num --> 个)\n")
        self.assertEqual([item["rule"] for item in problems], ["sentinel-value"])
        self.assertIn("9", problems[0]["message"])

    def test_unknown_id_reported(self):
        """哨兵里的事实 id 拼错 → sentinel-unknown(不能静默当成合规)。"""
        problems = self.check_text("workflow(当前 <!-- num:nosuch -->10<!-- /num --> 个)\n")
        self.assertEqual([item["rule"] for item in problems], ["sentinel-unknown"])


class BareNumberTests(TempRepoCase):
    """R2:命中已注册形态的裸数字一律红 —— **即使数值正确**。"""

    def test_correct_value_still_reported(self):
        """数值对但没包哨兵 → 仍然红(不留「反正我写对了」的口子)。"""
        problems = self.check_text("workflow(当前 10 个)\n")
        self.assertEqual([item["rule"] for item in problems], ["bare-number"])
        self.assertIn("10", problems[0]["message"])

    def test_wrong_value_reported(self):
        """数值错且没包哨兵 → 红,且提示里给出事实值。"""
        problems = self.check_text("workflow(当前 9 个)\n")
        self.assertEqual(len(problems), 1)
        self.assertIn("'10'", problems[0]["message"])

    def test_bold_wrapping_still_detected(self):
        """``**17 条**告警`` 这种加粗写法必须仍然被认出(否则漏判)。"""
        problems = self.check_text("共 **17 条**告警加载\n", {"alert_rules": "17"})
        self.assertEqual([item["rule"] for item in problems], ["bare-number"])

    def test_other_domain_rule_count_not_matched(self):
        """不相关领域的「867 条规则」不许误伤(mihomo 的规则数,不是告警规则)。"""
        self.assertEqual(self.check_text("刚启动要 3s 加载 867 条规则\n", {"alert_rules": "17"}), [])

    def test_unregistered_number_untouched(self):
        """注册表没声明的形态(规格 / 测量数字)不受约束。"""
        self.assertEqual(self.check_text("限流 120 次/小时,压测 476 rps,上限 50 条\n"), [])


class PlacementTests(TempRepoCase):
    """R3:哨兵不得出现在标题与代码围栏里。"""

    def test_sentinel_in_heading_reported(self):
        """标题里的哨兵 → sentinel-heading(会打碎 anchor、目录链接全断)。"""
        body = "## workflow(当前 <!-- num:workflows -->10<!-- /num --> 个)\n"
        self.assertEqual([item["rule"] for item in self.check_text(body)], ["sentinel-heading"])

    def test_sentinel_in_fence_reported(self):
        """围栏里的哨兵 → sentinel-fence(HTML 注释会当字面量显示出来)。"""
        body = "```\nworkflow(当前 <!-- num:workflows -->10<!-- /num --> 个)\n```\n"
        self.assertEqual([item["rule"] for item in self.check_text(body)], ["sentinel-fence"])

    def test_bare_number_in_fence_not_reported(self):
        """围栏里的裸数字是代码示例:不判,也不自动改。"""
        body = "```\nworkflow(当前 10 个)\n```\n"
        self.assertEqual(self.check_text(body), [])
        self.assertEqual(self.fix_text(body), body)

    def test_bare_number_in_heading_not_reported(self):
        """标题里的裸数字不判(自动包哨兵会立刻变成 R3 违例)。"""
        body = "## workflow(当前 10 个)\n"
        self.assertEqual(self.check_text(body), [])
        self.assertEqual(self.fix_text(body), body)


class ExemptionTests(TempRepoCase):
    """豁免:整文件白名单 / 行内标记 / 历史目录。"""

    def test_allow_marker_exempts_only_its_line(self):
        """行内标记只豁免它所在的那一行。"""
        body = (
            "workflow(当前 10 个) <!-- lint:allow:number -->\n"
            "workflow(当前 10 个)\n"
        )
        problems = self.check_text(body)
        self.assertEqual(len(problems), 1)
        self.assertEqual(problems[0]["line"], 2)

    def test_exempt_file_not_scanned(self):
        """``sources-of-truth.md`` 整文件豁免(它故意保留历史数字与裁决过程)。"""
        path = write_doc(self.root, facts.EXEMPT_FILES[0], "workflow(当前 10 个)\n")
        self.assertNotIn(path.resolve(), [item.resolve() for item in facts.scope_files(self.root)])

    def test_history_dirs_not_scanned(self):
        """历史 / 一次性报告 / 教学目录不在作用域(改历史等于改写证据)。"""
        for name in (
            "docs/milestones.md",
            "docs/reports/r-2026-11-01.md",
            "docs/security/round1.md",
            "docs/backlog/2026-11-03-todo.md",
            "docs/superpowers/specs/x-design.md",
            "docs/learning/l.md",
            "app/README.md",
        ):
            write_doc(self.root, name, "workflow(当前 10 个)\n")
        self.assertEqual(facts.scope_files(self.root), [])

    def test_live_docs_scanned(self):
        """作用域内五类文档都要被扫到(漏扫 = 门禁形同虚设)。"""
        names = (
            "README.md",
            "CLAUDE.md",
            "AGENTS.md",
            "docs/architecture.md",
            "docs/ops/a.md",
            "docs/standards/b.md",
            "docs/api/c.md",
            "docs/pitfalls/d.md",
        )
        for name in names:
            write_doc(self.root, name, "# x\n")
        # 顺序 = ``as_posix()`` 的字节序(不是文件名序):``docs/api/c.md`` 排在
        # ``docs/architecture.md`` 之前,因为 ``ap`` < ``ar``。生成物与报告都靠这个顺序稳定。
        self.assertEqual(
            [path.name for path in facts.scope_files(self.root)],
            ["AGENTS.md", "CLAUDE.md", "README.md", "c.md", "architecture.md", "a.md", "d.md", "b.md"],
        )


class WriteTests(TempRepoCase):
    """``--write``:刷新哨兵 + 包住裸数字,并且必须幂等、形态唯一。"""

    def test_wraps_bare_number_with_fact_value(self):
        """裸数字被就地包上哨兵,值取**事实**而不是原文。"""
        self.assertEqual(
            self.fix_text("workflow(当前 9 个)\n"),
            "workflow(当前 <!-- num:workflows -->10<!-- /num --> 个)\n",
        )

    def test_refreshes_stale_sentinel(self):
        """过期哨兵被刷新成当前值。"""
        self.assertEqual(
            self.fix_text("workflow(当前 <!-- num:workflows -->7<!-- /num --> 个)\n"),
            "workflow(当前 <!-- num:workflows -->10<!-- /num --> 个)\n",
        )

    def test_canonicalizes_spacing(self):
        """值写成唯一规范形态:``25/25`` → ``25 / 25``(判定与渲染不能各说一套)。"""
        body = "现 <!-- num:gates_contract -->25/25<!-- /num --> 道\n"
        self.assertEqual(
            self.fix_text(body, {"gates_contract": "25 / 25"}),
            "现 <!-- num:gates_contract -->25 / 25<!-- /num --> 道\n",
        )

    def test_keeps_bold_outside_sentinel(self):
        """加粗标记留在哨兵外面(渲染出来仍是粗体)。"""
        self.assertEqual(
            self.fix_text("共 **17 条**告警加载\n", {"alert_rules": "17"}),
            "共 **<!-- num:alert_rules -->17<!-- /num --> 条**告警加载\n",
        )

    def test_idempotent(self):
        """跑第二遍不产生任何变化(否则 CI 每轮都会红)。"""
        values = {"workflows": "10", "docs_archive": "106"}
        once = self.fix_text("workflow(当前 9 个),归档 106 份\n", values)
        self.assertIn("num:workflows", once)
        self.assertEqual(facts.apply_fixes(once, values), once)

    def test_preserves_crlf(self):
        """CRLF 检出必须原样保留(否则整文件换行被改,diff 不可 review)。"""
        self.assertEqual(
            self.fix_text("workflow(当前 9 个)\r\n第二行\r\n"),
            "workflow(当前 <!-- num:workflows -->10<!-- /num --> 个)\r\n第二行\r\n",
        )

    def test_unknown_sentinel_left_alone(self):
        """未知 id 不自动改(改它等于掩盖拼写错误),由 R1 报出来。"""
        body = "workflow(当前 <!-- num:nosuch -->10<!-- /num --> 个)\n"
        self.assertEqual(self.fix_text(body), body)


class ComputeTests(TempRepoCase):
    """计算层:数文件这类纯本地计算的口径。"""

    def test_workflows_counts_yml_and_yaml(self):
        """``.yml`` 与 ``.yaml`` 都算,其它后缀不算。"""
        wf = self.root / ".github" / "workflows"
        wf.mkdir(parents=True)
        for name in ("a.yml", "b.yaml", "c.txt"):
            (wf / name).write_text("x", encoding="utf-8")
        self.assertEqual(facts._workflows(self.root), "2")  # noqa: SLF001

    def test_workflows_missing_dir_is_zero(self):
        """目录不存在按 0 算(没有 workflow 是合法状态)。"""
        self.assertEqual(facts._workflows(self.root), "0")  # noqa: SLF001

    def test_alert_targets_counts_job_names(self):
        """``- job_name:`` 行数就是抓取目标数。"""
        targets = self.root / "deploy" / "observability"
        targets.mkdir(parents=True)
        (targets / "prometheus.yml").write_text(
            "scrape_configs:\n  - job_name: api\n  - job_name: im\n", encoding="utf-8"
        )
        self.assertEqual(facts._alert_targets(self.root), "2")  # noqa: SLF001

    def test_alert_targets_missing_file_raises(self):
        """配置文件缺失是「判不出来」,不是 0 个。"""
        with self.assertRaises(FileNotFoundError):
            facts._alert_targets(self.root)  # noqa: SLF001

    def test_dashboard_panels_sums_every_dashboard(self):
        """多个看板的 panel 数相加。"""
        dashboards = self.root / "deploy" / "observability" / "grafana" / "dashboards"
        dashboards.mkdir(parents=True)
        (dashboards / "a.json").write_text('{"panels": [{}, {}, {}]}', encoding="utf-8")
        (dashboards / "b.json").write_text('{"panels": [{}]}', encoding="utf-8")
        self.assertEqual(facts._dashboard_panels(self.root), "4")  # noqa: SLF001

    def test_dashboard_panels_without_panels_raises(self):
        """看板里没有 panels 数组是判不出来。"""
        dashboards = self.root / "deploy" / "observability" / "grafana" / "dashboards"
        dashboards.mkdir(parents=True)
        (dashboards / "a.json").write_text('{"rows": []}', encoding="utf-8")
        with self.assertRaises(ValueError):
            facts._dashboard_panels(self.root)  # noqa: SLF001

    def test_cpp_comment_blocks_counts_separator_pairs(self):
        """每个块上下各一条分隔线,所以块数 = 分隔线行数 ÷ 2。"""
        src = self.root / "imserver" / "src"
        src.mkdir(parents=True)
        separator = "//" + "-" * 115
        block = (
            f"{separator}\n// 函数简介\n{separator}\nvoid a();\n"
            f"{separator}\n// 函数简介\n{separator}\nvoid b();\n"
        )
        (src / "x.h").write_text(block, encoding="utf-8")
        self.assertEqual(facts._cpp_comment_blocks(self.root), "2")  # noqa: SLF001

    def test_cpp_comment_blocks_odd_separators_raise(self):
        """分隔线是奇数说明块结构坏了 —— 宁可判不出来,也不要报一个错数字。"""
        src = self.root / "imserver" / "src"
        src.mkdir(parents=True)
        separator = "//" + "-" * 115
        (src / "x.h").write_text(f"{separator}\nvoid a();\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            facts._cpp_comment_blocks(self.root)  # noqa: SLF001


class PatternCollisionTests(unittest.TestCase):
    """断言正则必须**互不相交**:同一处文本被两个事实命中,会包上两个哨兵(结构就坏了)。"""

    def _ids_matching(self, line: str) -> list[str]:
        """返回这一行会被哪些事实命中。

        Args:
            line: 待测文本。

        Returns:
            命中的事实 id 列表(顺序同 :data:`facts.FACTS`)。
        """
        return [
            fact.id
            for fact in facts.FACTS
            for pattern in fact.patterns
            if pattern.search(line)
        ]

    def test_dashboard_panel_is_not_cpp_block(self):
        """看板的「12 块」只属于 dashboard_panels。"""
        self.assertEqual(self._ids_matching("| 看板 | 12 块(新增业务漏斗) |"), ["dashboard_panels"])

    def test_cpp_block_is_not_dashboard_panel(self):
        """C++ 的「637 个块」只属于 cpp_comment_blocks。"""
        self.assertEqual(self._ids_matching("一条硬事实:637 个块**没有一个**落在函数体内部。"), ["cpp_comment_blocks"])

    def test_cpp_subtotal_not_matched(self):
        """`tests/` 的子集计数(共 108 个块)不是 C++ 注释块总数 → 一个都不许命中。"""
        self.assertEqual(
            self._ids_matching("`tests/` 的 15 个用例文件共 108 个块 = 107 个 `TEST`"), []
        )

    def test_cpp_table_row_matched_once(self):
        """``| 函数注释块 | 637 = `src/` 529 + `tests/` 108 |`` 只命中总数那一处。"""
        self.assertEqual(
            self._ids_matching("| 函数注释块 | 637 = `src/` 529 + `tests/` 108 |"),
            ["cpp_comment_blocks"],
        )

    def test_panel_comma_form(self):
        """容量文档里「,12 面板,抓取 15s」这一格。"""
        self.assertEqual(self._ids_matching("(E-4 后),12 面板,抓取 15s"), ["dashboard_panels"])

    def test_alert_targets_row(self):
        """「6 个 target(api/im/...)」只属于 alert_targets。"""
        self.assertEqual(
            self._ids_matching("6 个 target(api/im/node/celery/mysql/redis)全 `up`"),
            ["alert_targets"],
        )


def _tree_sitter_available() -> bool:
    """当前环境有没有装 tree-sitter(没有就跳过 AST 口径的交叉校验)。

    Returns:
        两个 wheel 都导入成功时返回 ``True``。
    """
    try:
        import tree_sitter  # noqa: F401  (只探可用性)
        import tree_sitter_cpp  # noqa: F401
    except ImportError:
        return False
    return True


@unittest.skipUnless(_tree_sitter_available(), "需要 tree-sitter(CI 与 bootstrap 环境里有)")
class CppBlockCrossCheckTests(unittest.TestCase):
    """分隔线口径(纯标准库)必须等于 AST 口径 —— 两套算法只准有一个答案。"""

    def test_separator_count_equals_ast_blocks(self):
        """``_cpp_comment_blocks`` 的块数 == ``check_cpp_comments`` 逐文件 ``blocks`` 之和。"""
        parser = check_cpp_comments.load_parser()
        imserver = REPO_ROOT / "imserver"
        total = 0
        for path in check_cpp_comments.iter_sources(imserver):
            total += check_cpp_comments.check_file(REPO_ROOT, imserver, path, parser).blocks
        self.assertEqual(facts._cpp_comment_blocks(REPO_ROOT), str(total))  # noqa: SLF001


class CommandLineTests(unittest.TestCase):
    """命令行口径:判不出来必须是退出码 2,不是「0 违例」。"""

    def test_conflicting_flags_exit_two(self):
        """``--write`` 与 ``--check`` 同时给 → 2。"""
        self.assertEqual(facts.main(["--write", "--check"]), 2)

    def test_write_and_report_conflict(self):
        """``--write`` 与 ``--report`` 同时给 → 2。"""
        self.assertEqual(facts.main(["--write", "--report"]), 2)

    def test_missing_docs_dir_exit_two(self):
        """目录不对 → 2(而不是「0 违例」)。"""
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(facts.main(["--root", tmp]), 2)


class RealRepoSmokeTests(unittest.TestCase):
    """真实仓库上的只读冒烟:注册表本身没写坏。"""

    def test_every_fact_computes(self):
        """每个事实都能在真实仓库上算出非空值。"""
        values = facts.compute_values(REPO_ROOT)
        self.assertEqual(set(values), {fact.id for fact in facts.FACTS})
        for fact_id, value in values.items():
            self.assertTrue(value.strip(), f"{fact_id} 算出了空值")

    def test_gate_contract_renders_same_on_both_sides(self):
        """``gates_contract`` 必须渲染成 ``N / N``(本地与 CI 跑同一份清单,条数不可能不等)。"""
        value = facts._gates_contract(REPO_ROOT)  # noqa: SLF001  (自测就该钉住渲染形态)
        left, _, right = value.partition("/")
        self.assertEqual(left.strip(), right.strip())

    def test_patterns_have_exactly_one_group(self):
        """每个断言正则恰好一个捕获组 —— 多于一个会让替换捏错位置。"""
        for fact in facts.FACTS:
            for pattern in fact.patterns:
                self.assertEqual(pattern.groups, 1, f"{fact.id} 的正则有 {pattern.groups} 个组")

    def test_fact_ids_are_sorted_and_unique(self):
        """id 唯一且按 POSIX 字节序排(``--report`` 输出跨平台稳定)。"""
        ids = [fact.id for fact in facts.FACTS]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(ids, sorted(ids, key=lambda item: item.encode("utf-8")))


if __name__ == "__main__":
    unittest.main()
