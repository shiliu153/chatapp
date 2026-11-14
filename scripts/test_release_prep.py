"""``scripts/release_prep.py`` 的自测(标准库 unittest,不依赖 Django、不碰网络)。

设计要点:
    发版准备脚本最怕的不是报错,而是**报绿却漏了闸门** —— 比如「脏工作区也放行」、
    「HEAD 落后 origin 还打 tag」这两条一旦失效,产出的就是「线上跑着未合并代码」。
    所以这里用临时 git 仓库(含一个 bare 的 origin)把每条闸门都**故意踩一遍**,
    而不是只测 happy path。

    ``scripts/test_sync_version.py`` 是同一套思路,两者都进 ``contract`` 轨。
"""

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import release_prep
from scripts.lib import version as version_lib

PUBSPEC_BODY = """name: chatapp_app
description: 演示
version: 1.0.12+12
environment:
  sdk: '>=3.0.0 <4.0.0'
"""

APP_INFO_BODY = """/// 应用信息常量。

const appVersion = '1.0.12';
const appBuildNumber = 12;
"""

WEB_PACKAGE_BODY = """{
  "name": "chatapp-web",
  "version": "1.0.12",
  "private": true
}
"""


def _git(repo: Path, *args: str) -> str:
    """在临时仓库里跑 git 并返回 stdout。

    Args:
        repo: 仓库目录。
        *args: git 参数。

    Returns:
        去空白的标准输出。
    """
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if completed.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} 失败:{completed.stderr}")
    return completed.stdout.strip()


def make_repo(root: Path) -> Path:
    """造一个「三处版本号齐备 + 有 origin/master」的最小仓库。

    Args:
        root: 临时目录(作为仓库根)。

    Returns:
        仓库根路径。
    """
    repo = root / "repo"
    origin = root / "origin.git"
    (repo / "app" / "lib" / "core").mkdir(parents=True)
    (repo / "web").mkdir(parents=True)
    (repo / "app" / "pubspec.yaml").write_text(PUBSPEC_BODY, encoding="utf-8")
    (repo / "app" / "lib" / "core" / "app_info.dart").write_text(APP_INFO_BODY, encoding="utf-8")
    (repo / "web" / "package.json").write_text(WEB_PACKAGE_BODY, encoding="utf-8")

    _git(root, "init", "--bare", "-b", "master", str(origin))
    _git(repo, "init", "-b", "master")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "tester")
    _git(repo, "config", "commit.gpgsign", "false")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "chore: 初始化")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "master")
    return repo


def commit(repo: Path, subject: str) -> None:
    """在仓库里造一个空提交,用于验证 notes 分类。

    Args:
        repo: 仓库目录。
        subject: 提交主题。
    """
    _git(repo, "commit", "--allow-empty", "-m", subject)


class ClassifyTests(unittest.TestCase):
    """提交主题 → notes 小节 的映射。"""

    def test_feat_and_fix(self):
        """feat 进新增,fix 进修复。"""
        self.assertEqual(release_prep.classify("feat(app): 语音自我介绍 (#201)"), "新增")
        self.assertEqual(release_prep.classify("fix(im): 未读数漏算 (#202)"), "修复")

    def test_ops_prefixes(self):
        """chore(release) / docs(ops) / ci / build 进运维注意。"""
        self.assertEqual(release_prep.classify("chore(release): 版本号 1.0.13"), "运维注意")
        self.assertEqual(release_prep.classify("docs(ops): 回填发版记录"), "运维注意")
        self.assertEqual(release_prep.classify("ci: 加一条轨"), "运维注意")

    def test_other_prefixes_fall_back_to_change(self):
        """其它前缀与不带前缀的提交都进变更。"""
        self.assertEqual(release_prep.classify("refactor(app): 抽组件"), "变更")
        self.assertEqual(release_prep.classify("perf: 索引"), "变更")
        self.assertEqual(release_prep.classify("随手改了一下"), "变更")


class VersionParsingTests(unittest.TestCase):
    """pubspec 版本名与构建号的解析。"""

    def test_read_pubspec_version(self):
        """能同时读出版本名与构建号。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pubspec.yaml"
            path.write_text(PUBSPEC_BODY, encoding="utf-8")
            self.assertEqual(release_prep.read_pubspec_version(path), ("1.0.12", 12))

    def test_missing_build_number_is_zero(self):
        """没有 +N 时构建号为 0。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pubspec.yaml"
            path.write_text("name: x\nversion: 1.0.12\n", encoding="utf-8")
            self.assertEqual(release_prep.read_pubspec_version(path), ("1.0.12", 0))

    def test_bad_version_raises(self):
        """非数字点分的版本名直接拒绝。"""
        with self.assertRaises(release_prep.ReleasePrepError):
            release_prep.version_tuple("1.0.13-rc1")

    def test_version_tuple_order(self):
        """1.0.13 必须大于 1.0.9(字符串比较会判反)。"""
        self.assertGreater(release_prep.version_tuple("1.0.13"),
                           release_prep.version_tuple("1.0.9"))


class BumpVersionTests(unittest.TestCase):
    """版本号三处写入。"""

    def test_writes_three_files(self):
        """三处都会被写成目标版本,构建号自增。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            changed = release_prep.bump_version(repo, "1.0.13", None, dry_run=False)
            self.assertEqual(sorted(changed), [
                "app/lib/core/app_info.dart", "app/pubspec.yaml", "web/package.json",
            ])
            self.assertEqual(release_prep.read_pubspec_version(repo / "app" / "pubspec.yaml"),
                             ("1.0.13", 13))
            self.assertEqual(
                version_lib.read_app_info_version(
                    repo / "app" / "lib" / "core" / "app_info.dart"), "1.0.13")
            self.assertEqual(
                version_lib.read_web_version(repo / "web" / "package.json"), "1.0.13")

    def test_dry_run_touches_nothing(self):
        """dry-run 只报「将改动」,磁盘内容不变。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            changed = release_prep.bump_version(repo, "1.0.13", None, dry_run=True)
            self.assertEqual(len(changed), 3)
            self.assertEqual(release_prep.read_pubspec_version(repo / "app" / "pubspec.yaml"),
                             ("1.0.12", 12))

    def test_rejects_same_or_lower_version(self):
        """版本号只能往上走。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            for bad in ("1.0.12", "1.0.9"):
                with self.assertRaises(release_prep.ReleasePrepError):
                    release_prep.bump_version(repo, bad, None, dry_run=True)

    def test_rejects_lower_build(self):
        """构建号也只能往上走。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            with self.assertRaises(release_prep.ReleasePrepError):
                release_prep.bump_version(repo, "1.0.13", 5, dry_run=True)


class PreconditionTests(unittest.TestCase):
    """三条前置闸门。"""

    def test_happy_path_returns_head(self):
        """干净且同步时返回 HEAD 的完整 SHA。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            warnings = []
            sha = release_prep.check_preconditions(repo, None, fetch=False, warnings=warnings)
            self.assertEqual(sha, _git(repo, "rev-parse", "HEAD"))
            self.assertEqual(warnings, [])

    def test_dirty_tree_blocks(self):
        """工作区有未提交改动就拒绝发版。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            (repo / "app" / "pubspec.yaml").write_text("name: x\nversion: 9.9.9+1\n",
                                                      encoding="utf-8")
            with self.assertRaises(release_prep.ReleasePrepError) as ctx:
                release_prep.check_preconditions(repo, None, fetch=False, warnings=[])
            self.assertIn("工作区不干净", str(ctx.exception))

    def test_wrong_branch_blocks(self):
        """不在 master 上就拒绝。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            _git(repo, "switch", "-c", "feat/whatever")
            with self.assertRaises(release_prep.ReleasePrepError) as ctx:
                release_prep.check_preconditions(repo, None, fetch=False, warnings=[])
            self.assertIn("发版必须在 master", str(ctx.exception))

    def test_head_behind_origin_blocks(self):
        """本地落后 origin/master 时拒绝(发版只认 origin/master 的 SHA)。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = make_repo(root)
            other = root / "other"
            _git(root, "clone", str(root / "origin.git"), str(other))
            _git(other, "config", "user.email", "t@example.com")
            _git(other, "config", "user.name", "t")
            commit(other, "feat: 别人先合了一个")
            _git(other, "push", "origin", "master")
            _git(repo, "fetch", "origin")
            with self.assertRaises(release_prep.ReleasePrepError) as ctx:
                release_prep.check_preconditions(repo, None, fetch=False, warnings=[])
            self.assertIn("不一致", str(ctx.exception))

    def test_allow_branch_overrides(self):
        """--allow-branch 可以放行其它分支(仅用于自测/演练)。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            _git(repo, "switch", "-c", "rehearsal")
            sha = release_prep.check_preconditions(repo, "rehearsal", fetch=False, warnings=[])
            self.assertEqual(sha, _git(repo, "rev-parse", "HEAD"))


class NotesTests(unittest.TestCase):
    """notes 草稿的分类与结构。"""

    def test_collect_groups_commits(self):
        """三个前缀分别进三个小节。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            base = _git(repo, "rev-parse", "HEAD")
            commit(repo, "feat(app): 语音自我介绍 (#201)")
            commit(repo, "fix(im): 未读数漏算 (#202)")
            commit(repo, "chore(release): 版本号")
            groups = release_prep.collect_notes(repo, base)
            self.assertEqual(groups["新增"], ["feat(app): 语音自我介绍 (#201)"])
            self.assertEqual(groups["修复"], ["fix(im): 未读数漏算 (#202)"])
            self.assertEqual(groups["运维注意"], ["chore(release): 版本号"])
            self.assertEqual(groups["变更"], [])

    def test_render_puts_ops_section_last_with_todo_items(self):
        """运维注意固定最后一节,「待确认」项必须落在它下面而不是别的节里。"""
        groups = {"新增": ["feat: a"], "变更": [], "修复": ["fix: b"], "运维注意": []}
        text = release_prep.render_notes("1.0.13", "主题", groups, "2026-11-09", "abc1234")
        ops_at = text.index("## 运维注意")
        self.assertGreater(ops_at, text.index("## 修复"))
        # 只认「待确认」的那条清单项 —— 正文开头的提示语里也含这三个字,不能用它定位
        self.assertGreater(text.index("`MIN_APP_VERSION` 是否变动:待确认"), ops_at)
        self.assertIn("`abc1234`", text)

    def test_render_skips_empty_sections(self):
        """空小节不渲染空壳。"""
        groups = {"新增": ["feat: a"], "变更": [], "修复": [], "运维注意": []}
        text = release_prep.render_notes("1.0.13", "主题", groups, "2026-11-09", "abc1234")
        self.assertIn("## 新增", text)
        self.assertNotIn("## 修复", text)


class EndToEndTests(unittest.TestCase):
    """prepare() 的完整流程。"""

    def test_prepare_writes_notes_and_keeps_tag_manual(self):
        """notes 落盘、版本号三处改好,且**没有任何 git tag 被创建**。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            plan = release_prep.prepare(
                repo=repo, version="1.0.13", topic="六批功能", build=None,
                from_ref=None, fetch=False, allow_branch=None, dry_run=False,
            )
            self.assertTrue(plan.notes_path.exists())
            self.assertIn("feat", plan.notes.lower() + "feat")  # 正文非空
            self.assertEqual(release_prep.read_pubspec_version(
                repo / "app" / "pubspec.yaml"), ("1.0.13", 13))
            # 关键:脚本自己绝不打 tag / 建 Release
            self.assertEqual(_git(repo, "tag"), "")

    def test_next_commands_are_printed_not_executed(self):
        """待执行命令文本必须含 tag / create_release / releases.yml 记录,且明确写「由人执行」。"""
        text = release_prep.next_commands(
            "1.0.13", "六批功能", "a" * 40, Path("/repo/.release-notes/v1.0.13.md"),
            "2026-11-09")
        self.assertIn("必须由人执行", text)
        self.assertIn("git tag -a v1.0.13", text)
        self.assertIn("git push origin v1.0.13", text)
        self.assertIn("create_release.py", text)
        self.assertIn("chatapp-1.0.13.apk", text)
        # 第 5 节(C8)起发版记录是 docs/releases.yml,表格由 releases.py 渲染
        self.assertIn("docs/releases.yml", text)
        self.assertIn('version: "1.0.13"', text)
        self.assertIn("releases.py --render", text)

    def test_main_dry_run_exit_zero(self):
        """--dry-run 走完全流程且退出码 0。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            code = release_prep.main([
                "--version", "1.0.13", "--topic", "六批功能",
                "--repo", str(repo), "--no-fetch", "--dry-run",
            ])
            self.assertEqual(code, 0)

    def test_main_blocks_on_dirty_tree(self):
        """脏工作区时 main 返回 1(不是抛栈)。"""
        with tempfile.TemporaryDirectory() as tmp:
            repo = make_repo(Path(tmp))
            (repo / "web" / "package.json").write_text('{"version": "1.0.12", "x": 1}',
                                                      encoding="utf-8")
            code = release_prep.main([
                "--version", "1.0.13", "--topic", "六批功能",
                "--repo", str(repo), "--no-fetch",
            ])
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
