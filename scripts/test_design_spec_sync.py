"""``scripts/design_spec_sync.py`` 的自测(真实规范做样本,就地改坏再判)。

进 CI 的 `contract` 轨。这道门禁防的是「同一份事实两处手写」——本仓库历史上过期过五次
（`docs/standards/writing.md` §5.1）。所以自测的重点是**两个方向 + 三种坏法**：

- **值不同**（最危险：两边都像对的）；
- **表里有、token 没有**（文档承诺了不存在的 token）；
- **token 有、表里没有**（新增 token 没人看得到）；
- **表本身读不出来**（标题改名 / 表格被改坏）必须 fail-closed，不能「0 条漂移 = 通过」。

样本做法:读真实规范,用 ``str.replace`` 造一处已知漂移,再断言**恰好**能被抓到 ——
比手写一份假规范更能证明脚本对真实排版有效(中文全角括号、反引号、``@ 92%`` 这些形态)。
"""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from scripts import design_contrast, design_spec_sync, design_tokens


def _quiet() -> contextlib.AbstractContextManager:
    """吞掉 stdout(失败行是预期内的)。

    返回参数:
        contextlib.AbstractContextManager: 重定向上下文。

    使用示例:
        ``with _quiet(): design_spec_sync.check(spec)``

    备注信息:
        只吞 stdout;异常仍然会抛出来。
    """
    return contextlib.redirect_stdout(io.StringIO())


class SpecCase(unittest.TestCase):
    """把真实规范读进来,按需改坏一处后落到临时文件。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.spec_path = design_contrast.find_spec()
        cls.original = cls.spec_path.read_text(encoding="utf-8")

    def mutate(self, old: str, new: str, count: int = 1) -> Path:
        """把规范里的一处文本替换掉,写到临时文件。

        参数说明:
            old: 要被替换的原文。
            new: 替换成什么。
            count: 替换几处(默认 1,避免同一 hex 在色阶表与语义表各出现一次时误改两处)。

        返回参数:
            Path: 临时文件路径。

        使用示例:
            ``self.mutate("`#54409E`", "`#123456`")``

        备注信息:
            原串不存在时直接让用例失败 —— 那说明规范正文改过、样本锚点失效了,
            不能静默跳过(否则自测会「永远绿」)。
        """
        self.assertIn(old, self.original, f"样本锚点不存在于规范:{old}")
        text = self.original.replace(old, new, count)
        handle = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8")
        handle.write(text)
        handle.close()
        return Path(handle.name)


class TestParsing(SpecCase):
    """真实排版下两类表都能解析。"""

    def test_ramps_have_expected_shape(self) -> None:
        ramps = design_spec_sync.parse_ramps(self.spec_path)
        self.assertEqual(set(ramps), {"ember", "paper"})
        self.assertEqual(ramps["ember"]["600"], "#C93C22")
        self.assertEqual(ramps["paper"]["5"], "#FBF7F3")
        self.assertEqual(sum(len(steps) for steps in ramps.values()), 27)

    def test_semantic_table_covers_both_modes(self) -> None:
        table = design_spec_sync.parse_semantic_table(self.spec_path)
        self.assertEqual(table["brand.default"]["light"][0], "#C93C22")
        self.assertEqual(table["brand.default"]["dark"][0], "#FF9370")
        self.assertGreaterEqual(len(table), 20)

    def test_scrim_percentage_is_parsed(self) -> None:
        table = design_spec_sync.parse_semantic_table(self.spec_path)
        self.assertEqual(table["overlay.scrim"]["light"], ("#1C1714", 92))

    def test_missing_semantic_heading_fails_closed(self) -> None:
        path = self.mutate(design_spec_sync.SEMANTIC_HEADING, "### 3.3 语义色（改名了）")
        with self.assertRaises(design_tokens.TokenError):
            design_spec_sync.parse_semantic_table(path)


class TestDriftDetection(SpecCase):
    """三种漂移都必须被抓到,且仓库当前是无漂移的。"""

    def test_repository_is_consistent(self) -> None:
        with _quiet():
            self.assertEqual(design_spec_sync.check(), 0,
                             "规范正文与 design/tokens 漂移了;先改 token 再同步文档")

    def test_value_mismatch_is_caught(self) -> None:
        path = self.mutate("`#54409E`", "`#123456`")
        with _quiet():
            self.assertEqual(design_spec_sync.check(path), 1)

    def test_documented_but_missing_token_is_caught(self) -> None:
        path = self.mutate("| `overlay.scrim`", "| `overlay.ghost`")
        with _quiet():
            self.assertEqual(design_spec_sync.check(path), 1)

    def test_token_without_documentation_is_caught(self) -> None:
        # 把语义表整行删掉:solid 的做法是删掉 brand.on 那一行
        row = [line for line in self.original.splitlines() if line.startswith("| `brand.on`")][0]
        path = self.mutate(row + "\n", "")
        with _quiet():
            self.assertEqual(design_spec_sync.check(path), 1)

    def test_ramp_value_mismatch_is_caught(self) -> None:
        path = self.mutate("`#FFF0E9`", "`#FFF0EA`")
        with _quiet():
            self.assertEqual(design_spec_sync.check(path), 1)

    def test_alpha_mismatch_is_caught(self) -> None:
        path = self.mutate("`#1C1714` @ 92%", "`#1C1714`")
        with _quiet():
            self.assertEqual(design_spec_sync.check(path), 1)


class TestMigrationTable(SpecCase):
    """§18.2 的「新值」列是副本,抄错必须被抓到;整节删掉则不该判红。"""

    def test_migration_rows_are_parsed(self) -> None:
        table = design_spec_sync.parse_migration_table(self.spec_path)
        self.assertIsNotNone(table)
        self.assertEqual(table["brand.default"], ("#C93C22", "#FF9370"))
        self.assertEqual(table["text.secondary"], ("#6A5F55", "#C4B9AD"))
        self.assertGreaterEqual(len(table), 10)

    def test_migration_new_value_mismatch_is_caught(self) -> None:
        # 把迁移表里 brand 行的深色值改错
        path = self.mutate("| `brand.default` | `#C93C22` / `#FF9370` |", "| `brand.default` | `#C93C22` / `#FF9371` |")
        with _quiet():
            self.assertEqual(design_spec_sync.check(path), 1)

    def test_absent_migration_section_is_not_an_error(self) -> None:
        # 迁移完成后 §18 被删掉是正常归宿,不该让门禁红
        path = self.mutate("### 18.2 色彩", "### 18.x 已迁移归档")
        with _quiet():
            self.assertEqual(design_spec_sync.check(path), 0)


if __name__ == "__main__":
    unittest.main()
