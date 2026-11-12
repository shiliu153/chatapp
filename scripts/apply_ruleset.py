"""给默认分支的 ruleset 加 required status checks(P0 审计的 P1-4)。

为什么要有它
------------
``.github/workflows/*.yml`` 只是「CI 会跑」,GitHub 本身**不要求任何 check 通过**:
2026-11-12 之前 ruleset 里只有 ``deletion`` / ``non_fast_forward`` / ``pull_request``,
``required_approving_review_count`` 还是 0。于是「CI 全绿才合并」纯靠人。

这个脚本把 contract / backend / web 三条轨设成必需检查。**前置条件**:
这三条 workflow 必须已经去掉 ``paths`` 过滤(同一次改动里做了),否则不触发时
check 不出现,PR 会永久 pending。

用法::

    python scripts/apply_ruleset.py --dry-run    # 先看将写入的 JSON(默认)
    python scripts/apply_ruleset.py --apply      # 真写

退出码:0 成功(或 dry-run);1 失败;2 用法/环境错误。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_TOKEN_FILE = Path.home() / ".dsh" / "github-mcp-token.txt"
DEFAULT_REPO = "shiliu153/chatapp"
DEFAULT_RULESET_NAME = "默认分支(main): 必须走 PR + 禁强推"
API = "https://api.github.com"
#: required check 的 context = **check run 的 name**(GitHub Actions 里就是 job 的
#: ``name:`` 字段),不是 ``workflow / job`` 拼接。三个 job 已显式命名为
#: contract / backend / web(见各自 yml),避免 ``test`` 这种通用名与其它轨重名。
REQUIRED_CONTEXTS = [
    "contract",
    "backend",
    "web",
]


class RulesetError(Exception):
    """无法完成设置;由 main 转成退出码。"""


def read_token() -> str:
    """取 GitHub token(环境变量优先,其次 DSH token 文件)。

    Returns:
        PAT 字符串。

    Raises:
        RulesetError: 两处都没有。
    """
    for name in ("GITHUB_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN"):
        value = os.environ.get(name, "").strip()
        if value:
            return value
    if DEFAULT_TOKEN_FILE.exists():
        value = DEFAULT_TOKEN_FILE.read_text(encoding="utf-8").strip()
        if value:
            return value
    raise RulesetError("找不到 GitHub token:设 GITHUB_TOKEN 或写 ~/.dsh/github-mcp-token.txt")


def request(method: str, url: str, token: str, payload: dict | None = None) -> tuple[int, dict]:
    """发一次 GitHub API 请求。

    Args:
        method: HTTP 方法。
        url: 完整 URL。
        token: GitHub PAT。
        payload: JSON body。

    Returns:
        ``(状态码, 解析后的 JSON)``;空响应体返回 ``{}``。
    """
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "chatapp-ruleset")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            text = response.read().decode("utf-8")
            return response.status, (json.loads(text) if text.strip() else {})
    except urllib.error.HTTPError as error:
        text = error.read().decode("utf-8", "replace")
        try:
            return error.code, json.loads(text)
        except ValueError:
            return error.code, {"message": text}


def find_ruleset(repo: str, name: str, token: str) -> dict:
    """找到目标 ruleset 的完整定义。

    Args:
        repo: ``owner/name``。
        name: ruleset 名称(精确匹配)。
        token: GitHub PAT。

    Returns:
        ruleset 详情 JSON。

    Raises:
        RulesetError: 找不到或查询失败。
    """
    status, listing = request("GET", f"{API}/repos/{repo}/rulesets", token)
    if status != 200:
        raise RulesetError(f"列 rulesets 失败:{status} {listing.get('message', '')}")
    match = next((item for item in listing if item.get("name") == name), None)
    if match is None:
        names = ", ".join(item.get("name", "?") for item in listing) or "(空)"
        raise RulesetError(f"找不到名为「{name}」的 ruleset;现有:{names}")
    status, detail = request("GET", f"{API}/repos/{repo}/rulesets/{match['id']}", token)
    if status != 200:
        raise RulesetError(f"读 ruleset 失败:{status} {detail.get('message', '')}")
    return detail


def merge_required_checks(detail: dict, contexts: list[str]) -> dict:
    """在 ruleset 详情上追加/替换 required_status_checks 规则。

    只改 ``rules`` 里的这一条,其余(conditions / bypass_actors / enforcement)原样保留。

    Args:
        detail: GET ruleset 的返回体。
        contexts: 必需的 check context 列表;空列表表示**移除**这条规则。

    Returns:
        可直接 PUT 的 body。
    """
    rules = [rule for rule in detail.get("rules", []) if rule.get("type") != "required_status_checks"]
    if contexts:
        rules.append({
            "type": "required_status_checks",
            "parameters": {
                # strict=false:不要求 PR 分支必须基于最新 main,否则每个 PR 都要 rebase。
                "strict_required_status_checks_policy": False,
                "required_status_checks": [{"context": context} for context in contexts],
            },
        })
    body = {
        "name": detail["name"],
        "target": detail.get("target", "branch"),
        "enforcement": detail.get("enforcement", "active"),
        "conditions": detail.get("conditions", {}),
        "rules": rules,
    }
    if detail.get("bypass_actors"):
        body["bypass_actors"] = detail["bypass_actors"]
    return body


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    Args:
        argv: 参数列表;``None`` 表示取 ``sys.argv[1:]``。

    Returns:
        0 成功;1 失败;2 环境错误。
    """
    parser = argparse.ArgumentParser(description="给默认分支 ruleset 加 required status checks")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="owner/name")
    parser.add_argument("--name", default=DEFAULT_RULESET_NAME, help="ruleset 名称")
    parser.add_argument("--apply", action="store_true", help="真写;默认只 dry-run")
    parser.add_argument("--dry-run", action="store_true", help="显式 dry-run(与默认行为相同)")
    parser.add_argument("--remove", action="store_true",
                        help="移除 required_status_checks(回滚用;其余规则原样保留)")
    parser.add_argument("--context", action="append", help="覆盖必需 check(可重复)")
    args = parser.parse_args(argv)

    contexts = [] if args.remove else (args.context or REQUIRED_CONTEXTS)
    try:
        token = read_token()
        detail = find_ruleset(args.repo, args.name, token)
        body = merge_required_checks(detail, contexts)
        print(f"[ruleset] id={detail['id']} name={detail['name']}")
        print("[ruleset] 将写入的规则:")
        print(json.dumps(body, ensure_ascii=False, indent=2))
        if not args.apply:
            print("[ruleset] dry-run:未写入。确认无误后加 --apply")
            return 0
        status, result = request(
            "PUT", f"{API}/repos/{args.repo}/rulesets/{detail['id']}", token, body)
        if status not in (200, 201):
            print(f"[ruleset] 写入失败:{status} {result.get('message', '')}", file=sys.stderr)
            return 1
        print("[ruleset] 已写入 required status checks")
        return 0
    except RulesetError as error:
        print(f"[ruleset] 错误:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
