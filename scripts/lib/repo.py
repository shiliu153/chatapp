"""GitHub 侧的三条常量 + token 解析(唯一一份实现)。

收的是什么
----------
2026-11-14 实测:``DEFAULT_REPO`` / ``DEFAULT_TOKEN_FILE`` / ``API`` 三个常量在
``apply_ruleset`` / ``create_release`` / ``deploy_gate`` / ``set_automerge_token``
**各抄了 4 份**,token 解析逻辑(环境变量两个名字 → ``~/.dsh`` 的 token 文件)也抄了 4 份。
``sources-of-truth.md`` §4 C7 把这件事记成「常量重复」,但重复的其实是**四组**同性质的东西 ——
只收 spec 点名的 ``DEFAULT_REPO`` 等于只修了四分之一。

为什么 token 文件路径写在这里而不是各脚本里
------------------------------------------
四个脚本读的是**同一个 PAT**(与 DSH 的 ``mcp-github`` 共用),所以「找不到 token 时该说什么」
也只能有一份文案 —— 否则四个脚本会给出四种「把 PAT 写到哪」的说法,而其中三种是过期的。

错误处理口径
------------
本模块**不 print、不 exit**:调用方的退出码语义各不相同(``create_release`` 用 1,
``deploy_gate`` 用 2,``apply_ruleset`` / ``set_automerge_token`` 用 2),由它们各自把
:class:`TokenError` 翻译成自己的口径。lib 只负责「找不到」这个事实与那句提示。
"""

from __future__ import annotations

import os
from pathlib import Path

#: 本仓库在 GitHub 上的 ``owner/name``(唯一一份)。
DEFAULT_REPO = "shiliu153/chatapp"

#: DSH 的 ``mcp-github`` 用的 classic PAT 文件(``repo`` 权限)。四个脚本共用同一个文件。
DEFAULT_TOKEN_FILE = Path.home() / ".dsh" / "github-mcp-token.txt"

#: GitHub REST API 基址。
API = "https://api.github.com"

#: 上传 Release 附件专用的基址(与 ``API`` 不同域,必须分开)。
UPLOAD_API = "https://uploads.github.com"

#: 读 token 时依次尝试的环境变量名(顺序即优先级)。
TOKEN_ENV_VARS = ("GITHUB_TOKEN", "GITHUB_PERSONAL_ACCESS_TOKEN")


class TokenError(RuntimeError):
    """环境变量与 token 文件都拿不到 PAT。

    Attributes:
        hint: 给调用方补充自己语境的尾巴(如 ``deploy_gate`` 会加「只想做 git 侧校验可加
            ``--offline``」);缺省空串。
    """

    def __init__(self, message: str) -> None:
        """保存错误文案。

        Args:
            message: 完整的中文错误描述(已含 token 文件路径与补救办法)。
        """
        super().__init__(message)
        self.hint = ""


def token_hint(token_file: Path = DEFAULT_TOKEN_FILE) -> str:
    """拼出「token 在哪、怎么补」的那句提示(四个脚本共用同一份文案)。

    Args:
        token_file: token 文件路径;默认 DSH 的 ``mcp-github`` 那个 PAT 文件。

    Returns:
        中文提示,形如 ``请设 GITHUB_TOKEN,或把 PAT 写到 <路径>(与 mcp-github 用的是同一个文件)``。
    """
    return (
        "找不到 GitHub token:请设 GITHUB_TOKEN,或把 PAT 写到 "
        f"{token_file}(与 mcp-github 用的是同一个文件)"
    )


def resolve_token(token_file: Path = DEFAULT_TOKEN_FILE) -> str:
    """按优先级取 GitHub PAT:环境变量(两个名字)→ token 文件。

    Args:
        token_file: 回落读取的 token 文件路径;默认 DSH 的那一份。

    Returns:
        去掉首尾空白的 PAT 字符串。

    Raises:
        TokenError: 两个环境变量都为空,且 token 文件不存在或内容为空。
    """
    for name in TOKEN_ENV_VARS:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    if token_file.exists():
        value = token_file.read_text(encoding="utf-8").strip()
        if value:
            return value
    raise TokenError(token_hint(token_file))
