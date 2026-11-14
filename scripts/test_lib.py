"""``scripts/lib/`` 与 ``scripts/releases.py`` 的自测(纯离线,临时目录造样本)。

为什么单独一份
--------------
第 5 节把四个发版脚本共用的东西收进 ``scripts/lib/``:常量(token / 仓库名 / API 基址)、
版本号读 / 写 / 比对、发版记录的解析与渲染、生成物比对语义。**这些是四个脚本的地基** ——
地基判错时四个脚本会一起静默走偏,而且没有第二份实现能对照(那正是本节要消灭的东西),
所以每一块都要有正反两面的用例:

- ``repo``:环境变量优先、token 文件回落、两处都没有时报错(文案里必须有路径与出处);
- ``version``:读版本名 / 构建号、写回只改目标行、三处比对;
- ``docs``:YAML 子集解析(含散文行)、渲染成旧表、``--check`` 的三种不一致、
  字段拼错 / 版本重复必须**判不出来**(而不是静默丢一列);
- ``artifacts``:与 HEAD 一致 / 不一致 / 不在 HEAD 里 / CRLF 与 LF 视为同一内容。

进 CI 的 ``contract`` 轨(``contract-lib-selftest``)。
"""

from __future__ import annotations

import contextlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import releases
from scripts.lib import artifacts, docs, repo, version

PUBSPEC_BODY = """name: chatapp_app
description: 演示
version: 1.0.13+13
environment:
  sdk: '>=3.0.0 <4.0.0'
"""

APP_INFO_BODY = """/// 应用展示信息。
const appDisplayName = '心跳';
const appVersion = '1.0.13';
"""

WEB_PACKAGE_BODY = """{
  "name": "chatapp-web",
  "version": "1.0.13",
  "scripts": {}
}
"""

RECORDS_BODY = """# 发版记录(样本)
- version: "1.0.13"
  date: "2026-11-11"
  tag: "v1.0.13"
  title: "v1.0.13 — R–W 六批"
  release: "https://example.com/r/1.0.13"
  note: ""
  asset: "chatapp-1.0.13.apk"
  asset_bytes: 61505970
  asset_sha1: "94f80d55f0d7f7ceb58cbcc2816c9760ae0b7691"
  deploy_sha: "e7456f6"

- version: "1.0.4"
  date: "2026-11-04"
  tag: "v1.0.4"
  title: ""
  release: ""
  note: "历史遗留:APK 构建产物已不可得,不补建(发版规则从 1.0.5 起真正执行)"
  asset: "chatapp-1.0.4.apk"
  asset_bytes: 0
  asset_sha1: ""
  deploy_sha: "ae7099f"

- version: "1.0.1"
  date: "2026-10-28"
  tag: ""
  title: ""
  release: ""
  note: "无(规则生效前发版)"
  asset: "chatapp-1.0.1.apk"
  asset_bytes: 0
  asset_sha1: ""
  deploy_sha: ""
"""

RELEASE_DOC_BODY = """# 发版与远端 Release

## 5. 发版记录(渲染物)

<!-- BEGIN generated:release-records -->
| 版本 | 日期 | tag | Release | 上线 SHA | APK |
|---|---|---|---|---|---|
<!-- END generated:release-records -->

## 6. 历史说明
"""


def _git(repo_path: Path, *args: str) -> str:
    """在临时仓库里跑一条 git 命令。

    Args:
        repo_path: 仓库目录。
        *args: git 参数。

    Returns:
        去空白的标准输出。

    Raises:
        AssertionError: 命令非零退出(自测环境坏了要立刻看出来)。
    """
    completed = subprocess.run(
        ["git", "-C", str(repo_path), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if completed.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} 失败:{completed.stderr}")
    return completed.stdout.strip()


def make_git_repo(root: Path) -> Path:
    """造一个只含一个提交的最小 git 仓库。

    Args:
        root: 临时目录(作为仓库根)。

    Returns:
        仓库根路径。
    """
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "tester")
    _git(root, "config", "commit.gpgsign", "false")
    return root


def make_release_root(root: Path) -> Path:
    """造一个「有 releases.yml + release.md」的最小仓库根。

    Args:
        root: 临时目录。

    Returns:
        仓库根路径(``docs/`` 与 ``docs/ops/`` 已建好,记录与手册已写入)。
    """
    (root / "docs" / "ops").mkdir(parents=True)
    (root / "docs" / "releases.yml").write_text(RECORDS_BODY, encoding="utf-8")
    (root / "docs" / "ops" / "release.md").write_text(RELEASE_DOC_BODY, encoding="utf-8")
    return root


def call_cli(main, argv: list[str]) -> tuple[int, str, str]:
    """调一个 CLI 的 ``main`` 并收集退出码与两路输出。

    Args:
        main: 入口函数(如 ``releases.main``)。
        argv: 命令行参数。

    Returns:
        ``(退出码, stdout, stderr)``。
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = main(argv)
    return code, out.getvalue(), err.getvalue()


class RepoLibTests(unittest.TestCase):
    """``scripts/lib/repo.py``:常量与 token 解析。"""

    def setUp(self):
        """清空两个 token 环境变量,保存原值以便还原。"""
        self._saved = {name: os.environ.get(name) for name in repo.TOKEN_ENV_VARS}
        for name in repo.TOKEN_ENV_VARS:
            os.environ.pop(name, None)

    def tearDown(self):
        """还原环境变量。"""
        for name, value in self._saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def test_constants_are_single_sourced(self):
        """仓库名 / API 基址 / token 文件路径只有一个定义处(本模块)。"""
        self.assertEqual(repo.DEFAULT_REPO, "shiliu153/chatapp")
        self.assertEqual(repo.API, "https://api.github.com")
        self.assertEqual(repo.UPLOAD_API, "https://uploads.github.com")
        self.assertEqual(repo.DEFAULT_TOKEN_FILE.name, "github-mcp-token.txt")
        self.assertEqual(repo.DEFAULT_TOKEN_FILE.parent.name, ".dsh")

    def test_env_var_wins_over_file(self):
        """环境变量优先:文件里的值不该被读到。"""
        with tempfile.TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "token.txt"
            token_file.write_text("from-file", encoding="utf-8")
            os.environ["GITHUB_TOKEN"] = "from-env"
            self.assertEqual(repo.resolve_token(token_file), "from-env")

    def test_personal_access_token_env_is_the_fallback_name(self):
        """``GITHUB_PERSONAL_ACCESS_TOKEN`` 也能用(与旧实现一致)。"""
        os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"] = "pat-env"
        self.assertEqual(repo.resolve_token(Path("unused")), "pat-env")

    def test_file_is_used_when_env_is_empty(self):
        """环境变量为空时回落到 token 文件(并去掉首尾空白)。"""
        with tempfile.TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "token.txt"
            token_file.write_text("  from-file\n", encoding="utf-8")
            self.assertEqual(repo.resolve_token(token_file), "from-file")

    def test_missing_token_reports_path_and_provenance(self):
        """两处都没有时必须报错,且文案里带路径与「与 mcp-github 同一个」的出处。"""
        with tempfile.TemporaryDirectory() as tmp:
            token_file = Path(tmp) / "token.txt"
            with self.assertRaises(repo.TokenError) as caught:
                repo.resolve_token(token_file)
            message = str(caught.exception)
            self.assertIn(str(token_file), message)
            self.assertIn("mcp-github", message)
            self.assertIn("GITHUB_TOKEN", message)


class VersionLibTests(unittest.TestCase):
    """``scripts/lib/version.py``:三处版本号的读 / 写 / 比对。"""

    def setUp(self):
        """造三份最小文件。"""
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.pubspec = root / "pubspec.yaml"
        self.app_info = root / "app_info.dart"
        self.web_package = root / "package.json"
        self.pubspec.write_text(PUBSPEC_BODY, encoding="utf-8")
        self.app_info.write_text(APP_INFO_BODY, encoding="utf-8")
        self.web_package.write_text(WEB_PACKAGE_BODY, encoding="utf-8")

    def tearDown(self):
        """删临时目录。"""
        self._tmp.cleanup()

    def test_reads_version_name_and_build(self):
        """版本名与构建号分开读,两种正则变体都在本模块。"""
        self.assertEqual(version.read_pubspec_version(self.pubspec), "1.0.13")
        self.assertEqual(
            version.read_pubspec_version_and_build(self.pubspec), ("1.0.13", 13))

    def test_missing_build_number_is_zero(self):
        """没有 ``+N`` 时构建号为 0。"""
        self.pubspec.write_text("name: x\nversion: 1.0.13\n", encoding="utf-8")
        self.assertEqual(
            version.read_pubspec_version_and_build(self.pubspec), ("1.0.13", 0))

    def test_missing_pubspec_raises_version_error(self):
        """读不到 pubspec 时抛 ``VersionError``(不是 SystemExit —— lib 不决定退出码)。"""
        with self.assertRaises(version.VersionError):
            version.read_pubspec_version(Path(self._tmp.name) / "nope.yaml")

    def test_consistent_files_have_no_mismatch(self):
        """三处一致时没有 mismatch。"""
        self.assertEqual(
            version.collect_mismatches(self.pubspec, self.app_info, self.web_package), [])

    def test_mismatch_names_file_and_fix(self):
        """不一致时点名文件,并给出修复命令。"""
        self.app_info.write_text(APP_INFO_BODY.replace("1.0.13", "1.0.12"), encoding="utf-8")
        problems = version.collect_mismatches(self.pubspec, self.app_info, self.web_package)
        self.assertTrue(any("app_info.dart" in problem for problem in problems), problems)
        self.assertTrue(any("sync_version.py --write" in problem for problem in problems))

    def test_write_updates_only_the_version_line(self):
        """写回只改目标行,其余内容原样保留。"""
        self.pubspec.write_text(PUBSPEC_BODY.replace("1.0.13", "1.1.0"), encoding="utf-8")
        self.assertTrue(version.write_app_info_version("1.1.0", self.app_info))
        self.assertTrue(version.write_web_version("1.1.0", self.web_package))
        self.assertEqual(
            version.collect_mismatches(self.pubspec, self.app_info, self.web_package), [])
        self.assertIn("const appDisplayName = '心跳';",
                      self.app_info.read_text(encoding="utf-8"))
        self.assertIn('"scripts": {}', self.web_package.read_text(encoding="utf-8"))
        self.assertIn("version: 1.1.0+13", self.pubspec.read_text(encoding="utf-8"))

    def test_write_is_noop_when_already_matching(self):
        """本来就是目标值时返回 False(不制造无意义的 diff)。"""
        self.assertFalse(version.write_app_info_version("1.0.13", self.app_info))
        self.assertFalse(version.write_web_version("1.0.13", self.web_package))

    def test_write_without_target_declaration_raises(self):
        """找不到 ``const appVersion`` 时抛错,而不是静默写坏文件。"""
        self.app_info.write_text("// 没有版本常量\n", encoding="utf-8")
        with self.assertRaises(version.VersionError):
            version.write_app_info_version("1.0.13", self.app_info)


class DocsLibTests(unittest.TestCase):
    """``scripts/lib/docs.py``:发版记录的解析 / 渲染 / 校验。"""

    def setUp(self):
        """解析一份含链接行与两种散文行的样本。"""
        self.records = docs.parse_records(RECORDS_BODY)

    def test_parses_all_fields(self):
        """字段逐个读出来(数字保持整数,便于渲染千分位)。"""
        latest = self.records[0]
        self.assertEqual(latest["version"], "1.0.13")
        self.assertEqual(latest["asset_bytes"], 61505970)
        self.assertEqual(latest["asset_sha1"], "94f80d55f0d7f7ceb58cbcc2816c9760ae0b7691")
        self.assertEqual(latest["deploy_sha"], "e7456f6")

    def test_prose_rows_are_preserved(self):
        """散文行(历史遗留 / 规则生效前发版)能原样还原,不被改写。"""
        cells = [docs.release_cell(record) for record in self.records]
        self.assertEqual(cells[0],
                         "[v1.0.13 — R–W 六批](https://example.com/r/1.0.13)"
                         "(附件 `chatapp-1.0.13.apk`,61,505,970 字节,"
                         "SHA-1 `94f80d55f0d7f7ceb58cbcc2816c9760ae0b7691`)")
        self.assertEqual(cells[1], "历史遗留:APK 构建产物已不可得,不补建(发版规则从 1.0.5 起真正执行)")
        self.assertEqual(cells[2], "无(规则生效前发版)")

    def test_render_table_uses_old_columns(self):
        """表头与列序必须与迁移前的旧表逐字一致(迁移对账靠它)。"""
        table = docs.render_table(self.records).splitlines()
        self.assertEqual(table[0], "| 版本 | 日期 | tag | Release | 上线 SHA | APK |")
        self.assertEqual(table[1], "|---|---|---|---|---|---|")
        self.assertTrue(table[2].startswith("| 1.0.13 | 2026-11-11 | `v1.0.13` |"))
        self.assertEqual(
            table[-1],
            "| 1.0.1 | 2026-10-28 | — | 无(规则生效前发版) | — | `chatapp-1.0.1.apk` |")

    def test_unknown_field_is_an_error(self):
        """字段拼错必须报错 —— 静默忽略等于「填了但没渲染」。"""
        with self.assertRaises(docs.DocsError):
            docs.parse_records('- version: "1.0.0"\n  date: "2026-01-01"\n  asset_byte: 1\n')

    def test_duplicate_version_is_an_error(self):
        """同一版本出现两次会让「当前版本有没有留痕」变得不可信。"""
        body = RECORDS_BODY + '\n- version: "1.0.13"\n  date: "2026-11-12"\n'
        with self.assertRaises(docs.DocsError):
            docs.parse_records(body)

    def test_missing_required_field_is_an_error(self):
        """缺 version / date 直接判不出来。"""
        with self.assertRaises(docs.DocsError):
            docs.parse_records('- version: "1.0.0"\n')

    def test_check_current_passes(self):
        """当前版本有行、tag 正确、Release 非空 → 通过。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "releases.yml"
            path.write_text(RECORDS_BODY, encoding="utf-8")
            self.assertEqual(docs.check_current("1.0.13", path), [])

    def test_check_current_reports_missing_version(self):
        """没有该版本时给出两条(现象 + 修复动作)。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "releases.yml"
            path.write_text(RECORDS_BODY, encoding="utf-8")
            problems = docs.check_current("9.9.9", path)
            self.assertTrue(any("没有 9.9.9" in problem for problem in problems), problems)
            self.assertTrue(any("releases.py --render" in problem for problem in problems))

    def test_check_current_reports_bad_tag(self):
        """tag 不含 ``v<版本>`` 时判红。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "releases.yml"
            path.write_text(RECORDS_BODY.replace('tag: "v1.0.13"', 'tag: "v1.0.12"'),
                            encoding="utf-8")
            problems = docs.check_current("1.0.13", path)
            self.assertTrue(any("应写成 `v1.0.13`" in problem for problem in problems), problems)

    def test_check_current_reports_empty_release(self):
        """Release 列为空时判红。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "releases.yml"
            body = RECORDS_BODY.replace(
                '  release: "https://example.com/r/1.0.13"\n  note: ""',
                '  release: ""\n  note: ""')
            path.write_text(body, encoding="utf-8")
            problems = docs.check_current("1.0.13", path)
            self.assertTrue(any("Release 为空" in problem for problem in problems), problems)

    def test_check_current_reports_pending_release(self):
        """「待建」不算留痕(1.0.4 的教训)。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "releases.yml"
            body = RECORDS_BODY.replace(
                '  release: "https://example.com/r/1.0.13"\n  note: ""',
                '  release: ""\n  note: "待建(等构建)"')
            path.write_text(body, encoding="utf-8")
            problems = docs.check_current("1.0.13", path)
            self.assertTrue(any("仍是「待建」" in problem for problem in problems), problems)

    def test_check_current_reports_missing_file(self):
        """记录文件不存在时给出「不存在」而不是抛栈。"""
        with tempfile.TemporaryDirectory() as tmp:
            problems = docs.check_current("1.0.13", Path(tmp) / "nope.yml")
            self.assertTrue(any("不存在" in problem for problem in problems), problems)

    def test_splice_requires_markers(self):
        """缺生成标记时判不出来(不能整文件乱写)。"""
        with self.assertRaises(docs.DocsError):
            docs.splice_block("# 没有标记\n", "body")

    def test_splice_follows_file_newline(self):
        """换行风格跟随原文件:CRLF 文件不能被写成整文件 LF(Windows 检出)。"""
        text = RELEASE_DOC_BODY.replace("\n", "\r\n")
        rendered = docs.splice_block(text, "| a | b |")
        self.assertIn("\r\n| a | b |\r\n", rendered)
        self.assertNotIn("\n| a | b |\n", rendered.replace("\r\n", ""))

    def test_write_then_check_roundtrip(self):
        """``write`` 之后 ``check`` 必须通过,且区间外的手写内容一字不动。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_release_root(Path(tmp))
            self.assertTrue(docs.write(root))
            self.assertEqual(docs.check(root), [])
            written = (root / "docs" / "ops" / "release.md").read_text(encoding="utf-8")
            self.assertIn("## 5. 发版记录(渲染物)", written)
            self.assertIn("## 6. 历史说明", written)
            self.assertFalse(docs.write(root))  # 再写一次不该有变化

    def test_check_reports_tampered_table(self):
        """手改渲染区间 → 判红,并指向 releases.yml。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_release_root(Path(tmp))
            docs.write(root)
            doc = root / "docs" / "ops" / "release.md"
            doc.write_text(
                doc.read_text(encoding="utf-8").replace("| 1.0.13 |", "| 9.9.9 |"),
                encoding="utf-8")
            problems = docs.check(root)
            self.assertTrue(any("releases.yml" in problem for problem in problems), problems)


class ArtifactsLibTests(unittest.TestCase):
    """``scripts/lib/artifacts.py``:与 HEAD 的比对语义(忽略行尾)。"""

    def setUp(self):
        """造一个提交了 ``gen.txt`` 的临时仓库。"""
        self._tmp = tempfile.TemporaryDirectory()
        self.root = make_git_repo(Path(self._tmp.name))
        (self.root / "gen.txt").write_text("a\nb\n", encoding="utf-8")
        _git(self.root, "add", "gen.txt")
        _git(self.root, "commit", "-q", "-m", "gen")

    def tearDown(self):
        """删临时目录。"""
        self._tmp.cleanup()

    def test_identical_content_passes(self):
        """内容相同 → ok。"""
        result = artifacts.compare("gen.txt", self.root)
        self.assertTrue(result.ok)
        self.assertEqual(result.problems, ())

    def test_crlf_and_lf_are_the_same_content(self):
        """Windows 检出(CRLF)与 HEAD(LF)必须视为一致 —— 这条判定以前在 WSL 里永远红。"""
        (self.root / "gen.txt").write_bytes(b"a\r\nb\r\n")
        self.assertTrue(artifacts.compare("gen.txt", self.root).ok)

    def test_different_content_fails_with_diff(self):
        """内容不同 → 判红,并给出前几十行 diff。"""
        (self.root / "gen.txt").write_text("a\nc\n", encoding="utf-8")
        result = artifacts.compare("gen.txt", self.root)
        self.assertFalse(result.ok)
        self.assertIn("与代码不一致", result.problems[0])
        self.assertIn("-b", result.diff)
        self.assertIn("+c", result.diff)

    def test_file_missing_from_head_is_reported(self):
        """新增但没提交的生成物 → 「不在 HEAD 里」(CI 会对不上)。"""
        (self.root / "new.txt").write_text("x\n", encoding="utf-8")
        result = artifacts.compare("new.txt", self.root)
        self.assertFalse(result.ok)
        self.assertIn("不在 HEAD 里", result.problems[0])

    def test_missing_working_file_is_reported(self):
        """HEAD 里有但工作区删了 → 判红,而不是抛栈。"""
        (self.root / "gen.txt").unlink()
        result = artifacts.compare("gen.txt", self.root)
        self.assertFalse(result.ok)
        self.assertIn("读不到", result.problems[0])

    def test_absolute_path_is_rejected(self):
        """绝对路径会让本地与 CI 比到不同文件,直接判不出来。"""
        with self.assertRaises(artifacts.ArtifactError):
            artifacts.compare(str(self.root / "gen.txt"), self.root)

    def test_not_a_repository_is_an_error(self):
        """不是 git 仓库 → 判不出来(2),不能冒充「生成物没提交」(1)。"""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(artifacts.ArtifactError):
                artifacts.compare("x.txt", Path(tmp))

    def test_cli_exit_codes(self):
        """CLI:0 一致 / 1 不一致 / 2 判不出来。"""
        code, out, _ = call_cli(artifacts.main, ["gen.txt", "--root", str(self.root)])
        self.assertEqual(code, 0)
        self.assertIn("生成物一致", out)

        (self.root / "gen.txt").write_text("changed\n", encoding="utf-8")
        code, _, err = call_cli(artifacts.main, ["gen.txt", "--root", str(self.root)])
        self.assertEqual(code, 1)
        self.assertIn("与代码不一致", err)

        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = call_cli(artifacts.main, ["x.txt", "--root", tmp])
            self.assertEqual(code, 2)
            self.assertIn("判不出来", err)


class ReleasesCliTests(unittest.TestCase):
    """``scripts/releases.py``:渲染 / 校验的退出码语义。"""

    def test_check_passes_after_render(self):
        """渲染后 ``--check`` 退出码 0。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_release_root(Path(tmp))
            code, _, _ = call_cli(releases.main, ["--root", str(root), "--render"])
            self.assertEqual(code, 0)
            code, out, _ = call_cli(releases.main, ["--root", str(root), "--check"])
            self.assertEqual(code, 0)
            self.assertIn("一致", out)

    def test_check_fails_before_render(self):
        """没渲染时 ``--check`` 退出码 1(生成物过期),并指向渲染命令。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_release_root(Path(tmp))
            code, out, _ = call_cli(releases.main, ["--root", str(root), "--check"])
            self.assertEqual(code, 1)
            self.assertIn("releases.py --render", out)

    def test_bad_yaml_exits_two(self):
        """YAML 判不出来 → 退出码 2(不是 0 也不是 1)。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_release_root(Path(tmp))
            (root / "docs" / "releases.yml").write_text("- version: [\n", encoding="utf-8")
            code, _, err = call_cli(releases.main, ["--root", str(root), "--check"])
            self.assertEqual(code, 2)
            self.assertIn("判不出来", err)

    def test_missing_markers_exits_two(self):
        """release.md 缺生成标记 → 判不出来。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_release_root(Path(tmp))
            (root / "docs" / "ops" / "release.md").write_text("# 无标记\n", encoding="utf-8")
            code, _, _ = call_cli(releases.main, ["--root", str(root), "--check"])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
