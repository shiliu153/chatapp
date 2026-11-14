"""把 ``AUTOMERGE_TOKEN`` 写进仓库 secret(libsodium sealed box 加密)。

为什么需要这个 secret
--------------------
``auto-merge.yml`` 优先用 ``secrets.AUTOMERGE_TOKEN`` 合并 PR。用 **PAT** 合并会触发
默认分支上的 ``push`` 轨(二次确认);用 ``GITHUB_TOKEN`` 合并则**不会**触发 ——
2026-11-12 核对时仓库 secrets 为空,所以那条二次确认一直是缺失的。

为什么不用现有的 classic PAT
---------------------------
本机 ``~/.dsh/github-mcp-token.txt`` 那个是 classic PAT(``repo`` 全权限)。把它放进
Actions secret 等于把「能改 workflow / 能发 Release」的凭据暴露给每条 workflow。
正确做法是建一个 **fine-grained PAT**:只对 ``shiliu153/chatapp``,只给
Contents(read/write)+ Pull requests(read/write),90 天过期。

怎么用
------
1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens
   → Generate new token:
   - Repository access: Only select repositories → ``shiliu153/chatapp``
   - Permissions: Contents = Read and write;Pull requests = Read and write
   - Expiration: 90 days(到期前会收到 GitHub 提醒)
2. 把 token 放进环境变量后跑:

       $env:AUTOMERGE_TOKEN = "github_pat_xxx"          # PowerShell
       python scripts/set_automerge_token.py --dry-run   # 先看能不能读到 public key
       python scripts/set_automerge_token.py             # 真写

3. 验证:``gh api repos/shiliu153/chatapp/actions/secrets`` 里应出现 ``AUTOMERGE_TOKEN``。
   下一次 auto-merge 的日志里 ``GH_TOKEN`` 会走 PAT,合并后 push 轨会被触发。

退出码:0 成功;1 失败;2 用法/环境错误。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from nacl import encoding, public

# `python scripts/set_automerge_token.py` 时 sys.path[0] 是 scripts/,显式把仓库根放进去,
# 这样 `from scripts.lib import repo` 在直接跑与 unittest 两种方式下都成立(见 lib/__init__.py)。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.lib import repo as lib_repo  # noqa: E402  (必须在 sys.path 修好之后)

SECRET_NAME = "AUTOMERGE_TOKEN"


class SecretError(Exception):
    """无法完成写入;由 main 转成退出码。"""


def read_admin_token() -> str:
    """取用于「写 secret」的管理凭据(需要 admin 权限)。

    Returns:
        PAT 字符串。

    Raises:
        SecretError: 环境变量与 DSH token 文件都没有。
    """
    try:
        return lib_repo.resolve_token()
    except lib_repo.TokenError as error:
        raise SecretError(str(error)) from error


def request(method: str, url: str, token: str, payload: dict | None = None) -> tuple[int, dict]:
    """发一次 GitHub API 请求。

    Args:
        method: HTTP 方法。
        url: 完整 URL。
        token: 具有 admin 权限的 PAT。
        payload: JSON body。

    Returns:
        ``(状态码, 解析后的 JSON)``;空响应体返回 ``{}``。
    """
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    req.add_header("User-Agent", "chatapp-set-secret")
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
    except urllib.error.URLError as error:
        raise SecretError(f"网络错误:{error.reason}") from error


def seal(public_key_b64: str, secret_value: str) -> str:
    """用仓库 public key 做 sealed box 加密(GitHub secrets 的要求)。

    Args:
        public_key_b64: ``GET /actions/secrets/public-key`` 返回的 ``key``。
        secret_value: 要写入的明文 secret。

    Returns:
        base64 编码的密文。
    """
    key = public.PublicKey(public_key_b64.encode("utf-8"), encoding.Base64Encoder())
    sealed_box = public.SealedBox(key)
    return base64.b64encode(sealed_box.encrypt(secret_value.encode("utf-8"))).decode("utf-8")


def main(argv: list[str] | None = None) -> int:
    """命令行入口。

    Args:
        argv: 参数列表;``None`` 表示取 ``sys.argv[1:]``。

    Returns:
        0 成功;1 失败;2 用法/环境错误。
    """
    parser = argparse.ArgumentParser(description="写入 AUTOMERGE_TOKEN secret")
    parser.add_argument("--repo", default=DEFAULT_REPO, help="owner/name")
    parser.add_argument("--dry-run", action="store_true", help="只读 public key,不写")
    args = parser.parse_args(argv)

    try:
        secret_value = os.environ.get(SECRET_NAME, "").strip()
        if not secret_value:
            raise SecretError(
                f"环境变量 {SECRET_NAME} 为空。先在 GitHub 建 fine-grained PAT,"
                f"再设 $env:{SECRET_NAME}"
            )
        admin = read_admin_token()

        status, key = request(
            "GET", f"{API}/repos/{args.repo}/actions/secrets/public-key", admin)
        if status != 200:
            raise SecretError(
                f"读 public-key 失败:{status} {key.get('message', '')}"
                "(通常是当前 token 没有 admin 权限)"
            )
        print(f"[secret] 已拿到仓库 public key(key_id={key['key_id']})")
        if args.dry_run:
            print("[secret] dry-run:未写入")
            return 0

        encrypted = seal(key["key"], secret_value)
        status, result = request(
            "PUT",
            f"{API}/repos/{args.repo}/actions/secrets/{SECRET_NAME}",
            admin,
            {"encrypted_value": encrypted, "key_id": key["key_id"]},
        )
        if status not in (201, 204):
            raise SecretError(f"写入 secret 失败:{status} {result.get('message', '')}")
        print(f"[secret] 已写入 {SECRET_NAME}")
        print("[secret] 下一次 auto-merge 会用 PAT 合并,合并后 push 轨会被触发")
        return 0
    except SecretError as error:
        print(f"[secret] 错误:{error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
