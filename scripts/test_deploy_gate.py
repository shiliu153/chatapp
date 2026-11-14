"""``scripts/deploy_gate.py`` 的自测(纯函数,不联网)。

进 CI 的 contract 轨:部署闸门是「main 红了还能上线」那类事故的唯一机械防线,
它自己坏掉时必须有人知道。

文件信息:
    文件名称          scripts/test_deploy_gate.py
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

import unittest

from scripts import deploy_gate


def run(name: str, status: str = "completed", conclusion: str | None = "success") -> dict:
    """造一条 check run 记录。

    参数说明:
        name: check 名称。
        status: ``completed`` / ``in_progress`` 等。
        conclusion: 结论;``None`` 表示未完成。

    返回参数:
        GitHub check-runs API 形状的字典。

    使用示例:
        ``run(name, status, conclusion)``

    备注信息:
        无特殊约束。
    """
    return {"name": name, "status": status, "conclusion": conclusion}


class EvaluateTests(unittest.TestCase):
    """``evaluate`` 的判定口径。"""

    def test_all_success_passes(self):
        """全部 success 时没有问题。

        参数说明:
            无。
        """
        self.assertEqual(deploy_gate.evaluate([run("backend"), run("web")]), [])

    def test_empty_is_rejected(self):
        """0 个 check run 必须拒绝(「没有 check」≠「绿」)。

        参数说明:
            无。
        """
        problems = deploy_gate.evaluate([])
        self.assertEqual(len(problems), 1)
        self.assertIn("没有任何 check run", problems[0])

    def test_failure_is_reported(self):
        """一个失败就拒绝,并点名是哪个 check。

        参数说明:
            无。
        """
        problems = deploy_gate.evaluate([run("backend"), run("web", conclusion="failure")])
        self.assertEqual(len(problems), 1)
        self.assertIn("web", problems[0])
        self.assertIn("failure", problems[0])

    def test_pending_is_reported(self):
        """未完成的 check 不算通过。

        参数说明:
            无。
        """
        problems = deploy_gate.evaluate([run("app-ui", status="in_progress", conclusion=None)])
        self.assertEqual(len(problems), 1)
        self.assertIn("尚未完成", problems[0])

    def test_neutral_and_skipped_pass(self):
        """neutral / skipped 与 GitHub required check 语义一致,视为通过。

        参数说明:
            无。
        """
        self.assertEqual(
            deploy_gate.evaluate([
                run("a", conclusion="neutral"),
                run("b", conclusion="skipped"),
            ]),
            [],
        )

    def test_cancelled_is_rejected(self):
        """cancelled / timed_out / stale 都不算绿。

        参数说明:
            无。
        """
        for conclusion in ("cancelled", "timed_out", "stale", "action_required"):
            problems = deploy_gate.evaluate([run("x", conclusion=conclusion)])
            self.assertEqual(len(problems), 1, conclusion)


class AncestryTests(unittest.TestCase):
    """``is_ancestor`` 的 git 语义(用临时仓库验证,不碰本仓库)。"""

    def test_ancestor_and_non_ancestor(self):
        """main 上的提交是祖先;分叉后的提交不是。

        参数说明:
            无。
        """
        import subprocess
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                   "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}

            def g(*args: str) -> str:
                completed = subprocess.run(
                    ["git", "-C", str(repo), *args], capture_output=True, text=True, env={**__import__("os").environ, **env}
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                return completed.stdout.strip()

            g("init", "-q", "-b", "main")
            (repo / "a.txt").write_text("a", encoding="utf-8")
            g("add", ".")
            g("commit", "-q", "-m", "first")
            first = g("rev-parse", "HEAD")
            g("update-ref", "refs/remotes/origin/main", first)
            self.assertTrue(deploy_gate.is_ancestor(repo, first, "main"))

            g("checkout", "-q", "-b", "side")
            (repo / "b.txt").write_text("b", encoding="utf-8")
            g("add", ".")
            g("commit", "-q", "-m", "side")
            side = g("rev-parse", "HEAD")
            self.assertFalse(deploy_gate.is_ancestor(repo, side, "main"))


if __name__ == "__main__":
    unittest.main()
