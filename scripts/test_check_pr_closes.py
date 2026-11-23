"""``scripts/check_pr_closes.py`` 的自测(纯离线,不联网、不碰 GitHub)。

进 CI 的 `contract` 轨。这道判定守的是「活干完了 issue 还开着」——它自己坏掉时**两个方向**
都要能被发现:

- **漏报**(该关未关被判成通过):issue 合并后继续悬着,下一个 agent 当没做完再干一遍
  (`#102` / `#466` 就是这么来的);
- **误报**(声明了不关单/已经写了 Closes 却被判红):红线一响就有人把它关掉。

所以下面每一组都成对出现。额外钉住三件容易退化的事:模板注释必须被忽略(否则「原样没动的
模板」会假通过)、`Refs #N` 必须给专门提示、参数冲突/读不出文件必须退出 2(判不出来 ≠ 通过)。
"""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import check_pr_closes


def evaluate(body: str) -> tuple[int, str, str]:
    """用临时文件走一遍真正的命令行入口。

    Args:
        body: PR 正文。

    Returns:
        ``(退出码, stdout, stderr)``。
    """
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "pr-body.md"
        path.write_text(body, encoding="utf-8")
        return call_main(["--body-file", str(path)])


def call_main(argv: list[str]) -> tuple[int, str, str]:
    """调 ``check_pr_closes.main`` 并收集退出码与两路输出。

    Args:
        argv: 命令行参数(不含程序名)。

    Returns:
        ``(退出码, stdout, stderr)``。
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = check_pr_closes.main(argv)
    return code, out.getvalue(), err.getvalue()


class PassesTests(unittest.TestCase):
    """该判绿的三类写法。"""

    def test_closes_with_number(self):
        """最基本的形态。"""
        code, out, _ = evaluate("## 关闭的 issue\n\nCloses #474\n")
        self.assertEqual(code, 0)
        self.assertIn("#474", out)

    def test_github_keyword_variants(self):
        """`Fixes` / `Resolves` 与大小写、冒号、多个编号都认。"""
        for body in (
            "Fixes #12",
            "resolves #7",
            "fixed: #8",
            "CLOSES #9 , closes #10",
        ):
            with self.subTest(body=body):
                self.assertEqual(evaluate(body)[0], 0)

    def test_reference_outside_section_still_counts(self):
        """关键词写在别的小节里也算 —— GitHub 认的是全文,不是某个小节。"""
        code, _, _ = evaluate("## 改了什么\n\n顺手 Closes #301。\n")
        self.assertEqual(code, 0)

    def test_explicit_no_issue(self):
        """确实不关单时,写「无」即通过。"""
        for word in ("无", "None", "n/a"):
            with self.subTest(word=word):
                code, out, _ = evaluate(f"## 关闭的 issue\n\n{word}\n\n## 改了什么\n\n文档整改\n")
                self.assertEqual(code, 0)
                self.assertIn("不关单", out)


class FailsTests(unittest.TestCase):
    """该判红的三类写法。"""

    def test_reference_only_is_red(self):
        """实测的失败形态:`Refs #466` 看着像关联,但不会关单。"""
        code, _, err = evaluate("## 关闭的 issue\n\nRefs #466\n")
        self.assertEqual(code, 1)
        self.assertIn("Refs", err)
        self.assertIn("#466", err)

    def test_unfilled_template_is_red(self):
        """原样提交的模板:示例活在 HTML 注释里,不能被当成本体声明。"""
        body = (
            "## 关闭的 issue\n\n"
            "<!-- 必填:写成 `Closes #<编号>`;确实不关任何 issue 的写「无」。 -->\n\n"
            "Closes #\n\n## 改了什么\n\n干点活\n"
        )
        code, _, err = evaluate(body)
        self.assertEqual(code, 1)
        self.assertIn("没有 Closes", err)

    def test_comment_hiding_a_keyword_is_ignored(self):
        """注释里的 `Closes #1` 不算(否则把要求注掉就能骗过门禁)。"""
        self.assertEqual(evaluate("<!-- Closes #1 -->\n\n干活\n")[0], 1)

    def test_empty_body_is_red(self):
        """空正文 / 只有注释。"""
        self.assertEqual(evaluate("")[0], 1)
        self.assertEqual(evaluate("<!-- nothing -->")[0], 1)

    def test_section_without_declaration_is_red(self):
        """「关闭的 issue」小节里既不写编号也不写「无」。"""
        self.assertEqual(evaluate("## 关闭的 issue\n\n呆会儿补\n")[0], 1)

    def test_plain_prose_is_red(self):
        """只写「这个 PR 关联 474」这种散文 —— 没有关键字,不认。"""
        self.assertEqual(evaluate("这个 PR 关联 474 号票。\n")[0], 1)


class UsageTests(unittest.TestCase):
    """判不出来时必须退出 2(不是 0,也不是 1)。"""

    def test_conflicting_sources(self):
        """`--event` 与 `--body-file` 同时给。"""
        code, _, err = call_main(["--event", "x.json", "--body-file", "y.md"])
        self.assertEqual(code, 2)
        self.assertIn("只能给一个", err)

    def test_unreadable_event_file(self):
        """事件文件不存在。"""
        code, _, err = call_main(["--event", "definitely-not-here.json"])
        self.assertEqual(code, 2)
        self.assertIn("读不出事件负载", err)

    def test_event_without_pull_request(self):
        """不是 pull_request 事件(没有 `pull_request.body`)。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "event.json"
            path.write_text(json.dumps({"ref": "refs/heads/main"}), encoding="utf-8")
            code, _, err = call_main(["--event", str(path)])
        self.assertEqual(code, 2)
        self.assertIn("pull_request", err)

    def test_unreadable_body_file(self):
        """正文文件不存在。"""
        code, _, err = call_main(["--body-file", "definitely-not-here.md"])
        self.assertEqual(code, 2)
        self.assertIn("读不出正文文件", err)


class EventPayloadTests(unittest.TestCase):
    """CI 走的是事件 JSON 这条路,单独验一次。"""

    def test_body_comes_from_event(self):
        """`pull_request.body` 里的 Closes 能被读到。"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "event.json"
            path.write_text(
                json.dumps({"pull_request": {"number": 475, "body": "Closes #474"}}),
                encoding="utf-8",
            )
            code, out, _ = call_main(["--event", str(path)])
        self.assertEqual(code, 0)
        self.assertIn("#474", out)


class TemplateTests(unittest.TestCase):
    """仓库里的 PR 模板本身必须还带着要求 —— 模板被删掉时这道门禁就没人知道了。"""

    def test_template_asks_for_closing_keyword(self):
        """`pull_request_template.md` 里要有 `Closes #` 的写法说明。"""
        template = (Path(__file__).resolve().parent.parent
                    / ".github" / "pull_request_template.md")
        text = template.read_text(encoding="utf-8")
        self.assertIn("Closes #", text)
        self.assertIn("无", text)


if __name__ == "__main__":
    unittest.main()
