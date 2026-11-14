"""发版准备一条命令(L1 的「发版清单」那一半,2026-11-09 W 批)。

设计要点:
    ``docs/ops/release.md`` §3 的发版清单有 8 步,其中 **5 步是确定性的机械动作**,
    人每次都要照着抄命令、抄 SHA、抄版本号,漏一步的表现还很隐蔽(版本号三处不一致 /
    tag 指到未合并提交 / notes 少一节)。这里把它们收进一条命令:

        python scripts/release_prep.py --version 1.0.13 --topic "语音自我介绍等六批"

    它做四件事,全部**可逆、可重复**:

    1. **前置闸门** —— 工作区必须干净、当前分支必须是远端默认分支(``main``)、``HEAD`` 必须等于
       ``origin/main``。这三条挡的是「拿未合并提交发版」,即 release.md §3 那条
       「部署只认 ``origin/<默认分支>`` 的 SHA」的同一条纪律。
    2. **版本号三处** —— 写 ``app/pubspec.yaml`` 的 ``version: X.Y.Z+N``(构建号默认自增),
       再用 :mod:`scripts.lib.version` 的写原语写回 ``app_info.dart`` 与 ``web/package.json``
       (与 ``sync_version --write`` 是**同一份实现**,不再互相 import)。
    3. **门禁** —— 跑 :func:`scripts.lib.version.collect_mismatches`(必须为空);
       发版记录 ``docs/releases.yml`` 那一条**此时必然还没有**,所以它不算失败,
       而是把**可以直接粘贴的 YAML 记录**打出来,告诉人补在哪。
    4. **notes 草稿 + 待执行命令** —— 从上一个 tag 到 ``HEAD`` 的提交按
       ``feat`` / ``fix`` / 运维 分类,写成 ``.release-notes/v<版本>.md``;
        "再把 tag、``create_release.py``、``docs/releases.yml`` 的待填记录、部署清单**打印出来**。

**本脚本绝不执行**打 tag、建 Release、部署、构建 —— AGENTS.md 明令禁止 agent 做这些,
它们必须由人执行。脚本只负责把「该做什么」变成一串可以直接复制的命令。

用法与退出码::

    python scripts/release_prep.py --version 1.0.13 --topic "..." [选项]

    0  准备完成(dry-run 也是 0)
    1  前置闸门不过(脏工作区 / 分支不对 / 落后 origin / 版本号不合法)
    2  写完版本号后门禁仍不过(三处不一致 —— 说明 sync_version 自己坏了)

文件信息:
    文件名称          scripts/release_prep.py
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

import argparse
import datetime as _dt
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

# `python scripts/release_prep.py` 时 sys.path[0] 是 scripts/,显式把仓库根放进去,
# 这样 `from scripts.lib import version` 在直接跑与 unittest 两种方式下都成立(见 lib/__init__.py)。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import version as version_lib  # noqa: E402  (必须在 sys.path 修好之后)

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTES_DIR = REPO_ROOT / ".release-notes"
APK_PATH = "app/build/app/outputs/flutter-apk/app-release.apk"

# 提交主题前缀 → notes 小节。未命中的一律进「变更」。
NOTE_SECTIONS = ("新增", "变更", "修复", "运维注意")
PREFIX_SECTION = {
    "feat": "新增",
    "fix": "修复",
    "chore(release)": "运维注意",
    "docs(ops)": "运维注意",
    "ci": "运维注意",
    "build": "运维注意",
}
OPS_SECTION = "运维注意"
DEFAULT_SECTION = "变更"


class ReleasePrepError(Exception):
    """前置闸门或 git 操作失败;由 :func:`main` 转成退出码。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``raise ReleasePrepError(...)``

    备注信息:
        无特殊约束。
    """


@dataclass
class Plan:
    """一次发版准备的全部结果,便于 ``--dry-run`` 与自测断言。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``obj = Plan(...)``

    备注信息:
        version: 目标版本名,如 ``1.0.13``。
        build: 目标构建号(``+N`` 里的 N)。
        previous: 改动前的版本名(用于提示「从 X 升到 Y」)。
        sha: 将要被打 tag 的提交(``HEAD``)。
        notes_path: notes 草稿落盘路径。
        notes: notes 正文。
        groups: 提交按小节分类的结果。
        changed_files: 实际被写入的文件(相对仓库根)。
        warnings: 不阻塞的提示(fetch 失败等)。
    """

    version: str
    build: int
    previous: str
    sha: str
    notes_path: Path
    notes: str = ""
    groups: dict[str, list[str]] = field(default_factory=dict)
    changed_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# git 小工具
# --------------------------------------------------------------------------- #
def git(repo: Path, *args: str, check: bool = True) -> str:
    """在指定仓库里跑一条 git 命令。

    参数说明:
        repo: 仓库根目录。
        *args: 传给 git 的参数,如 ``("rev-parse", "HEAD")``。
        check: 为 ``True`` 时非零退出抛 :class:`ReleasePrepError`。

    返回参数:
        标准输出的去空白文本;``check=False`` 且命令失败时返回空串。

    使用示例:
        ``git(repo, *args, check=check)``

    备注信息:
        失败时抛 ``ReleasePrepError``,由调用方处理。
    """
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if completed.returncode != 0:
        if check:
            raise ReleasePrepError(
                f"git {' '.join(args)} 失败:{completed.stderr.strip() or completed.stdout.strip()}"
            )
        return ""
    return completed.stdout.strip()


def read_pubspec_version(path: Path = version_lib.PUBSPEC) -> tuple[str, int]:
    """读 ``app/pubspec.yaml`` 的版本名与构建号。

    参数说明:
        path: pubspec 路径,默认仓库里的那一份。

    返回参数:
        ``(版本名, 构建号)``;没有 ``+N`` 时构建号为 ``0``。

    使用示例:
        ``read_pubspec_version(path)``

    备注信息:
        抛 ``ReleasePrepError``:文件读不到或找不到 ``version:`` 行。
    """
    try:
        return version_lib.read_pubspec_version_and_build(path)
    except version_lib.VersionError as error:
        raise ReleasePrepError(str(error)) from error


def version_tuple(version: str) -> tuple[int, ...]:
    """把 ``1.0.13`` 解析成可比较的整数元组。

    参数说明:
        version: 版本名,如 ``1.0.13``。

    返回参数:
        整数元组 ``(1, 0, 13)``。

    使用示例:
        ``version_tuple(version)``

    备注信息:
        抛 ``ReleasePrepError``:版本名不是纯数字点分形式。
    """
    parts = version.split(".")
    if not parts or not all(part.isdigit() for part in parts):
        raise ReleasePrepError(f"版本名必须是纯数字点分形式(例:1.0.13),收到 {version!r}")
    return tuple(int(part) for part in parts)


# --------------------------------------------------------------------------- #
# 1. 前置闸门
# --------------------------------------------------------------------------- #
def remote_default_branch(repo: Path) -> str:
    """返回远端默认分支名(``main`` 优先,回退 ``master``)。

    参数说明:
        repo: 仓库根目录。

    返回参数:
        分支名,例如 ``"main"``;两个 ref 都不存在时返回 ``"main"``。

    使用示例:
        ``remote_default_branch(repo)``

    备注信息:
        默认分支 2026-11-11 由 ``master`` 改名成 ``main``。把分支名写死会让发版闸门在改名后
        永远报「拿不到 origin/master」—— 而闸门挂掉的表现是「发不了版」,人只会以为网络坏了。
        所以这里按本地 remote-tracking ref 判一次(纯本地,不发网络请求)。
    """
    for candidate in ("main", "master"):
        if git(repo, "rev-parse", "--verify", "--quiet",
               f"refs/remotes/origin/{candidate}", check=False):
            return candidate
    return "main"


def check_preconditions(repo: Path, allow_branch: str | None, fetch: bool,
                        warnings: list[str]) -> str:
    """校验「现在能不能发版」,并返回将要被打 tag 的 ``HEAD``。

    参数说明:
        repo: 仓库根目录。
        allow_branch: 允许的分支名;``None`` 表示必须是远端默认分支(当前是 ``main``)。
        fetch: 是否先 ``git fetch origin``(失败只记 warning,不阻断)。
        warnings: 收集不阻塞提示的列表(原地追加)。

    返回参数:
        当前 ``HEAD`` 的完整 SHA。

    使用示例:
        ``check_preconditions(repo, allow_branch, fetch, warnings)``

    备注信息:
        抛 ``ReleasePrepError``:脏工作区 / 分支不对 / ``HEAD`` 与 ``origin/<默认分支>`` 不一致。
    """
    dirty = git(repo, "status", "--porcelain")
    if dirty:
        raise ReleasePrepError(
            "工作区不干净,先提交或 stash:\n"
            + "\n".join(f"  {line}" for line in dirty.splitlines()[:10])
        )

    if fetch:
        try:
            git(repo, "fetch", "--quiet", "origin")
        except ReleasePrepError as error:
            warnings.append(f"git fetch 失败,改用本地 origin/<默认分支> 判定:{error}")

    # fetch 之后再认分支名:改名后的第一次运行要靠本次拉下来的 ref 才认得 ``main``。
    base = remote_default_branch(repo)
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    expected_branch = allow_branch or base
    if branch != expected_branch:
        raise ReleasePrepError(f"当前分支是 {branch},发版必须在 {expected_branch} 上进行")

    sha = git(repo, "rev-parse", "HEAD")
    remote = git(repo, "rev-parse", f"origin/{base}", check=False)
    if not remote:
        raise ReleasePrepError(f"拿不到 origin/{base} —— 至少先 git fetch origin 一次")
    if sha != remote:
        raise ReleasePrepError(
            f"HEAD {sha[:7]} 与 origin/{base} {remote[:7]} 不一致;"
            f"发版只认 origin/{base} 的 SHA,先 pull --ff-only 或等 CI 合并"
        )
    return sha


# --------------------------------------------------------------------------- #
# 2. 版本号三处
# --------------------------------------------------------------------------- #
def bump_version(repo: Path, version: str, build: int | None, dry_run: bool) -> list[str]:
    """把版本号写进三处(``pubspec.yaml`` 是事实来源)。

    参数说明:
        repo: 仓库根目录。
        version: 目标版本名。
        build: 目标构建号;``None`` 表示在当前构建号上 +1。
        dry_run: 为 ``True`` 时只计算不落盘。

    返回参数:
        被改动文件的相对路径列表(dry-run 时为「将会改动」的列表)。

    使用示例:
        ``bump_version(repo, version, build, dry_run)``

    备注信息:
        抛 ``ReleasePrepError``:目标版本不高于当前版本,或文件里找不到版本行。
    """
    current, current_build = read_pubspec_version(repo / "app" / "pubspec.yaml")
    if version_tuple(version) <= version_tuple(current):
        raise ReleasePrepError(
            f"目标版本 {version} 不高于当前 {current};版本号只能往上走"
        )
    target_build = current_build + 1 if build is None else build
    if target_build <= current_build:
        raise ReleasePrepError(
            f"目标构建号 {target_build} 不高于当前 {current_build};构建号只能往上走"
        )

    changed: list[str] = []
    pubspec_path = repo / "app" / "pubspec.yaml"
    text = pubspec_path.read_text(encoding="utf-8")
    updated = version_lib.PUBSPEC_VERSION_BUILD_RE.sub(
        f"version: {version}+{target_build}", text, count=1)
    if updated != text:
        changed.append("app/pubspec.yaml")
        if not dry_run:
            pubspec_path.write_text(updated, encoding="utf-8")

    app_info_path = repo / "app" / "lib" / "core" / "app_info.dart"
    web_package_path = repo / "web" / "package.json"
    if dry_run:
        if version_lib.read_app_info_version(app_info_path) != version:
            changed.append("app/lib/core/app_info.dart")
        if version_lib.read_web_version(web_package_path) != version:
            changed.append("web/package.json")
        return changed

    if version_lib.write_app_info_version(version, app_info_path):
        changed.append("app/lib/core/app_info.dart")
    if version_lib.write_web_version(version, web_package_path):
        changed.append("web/package.json")
    return changed


def check_gates(repo: Path, version: str) -> list[str]:
    """跑两道门禁,返回问题列表(空表示通过)。

    参数说明:
        repo: 仓库根目录。
        version: 刚写入的版本名。

    返回参数:
        逐条中文问题描述。

    使用示例:
        ``check_gates(repo, version)``

    备注信息:
        无特殊约束。
    """
    try:
        return version_lib.collect_mismatches(
            repo / "app" / "pubspec.yaml",
            repo / "app" / "lib" / "core" / "app_info.dart",
            repo / "web" / "package.json",
        )
    except version_lib.VersionError as error:
        return [str(error)]


# --------------------------------------------------------------------------- #
# 3. notes 草稿
# --------------------------------------------------------------------------- #
def classify(subject: str) -> str:
    """按提交主题的前缀决定它进哪个 notes 小节。

    参数说明:
        subject: 提交主题,如 ``feat(app): 语音自我介绍 (#201)``。

    返回参数:
        小节名:``新增`` / ``变更`` / ``修复`` / ``运维注意``。

    使用示例:
        ``classify(subject)``

    备注信息:
        无特殊约束。
    """
    match = re.match(r"^([a-z]+)(\([^)]*\))?!?:", subject)
    if not match:
        return DEFAULT_SECTION
    kind, scope = match.group(1), (match.group(2) or "")
    return PREFIX_SECTION.get(f"{kind}{scope}", PREFIX_SECTION.get(kind, DEFAULT_SECTION))


def collect_notes(repo: Path, from_ref: str) -> dict[str, list[str]]:
    """把 ``from_ref..HEAD`` 的提交按小节分类。

    参数说明:
        repo: 仓库根目录。
        from_ref: 起点(上一个 tag 或任意 ref);空串表示用全部历史。

    返回参数:
        小节名 → 提交主题列表;四个小节都保证存在(可能为空列表)。

    使用示例:
        ``collect_notes(repo, from_ref)``

    备注信息:
        无特殊约束。
    """
    rng = f"{from_ref}..HEAD" if from_ref else "HEAD"
    subjects = git(repo, "log", "--no-merges", "--pretty=%s", rng)
    groups: dict[str, list[str]] = {name: [] for name in NOTE_SECTIONS}
    for subject in subjects.splitlines():
        subject = subject.strip()
        if not subject:
            continue
        groups[classify(subject)].append(subject)
    return groups


def render_notes(version: str, topic: str, groups: dict[str, list[str]],
                 date: str, sha: str) -> str:
    """渲染 notes 草稿(结构见 ``docs/ops/release.md`` §4)。

    参数说明:
        version: 版本名。
        topic: 一句话主题。
        groups: :func:`collect_notes` 的结果。
        date: 发版日期 ``YYYY-MM-DD``。
        sha: 上线 SHA。

    返回参数:
        Markdown 正文。

    使用示例:
        ``render_notes(version, topic, groups, date, sha)``

    备注信息:
        无特殊约束。
    """
    lines = [
        f"# v{version} — {topic}",
        "",
        f"> 自动生成于 {date};准备时 HEAD `{sha}`。**上线 SHA 以「版本号改动合并后」的提交为准**,",
        "> 不要用准备时的 HEAD —— 那时版本号还没提交。发布前请人工补全标了「待确认」的项,",
        "> 并把空小节删掉(不要留「无」的空壳)。",
        "",
    ]
    for name in NOTE_SECTIONS:
        if name == OPS_SECTION:
            continue  # 运维注意固定放最后:先列本批运维类提交,再接「待确认」项
        items = groups.get(name) or []
        if not items:
            continue
        lines.append(f"## {name}")
        lines.append("")
        lines.extend(f"- {item}" for item in items)
        lines.append("")
    lines.extend(["## 运维注意", ""])
    lines.extend(f"- {item}" for item in (groups.get(OPS_SECTION) or []))
    lines.extend([
        "- 迁移:待确认(看各 PR 正文;有则写「先 `migrate` 再重启」)",
        "- `MIN_APP_VERSION` 是否变动:待确认(只升 App 会让整站被「需要更新」挡住)",
        "",
        "## 验证",
        "",
        "- `scripts/verify.sh all` 全绿(四栈)",
        "- 生产冒烟:`/api/v1/app/config` 版本正确、APK 下载 206、`/health` 与 `/readyz` 200",
        "",
        "## 附件校验",
        "",
        f"- `chatapp-{version}.apk` SHA-1:构建后填",
        "",
    ])
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 4. 待执行命令
# --------------------------------------------------------------------------- #
def next_commands(version: str, topic: str, sha: str, notes_path: Path,
                  date: str) -> str:
    """把「人接下来要执行的命令」拼成可直接复制的文本(**不执行**)。

    参数说明:
        version: 版本名。
        topic: 一句话主题。
        sha: 上线 SHA(完整)。
        notes_path: notes 草稿路径。
        date: 发版日期。

    返回参数:
        多行命令清单。

    使用示例:
        ``next_commands(version, topic, sha, notes_path, date)``

    备注信息:
        无特殊约束。
    """
    try:
        notes_display = notes_path.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        notes_display = str(notes_path)
    return "\n".join([
        "以下 5 步必须由人执行(本脚本不代做):",
        "",
        "1) 构建(APK 必须带 ERROR_REPORTING=true;Web 必须重新 build)",
        "   cd app && ../flutter/bin/flutter.bat build apk --release \\",
        "     --dart-define=API_BASE=https://chat.shiliu153.cn/api/v1 \\",
        "     --dart-define=ERROR_REPORTING=true",
        "   cd web && npm run build",
        "",
        "2) **先把上面三处版本号提交并合并**(本脚本不提交),再打 tag ——",
        "   tag 必须指向「版本号改动合并后」的那个 SHA,不能指向准备时的 HEAD",
        f"   (准备时 HEAD = {sha[:7]},它还不含本次版本号)。",
        f"   git tag -a v{version} -m \"{topic}\" <版本号合并后的 SHA>",
        f"   git push origin v{version}",
        "",
        "3) 建 / 更新 Release(幂等;同名附件先删后传;tag 不存在会直接拒绝)",
        f"   python scripts/create_release.py --title \"v{version} — {topic}\" \\",
        f"     --notes-file {notes_display} --apk {APK_PATH} \\",
        f"     --asset-name chatapp-{version}.apk",
        "",
        "4) 在 docs/releases.yml 加一条记录(发版记录的唯一事实来源),再渲染回 release.md:",
        "   # 追加到 docs/releases.yml 末尾(字段含义见文件头部注释):",
        "   - version: \"{version}\"".format(version=version),
        "     date: \"{date}\"".format(date=date),
        "     tag: \"v{version}\"".format(version=version),
        "     title: \"v{version} — {topic}\"".format(version=version, topic=topic),
        "     release: \"<Release 链接>\"",
        "     asset: \"chatapp-{version}.apk\"".format(version=version),
        "     asset_bytes: 0",
        "     asset_sha1: \"<构建后填>\"",
        "     deploy_sha: \"<合并后的短 SHA>\"",
        "     note: \"\"",
        "   python scripts/releases.py --render",
        "",
        "5) 部署前跑闸门(默认分支 + CI 全绿),再执行 dist 覆盖 / APK 上传 / .env 三个变量 / 重启 web:",
        "   python scripts/deploy_gate.py",
        "   清单见 docs/ops/release.md §3 步骤 4 / 步骤 8",
        "",
        f"全部做完后:`python scripts/sync_version.py --check` 应退出码 0",
    ])


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def prepare(repo: Path, version: str, topic: str, build: int | None,
            from_ref: str | None, fetch: bool, allow_branch: str | None,
            dry_run: bool) -> Plan:
    """跑完整的发版准备流程(纯函数式,便于自测)。

    参数说明:
        repo: 仓库根目录。
        version: 目标版本名。
        topic: 一句话主题。
        build: 目标构建号;``None`` 表示自增。
        from_ref: notes 的起点;``None`` 表示上一个 tag。
        fetch: 是否先 fetch。
        allow_branch: 允许的分支名。
        dry_run: 只计算不落盘。

    返回参数:
        :class:`Plan`。

    使用示例:
        ``prepare(repo, version, topic, build, from_ref, fetch, allow_branch, dry_run)``

    备注信息:
        抛 ``ReleasePrepError``:任一闸门不过。
    """
    plan = Plan(version=version, build=0, previous="", sha="",
                notes_path=repo / ".release-notes" / f"v{version}.md")
    plan.sha = check_preconditions(repo, allow_branch, fetch, plan.warnings)
    plan.previous, current_build = read_pubspec_version(repo / "app" / "pubspec.yaml")
    plan.build = current_build + 1 if build is None else build

    plan.changed_files = bump_version(repo, version, build, dry_run)

    if not from_ref:
        from_ref = git(repo, "describe", "--tags", "--abbrev=0", "HEAD", check=False)
    plan.groups = collect_notes(repo, from_ref or "")
    date = _dt.date.today().isoformat()
    plan.notes = render_notes(version, topic, plan.groups, date, plan.sha)

    if not dry_run:
        plan.notes_path.parent.mkdir(parents=True, exist_ok=True)
        plan.notes_path.write_text(plan.notes, encoding="utf-8")
    return plan


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    参数说明:
        argv: 命令行参数;``None`` 表示取 ``sys.argv[1:]``。

    返回参数:
        退出码:0 准备完成,1 闸门不过,2 写完版本号后门禁仍不过。

    使用示例:
        ``python scripts/release_prep.py --version 1.0.13 --topic "语音自我介绍等六批"``

    备注信息:
        无特殊约束。
    """
    parser = argparse.ArgumentParser(
        description="发版准备一条命令:前置闸门 + 版本号三处 + 门禁 + notes 草稿 + 待执行命令",
    )
    parser.add_argument("--version", required=True, help="目标版本名,如 1.0.13")
    parser.add_argument("--topic", required=True, help="一句话主题(进 notes 标题与 tag 消息)")
    parser.add_argument("--build", type=int, help="构建号(+N);默认在当前值上自增")
    parser.add_argument("--from", dest="from_ref", help="notes 起点 ref;默认上一个 tag")
    parser.add_argument("--repo", type=Path, default=REPO_ROOT, help="仓库根;默认本仓库")
    parser.add_argument("--allow-branch", help="允许的分支名;默认只允许远端默认分支(main)")
    parser.add_argument("--no-fetch", action="store_true", help="不先 git fetch origin")
    parser.add_argument("--dry-run", action="store_true", help="只打印计划,不写任何文件")
    args = parser.parse_args(argv)

    try:
        plan = prepare(
            repo=args.repo.resolve(), version=args.version, topic=args.topic,
            build=args.build, from_ref=args.from_ref, fetch=not args.no_fetch,
            allow_branch=args.allow_branch, dry_run=args.dry_run,
        )
    except ReleasePrepError as error:
        print(f"[发版准备] 中止:{error}", file=sys.stderr)
        return 1

    for warning in plan.warnings:
        print(f"[发版准备] 警告:{warning}")

    head = "将改动" if args.dry_run else "已改动"
    print(f"[发版准备] 版本 {plan.previous} → {plan.version}+{plan.build};"
          f"{head} {len(plan.changed_files)} 个文件")
    for path in plan.changed_files:
        print(f"  - {path}")

    problems = check_gates(args.repo.resolve(), plan.version)
    if problems and not args.dry_run:
        for problem in problems:
            print(f"[发版准备] 门禁:{problem}", file=sys.stderr)
        print("[发版准备] 版本号三处仍不一致 —— sync_version 自己出问题了,先修它",
              file=sys.stderr)
        return 2

    counts = ", ".join(f"{name} {len(items)}" for name, items in plan.groups.items() if items)
    print(f"[发版准备] notes 草稿:{plan.notes_path}"
          f"{'(dry-run 未落盘)' if args.dry_run else ''}")
    print(f"[发版准备] 提交分类:{counts or '(上个 tag 之后没有提交)'}")
    print("[发版准备] 发版记录 docs/releases.yml 此时必然还没有本版本这一条 —— 补在步骤 4")
    print("")
    print(next_commands(plan.version, args.topic, plan.sha, plan.notes_path,
                        _dt.date.today().isoformat()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
