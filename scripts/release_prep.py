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
       再调 :mod:`scripts.sync_version` 写回 ``app_info.dart`` 与 ``web/package.json``。
    3. **门禁** —— 跑 :func:`scripts.sync_version.collect_mismatches`(必须为空);
       发版记录 ``docs/ops/release.md`` §5 那一行**此时必然还没有**,所以它不算失败,
       而是把**可以直接粘贴的表格行**打出来,告诉人补在哪。
    4. **notes 草稿 + 待执行命令** —— 从上一个 tag 到 ``HEAD`` 的提交按
       ``feat`` / ``fix`` / 运维 分类,写成 ``.release-notes/v<版本>.md``;
       再把 tag、``create_release.py``、§5 行、部署清单**打印出来**。

**本脚本绝不执行**打 tag、建 Release、部署、构建 —— AGENTS.md 明令禁止 agent 做这些,
它们必须由人执行。脚本只负责把「该做什么」变成一串可以直接复制的命令。

用法与退出码::

    python scripts/release_prep.py --version 1.0.13 --topic "..." [选项]

    0  准备完成(dry-run 也是 0)
    1  前置闸门不过(脏工作区 / 分支不对 / 落后 origin / 版本号不合法)
    2  写完版本号后门禁仍不过(三处不一致 —— 说明 sync_version 自己坏了)
"""

from __future__ import annotations

import argparse
import datetime as _dt
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:  # `python -m scripts.release_prep` 与 CI 里的 unittest 走这条
    from scripts import sync_version
except ImportError:  # 直接 `python scripts/release_prep.py` 时 sys.path[0] 是 scripts/ 目录
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from scripts import sync_version

REPO_ROOT = Path(__file__).resolve().parent.parent
PUBSPEC = REPO_ROOT / "app" / "pubspec.yaml"
NOTES_DIR = REPO_ROOT / ".release-notes"
APK_PATH = "app/build/app/outputs/flutter-apk/app-release.apk"

# ``version: 1.0.12+12`` —— 版本名与可选构建号
PUBSPEC_VERSION_RE = re.compile(r"^version:\s*([0-9][^\s+]*)(?:\+(\d+))?", re.MULTILINE)

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
    """前置闸门或 git 操作失败;由 :func:`main` 转成退出码。"""


@dataclass
class Plan:
    """一次发版准备的全部结果,便于 ``--dry-run`` 与自测断言。

    Attributes:
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

    Args:
        repo: 仓库根目录。
        *args: 传给 git 的参数,如 ``("rev-parse", "HEAD")``。
        check: 为 ``True`` 时非零退出抛 :class:`ReleasePrepError`。

    Returns:
        标准输出的去空白文本;``check=False`` 且命令失败时返回空串。
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


def read_pubspec_version(path: Path = PUBSPEC) -> tuple[str, int]:
    """读 ``app/pubspec.yaml`` 的版本名与构建号。

    Args:
        path: pubspec 路径,默认仓库里的那一份。

    Returns:
        ``(版本名, 构建号)``;没有 ``+N`` 时构建号为 ``0``。

    Raises:
        ReleasePrepError: 文件读不到或找不到 ``version:`` 行。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise ReleasePrepError(f"读不到 {path}:{error}") from error
    match = PUBSPEC_VERSION_RE.search(text)
    if not match:
        raise ReleasePrepError(f"{path} 里找不到 version: 行")
    return match.group(1), int(match.group(2) or 0)


def version_tuple(version: str) -> tuple[int, ...]:
    """把 ``1.0.13`` 解析成可比较的整数元组。

    Args:
        version: 版本名,如 ``1.0.13``。

    Returns:
        整数元组 ``(1, 0, 13)``。

    Raises:
        ReleasePrepError: 版本名不是纯数字点分形式。
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

    默认分支 2026-11-11 由 ``master`` 改名成 ``main``。把分支名写死会让发版闸门在改名后
    永远报「拿不到 origin/master」—— 而闸门挂掉的表现是「发不了版」,人只会以为网络坏了。
    所以这里按本地 remote-tracking ref 判一次(纯本地,不发网络请求)。

    Args:
        repo: 仓库根目录。

    Returns:
        分支名,例如 ``"main"``;两个 ref 都不存在时返回 ``"main"``。
    """
    for candidate in ("main", "master"):
        if git(repo, "rev-parse", "--verify", "--quiet",
               f"refs/remotes/origin/{candidate}", check=False):
            return candidate
    return "main"


def check_preconditions(repo: Path, allow_branch: str | None, fetch: bool,
                        warnings: list[str]) -> str:
    """校验「现在能不能发版」,并返回将要被打 tag 的 ``HEAD``。

    Args:
        repo: 仓库根目录。
        allow_branch: 允许的分支名;``None`` 表示必须是远端默认分支(当前是 ``main``)。
        fetch: 是否先 ``git fetch origin``(失败只记 warning,不阻断)。
        warnings: 收集不阻塞提示的列表(原地追加)。

    Returns:
        当前 ``HEAD`` 的完整 SHA。

    Raises:
        ReleasePrepError: 脏工作区 / 分支不对 / ``HEAD`` 与 ``origin/<默认分支>`` 不一致。
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

    Args:
        repo: 仓库根目录。
        version: 目标版本名。
        build: 目标构建号;``None`` 表示在当前构建号上 +1。
        dry_run: 为 ``True`` 时只计算不落盘。

    Returns:
        被改动文件的相对路径列表(dry-run 时为「将会改动」的列表)。

    Raises:
        ReleasePrepError: 目标版本不高于当前版本,或文件里找不到版本行。
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
    updated = PUBSPEC_VERSION_RE.sub(f"version: {version}+{target_build}", text, count=1)
    if updated != text:
        changed.append("app/pubspec.yaml")
        if not dry_run:
            pubspec_path.write_text(updated, encoding="utf-8")

    app_info_path = repo / "app" / "lib" / "core" / "app_info.dart"
    web_package_path = repo / "web" / "package.json"
    if dry_run:
        if sync_version.read_app_info_version(app_info_path) != version:
            changed.append("app/lib/core/app_info.dart")
        if sync_version.read_web_version(web_package_path) != version:
            changed.append("web/package.json")
        return changed

    if sync_version.write_app_info_version(version, app_info_path):
        changed.append("app/lib/core/app_info.dart")
    if sync_version.write_web_version(version, web_package_path):
        changed.append("web/package.json")
    return changed


def check_gates(repo: Path, version: str) -> list[str]:
    """跑两道门禁,返回问题列表(空表示通过)。

    Args:
        repo: 仓库根目录。
        version: 刚写入的版本名。

    Returns:
        逐条中文问题描述。
    """
    return sync_version.collect_mismatches(
        repo / "app" / "pubspec.yaml",
        repo / "app" / "lib" / "core" / "app_info.dart",
        repo / "web" / "package.json",
    )


# --------------------------------------------------------------------------- #
# 3. notes 草稿
# --------------------------------------------------------------------------- #
def classify(subject: str) -> str:
    """按提交主题的前缀决定它进哪个 notes 小节。

    Args:
        subject: 提交主题,如 ``feat(app): 语音自我介绍 (#201)``。

    Returns:
        小节名:``新增`` / ``变更`` / ``修复`` / ``运维注意``。
    """
    match = re.match(r"^([a-z]+)(\([^)]*\))?!?:", subject)
    if not match:
        return DEFAULT_SECTION
    kind, scope = match.group(1), (match.group(2) or "")
    return PREFIX_SECTION.get(f"{kind}{scope}", PREFIX_SECTION.get(kind, DEFAULT_SECTION))


def collect_notes(repo: Path, from_ref: str) -> dict[str, list[str]]:
    """把 ``from_ref..HEAD`` 的提交按小节分类。

    Args:
        repo: 仓库根目录。
        from_ref: 起点(上一个 tag 或任意 ref);空串表示用全部历史。

    Returns:
        小节名 → 提交主题列表;四个小节都保证存在(可能为空列表)。
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

    Args:
        version: 版本名。
        topic: 一句话主题。
        groups: :func:`collect_notes` 的结果。
        date: 发版日期 ``YYYY-MM-DD``。
        sha: 上线 SHA。

    Returns:
        Markdown 正文。
    """
    lines = [
        f"# v{version} — {topic}",
        "",
        f"> 自动生成于 {date},上线 SHA `{sha}`。**发布前请人工补全标了「待确认」的项**,",
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

    Args:
        version: 版本名。
        topic: 一句话主题。
        sha: 上线 SHA(完整)。
        notes_path: notes 草稿路径。
        date: 发版日期。

    Returns:
        多行命令清单。
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
        "2) 打 tag 并推送(tag 必须指向合并后的 SHA)",
        f"   git tag -a v{version} -m \"{topic}\" {sha}",
        f"   git push origin v{version}",
        "",
        "3) 建 / 更新 Release(幂等;同名附件先删后传)",
        f"   python scripts/create_release.py --title \"v{version} — {topic}\" \\",
        f"     --notes-file {notes_display} --apk {APK_PATH} \\",
        f"     --asset-name chatapp-{version}.apk",
        "",
        "4) 在 docs/ops/release.md §5 记录表加一行(补完 Release 链接后再跑 --check)",
        f"   | {version} | {date} | `v{version}` | <Release 链接> | `{sha[:7]}` | `chatapp-{version}.apk` |",
        "",
        "5) 部署(dist 覆盖 + APK 上传 + .env 三个变量 + 重启 web)与生产冒烟",
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

    Args:
        repo: 仓库根目录。
        version: 目标版本名。
        topic: 一句话主题。
        build: 目标构建号;``None`` 表示自增。
        from_ref: notes 的起点;``None`` 表示上一个 tag。
        fetch: 是否先 fetch。
        allow_branch: 允许的分支名。
        dry_run: 只计算不落盘。

    Returns:
        :class:`Plan`。

    Raises:
        ReleasePrepError: 任一闸门不过。
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

    Args:
        argv: 命令行参数;``None`` 表示取 ``sys.argv[1:]``。

    Returns:
        退出码:0 准备完成,1 闸门不过,2 写完版本号后门禁仍不过。
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
    print("[发版准备] 发版记录 §5 此时必然还没有本版本这一行 —— 补在步骤 4")
    print("")
    print(next_commands(plan.version, args.topic, plan.sha, plan.notes_path,
                        _dt.date.today().isoformat()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
