"""部署闸门:确认「要上线的那个 SHA」真的来自默认分支、且它的 CI 是绿的。

为什么需要它
------------
``README.md`` §8 与 ``docs/ops/release.md`` 都写着「部署只认 ``origin/main`` 的 SHA」,
但那是**人的纪律**:2026-11-11 的 1.0.13 就是在 ``main`` 的 web 轨已经红着的情况下
完成上线的(P0 审计记录)。纪律没有机械执行 = 没有纪律。

这个脚本把那条纪律变成一条命令:部署前跑一次,不过就别上。

它查三件事
----------
1. 目标 SHA 是 ``origin/<默认分支>`` 的**祖先或相等**(禁止拿未合并提交上线);
2. 该 SHA 上**至少有 1 个 check run**(paths 过滤会把不相关的轨整个跳过 ——
   「没有 check」不等于「CI 绿」);
3. 所有 check run 都已完成,且结论 ∈ {success, neutral, skipped}。

用法::

    python scripts/deploy_gate.py                 # 查 origin/main 的 HEAD
    python scripts/deploy_gate.py --sha e7456f6   # 查指定提交(部署脚本里用)
    python scripts/deploy_gate.py --offline       # 只做 git 侧校验,不查 GitHub

退出码:0 通过;1 不通过(原因逐条打印);2 用法/环境错误。

仓库名 / API 基址 / token 文件与解析逻辑住在 ``scripts/lib/repo.py``(2026-11-14 治理第 5 节:
这四个 GitHub 常量以前在四个脚本里各抄一份,见 ``sources-of-truth.md`` §4 C7)。

文件信息:
    文件名称          scripts/deploy_gate.py
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
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# `python scripts/deploy_gate.py` 时 sys.path[0] 是 scripts/,显式把仓库根放进去,
# 这样 `from scripts.lib import repo` 在直接跑与 unittest 两种方式下都成立(见 lib/__init__.py)。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import repo as lib_repo  # noqa: E402  (必须在 sys.path 修好之后)

REPO_ROOT = Path(__file__).resolve().parent.parent
#: 这些结论视为「通过」。``skipped`` 是 GitHub 在 job 级 if 跳过时给的值,
#: 在「required check」语义里也算通过,这里与 GitHub 保持一致。
OK_CONCLUSIONS = frozenset({"success", "neutral", "skipped"})


class GateError(Exception):
    """无法完成校验(用法错 / 网络错 / 拿不到 token);由 main 转成退出码 2。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``raise GateError(...)``

    备注信息:
        无特殊约束。
    """


def git(repo: Path, *args: str, check: bool = True) -> str:
    """在仓库里跑一条 git 命令。

    参数说明:
        repo: 仓库根目录。
        *args: 传给 git 的参数。
        check: 为 True 时非零退出抛 :class:`GateError`。

    返回参数:
        标准输出(去空白);``check=False`` 且失败时返回空串。

    使用示例:
        ``git(repo, *args, check=check)``

    备注信息:
        失败时抛 ``GateError``,由调用方处理。
    """
    completed = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if completed.returncode != 0:
        if check:
            raise GateError(
                f"git {' '.join(args)} 失败:{completed.stderr.strip() or completed.stdout.strip()}"
            )
        return ""
    return completed.stdout.strip()


def resolve_target_sha(repo: Path, branch: str, sha: str | None) -> str:
    """确定要校验的目标 SHA。

    参数说明:
        repo: 仓库根目录。
        branch: 默认分支名(如 ``main``)。
        sha: 显式指定的提交;``None`` 表示用 ``origin/<branch>``。

    返回参数:
        完整 SHA。

    使用示例:
        ``resolve_target_sha(repo, branch, sha)``

    备注信息:
        抛 ``GateError``:拿不到目标 ref。
    """
    if sha:
        full = git(repo, "rev-parse", "--verify", f"{sha}^{{commit}}", check=False)
        if not full:
            raise GateError(f"找不到提交 {sha}")
        return full
    full = git(repo, "rev-parse", "--verify", f"refs/remotes/origin/{branch}", check=False)
    if not full:
        raise GateError(f"拿不到 origin/{branch} —— 先 git fetch origin")
    return full


def is_ancestor(repo: Path, sha: str, branch: str) -> bool:
    """判断 ``sha`` 是否属于 ``origin/<branch>`` 的历史。

    参数说明:
        repo: 仓库根目录。
        sha: 目标提交。
        branch: 默认分支名。

    返回参数:
        True 表示是祖先或相等(可以部署)。

    使用示例:
        ``is_ancestor(repo, sha, branch)``

    备注信息:
        无特殊约束。
    """
    completed = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", sha, f"origin/{branch}"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return completed.returncode == 0


def read_token() -> str:
    """按优先级取 GitHub token(环境变量优先,其次 DSH 的 token 文件)。

    参数说明:
        无。

    返回参数:
        PAT 字符串。

    使用示例:
        ``read_token()``

    备注信息:
        抛 ``GateError``:两处都没有。
    """
    try:
        return lib_repo.resolve_token()
    except lib_repo.TokenError as error:
        raise GateError(f"{error};只想做 git 侧校验可加 --offline") from error


def fetch_check_runs(repo_slug: str, sha: str, token: str) -> list[dict]:
    """拉取某个提交上的全部 check run(自动翻页)。

    参数说明:
        repo_slug: ``owner/name``。
        sha: 提交 SHA。
        token: GitHub PAT。

    返回参数:
        check run 列表。

    使用示例:
        ``fetch_check_runs(repo_slug, sha, token)``

    备注信息:
        抛 ``GateError``:网络错误或非 2xx。
    """
    runs: list[dict] = []
    page = 1
    while True:
        url = (
            f"{lib_repo.API}/repos/{repo_slug}/commits/{urllib.parse.quote(sha)}/check-runs"
            f"?per_page=100&page={page}"
        )
        request = urllib.request.Request(url)
        request.add_header("Authorization", f"Bearer {token}")
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("User-Agent", "chatapp-deploy-gate")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise GateError(f"查询 check-runs 失败:HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise GateError(f"查询 check-runs 失败:{error.reason}") from error
        batch = payload.get("check_runs") or []
        runs.extend(batch)
        if len(batch) < 100:
            return runs
        page += 1


def evaluate(check_runs: list[dict]) -> list[str]:
    """判定 check run 集合是否允许部署。

    参数说明:
        check_runs: GitHub check-runs API 返回的 ``check_runs`` 列表。

    返回参数:
        问题描述列表;空列表表示通过。

    使用示例:
        ``evaluate(check_runs)``

    备注信息:
        无特殊约束。
    """
    if not check_runs:
        return [
            "该提交上没有任何 check run —— 「没有 check」不等于「CI 绿」,"
            "可能是 paths 过滤把整条轨跳过了,或 workflow 没触发",
        ]
    problems: list[str] = []
    for run in check_runs:
        name = run.get("name") or "?"
        status = run.get("status")
        conclusion = run.get("conclusion")
        if status != "completed":
            problems.append(f"{name}:尚未完成(status={status})")
            continue
        if conclusion not in OK_CONCLUSIONS:
            problems.append(f"{name}:结论是 {conclusion}")
    return problems


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    参数说明:
        argv: 参数列表;``None`` 表示取 ``sys.argv[1:]``。

    返回参数:
        0 通过;1 不通过;2 用法/环境错误。

    使用示例:
        ``python scripts/deploy_gate.py``

    备注信息:
        无特殊约束。
    """
    parser = argparse.ArgumentParser(description="部署闸门:默认分支 + CI 绿")
    parser.add_argument("--repo", default=lib_repo.DEFAULT_REPO, help="owner/name")
    parser.add_argument("--branch", default="main", help="默认分支名,默认 main")
    parser.add_argument("--sha", help="要校验的提交;默认 origin/<branch>")
    parser.add_argument("--offline", action="store_true", help="只做 git 侧校验,不查 GitHub")
    parser.add_argument("--dir", type=Path, default=REPO_ROOT, help="仓库根,默认本仓库")
    args = parser.parse_args(argv)

    try:
        repo = args.dir.resolve()
        target = resolve_target_sha(repo, args.branch, args.sha)
        print(f"[deploy-gate] 目标提交 {target[:12]}(origin/{args.branch})")
        if not is_ancestor(repo, target, args.branch):
            print(
                f"[deploy-gate] 拒绝:{target[:12]} 不在 origin/{args.branch} 的历史里 —— "
                "只部署合并后的提交",
                file=sys.stderr,
            )
            return 1
        print(f"[deploy-gate] 属于 origin/{args.branch} ✓")
        if args.offline:
            print("[deploy-gate] --offline:跳过 GitHub check 校验(不能证明 CI 绿)")
            return 0
        token = read_token()
        problems = evaluate(fetch_check_runs(args.repo, target, token))
        if problems:
            print("[deploy-gate] 拒绝:CI 不是全绿", file=sys.stderr)
            for problem in problems:
                print(f"  - {problem}", file=sys.stderr)
            return 1
        print("[deploy-gate] CI 全绿 ✓ 可以部署")
        print("[deploy-gate] 别忘了先记回滚点:旧 SHA / 旧镜像 tag / .env 备份")
        return 0
    except GateError as error:
        print(f"[deploy-gate] 错误:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
