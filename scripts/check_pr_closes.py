"""PR 正文必须声明 `Closes #N` 的门禁(不关单就写「无」)。

为什么需要它
------------
PR 合并后应该关掉的 issue，只有 GitHub **认的关键字**才会自动关：正文里出现的
`Closes #N` / `Fixes #N` / `Resolves #N`。写 `Refs #N`、或者只在 squash 提交信息里带编号，
都不会触发 —— 结果是活已经干完、issue 还开着，下一个 agent 会把它当「没做完」再干一遍。

这个仓库已经踩过两次：`#102` 悬了一整轮（活早随 PR #103 合并了）、`#466`（PR #468 正文写的是
`Refs #466`）。两次都是「模板里写了要求、作者没照做」，所以光靠 `pull_request_template.md`
的注释挡不住 —— 那只是一段文字，不是判定。

判定口径
--------
1. 先把 HTML 注释整段删掉：模板里的示例（`Closes #<编号>`）就活在注释里，
   不删的话「原样没动的模板」会假通过。
2. 正文任意位置命中 `Closes|Fixes|Resolves #<数字>`（大小写不敏感，`#` 与数字间允许空格）
   → 通过。
3. 没命中关键词时，只认「显式声明不关单」：`## 关闭的 issue` 小节里写「无」
   （或 `none` / `n/a`）→ 通过。
4. 其余一律判红。若正文里出现了 `Refs #N` / `References #N`，额外提示「改成 Closes 才会自动关单」
   —— 这正是实测的失败形态。

用法
----
::

    python scripts/check_pr_closes.py --event "$GITHUB_EVENT_PATH"   # CI:读事件 JSON
    python scripts/check_pr_closes.py --body-file pr.md              # 本地:读正文文件
    gh pr view 475 --json body --jq .body | python scripts/check_pr_closes.py   # 从 stdin

退出码 0 = 通过；1 = 该关没关（判红）；2 = 用法错误。

备注
----
判定逻辑与 GitHub 的关键字口径一致（`closes` / `closed` / `close` / `fixes` / `fixed` / `fix` /
`resolves` / `resolved` / `resolve` + 可选冒号 + `#编号`）。这是**离线**判定，不查 GitHub API：
CI 里读的是事件负载里的正文，contract 轨仍然秒级、不联网。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

#: GitHub 认的关单关键字(作用与 `pull_request_template.md` 的说明一致)。
CLOSING_RE = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s*:?\s*#\s*(\d+)",
    re.IGNORECASE,
)

#: 只提编号、不关单的写法 —— 判红时用它给出更具体的提示。
REFERENCE_ONLY_RE = re.compile(r"\b(?:refs?|references?)\b\s*:?\s*#\s*(\d+)", re.IGNORECASE)

#: HTML 注释(模板里的示例与说明都在这里,必须先删掉)。
COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

#: 「不关单」小节的名字;小节里写「无」即视为显式声明。
EXEMPT_HEADING = "关闭的 issue"

#: 显式声明不关单的写法(中文优先,兼容英文)。
EXEMPT_WORDS = ("无", "none", "n/a", "n / a", "nothing")

#: 小节标题行(`## 关闭的 issue`),用于切出小节的正文。
SECTION_HEADING_RE = re.compile(r"^#{1,6}\s*(.+?)\s*$")


def strip_comments(body: str) -> str:
    """删掉正文里的 HTML 注释。

    Args:
        body: PR 正文原文。

    Returns:
        去掉 `<!-- ... -->` 之后的正文。
    """
    return COMMENT_RE.sub("", body)


def find_closing_references(body: str) -> list[int]:
    """找出正文里会触发自动关单的 issue 编号。

    Args:
        body: PR 正文(应已去掉 HTML 注释)。

    Returns:
        按出现顺序排列的 issue 编号;一个都没有时是空列表。
    """
    return [int(match.group(1)) for match in CLOSING_RE.finditer(body)]


def extract_section(body: str, heading: str) -> str | None:
    """取出某个 `##` 小节的正文。

    Args:
        body: PR 正文。
        heading: 小节标题(忽略大小写比较,允许标题里带额外文字)。

    Returns:
        小节正文(不含标题行);找不到该小节时返回 `None`。
    """
    lines = body.splitlines()
    collected: list[str] | None = None
    for line in lines:
        matched = SECTION_HEADING_RE.match(line.strip())
        if matched:
            title = matched.group(1).strip().lower()
            if collected is None:
                if title.startswith(heading.lower()):
                    collected = []
                continue
            break
        if collected is not None:
            collected.append(line)
    return "\n".join(collected) if collected is not None else None


def evaluate(body: str) -> tuple[bool, list[str]]:
    """判定一份 PR 正文是否满足「声明了关单 / 显式声明不关单」。

    Args:
        body: PR 正文原文(含 HTML 注释也可以)。

    Returns:
        `(是否通过, 说明行列表)`。说明行既用于失败原因的逐条打印,也用于成功时回显。
    """
    cleaned = strip_comments(body)
    if not cleaned.strip():
        return False, ["正文是空的(或只有模板注释):既没写 Closes #N,也没写「无」"]

    issues = find_closing_references(cleaned)
    if issues:
        return True, ["关单声明:" + "、".join(f"#{number}" for number in issues)]

    section = extract_section(cleaned, EXEMPT_HEADING)
    if section is not None:
        lowered = section.lower()
        if any(word in lowered for word in EXEMPT_WORDS):
            return True, [f"「{EXEMPT_HEADING}」小节声明不关单"]

    messages = ["正文里没有 Closes / Fixes / Resolves #<编号>,也没有在「关闭的 issue」小节写「无」"]
    refs = [int(match.group(1)) for match in REFERENCE_ONLY_RE.finditer(cleaned)]
    if refs:
        messages.append(
            "正文只写了 Refs:" + "、".join(f"#{number}" for number in refs)
            + " —— GitHub 不认 Refs,改成 Closes 才会在合并后自动关单"
        )
    return False, messages


class UsageError(Exception):
    """判不出来时的信号:参数冲突或输入读不出来。

    备注:
        它**不是**「判红」—— 门禁红(退出码 1)说的是「PR 正文不合规」,而这类是
        「这道门禁自己没法跑」。两者混在一起会让人去改 PR 正文,而真正该修的是调用方式。
    """


def load_body(event_path: Path | None, body_path: Path | None) -> str:
    """按命令行给出的来源读出 PR 正文。

    Args:
        event_path: GitHub 事件 JSON 路径(`--event`)。
        body_path: 纯文本正文路径(`--body-file`)。

    Returns:
        正文原文。

    Raises:
        UsageError: 参数冲突,或事件/正文文件读不出来(判不出来不等于通过)。
    """
    if event_path is not None and body_path is not None:
        raise UsageError("--event 与 --body-file 只能给一个")
    if event_path is not None:
        try:
            payload = json.loads(event_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise UsageError(f"读不出事件负载 {event_path}:{error}") from error
        body = (payload.get("pull_request") or {}).get("body")
        if body is None:
            raise UsageError(f"{event_path} 里没有 pull_request.body —— 这不像 pull_request 事件")
        return str(body)
    if body_path is not None:
        try:
            return body_path.read_text(encoding="utf-8")
        except OSError as error:
            raise UsageError(f"读不出正文文件 {body_path}:{error}") from error
    return sys.stdin.read()


def main(argv: list[str] | None = None) -> int:
    """门禁入口。

    Args:
        argv: 命令行参数(不含程序名);`None` 表示读 `sys.argv`。

    Returns:
        进程退出码:0 通过、1 判红、2 用法错误。
    """
    parser = argparse.ArgumentParser(description="PR 正文必须声明 Closes #N(不关单写「无」)")
    parser.add_argument("--event", type=Path, help="GitHub 事件 JSON(读 pull_request.body)")
    parser.add_argument("--body-file", type=Path, help="纯文本 PR 正文")
    parsed = parser.parse_args(argv)

    try:
        body = load_body(parsed.event, parsed.body_file)
    except UsageError as error:
        print(f"::error::{error}", file=sys.stderr)
        return 2

    ok, messages = evaluate(body)
    for message in messages:
        stream = sys.stdout if ok else sys.stderr
        prefix = "" if ok else "::error title=PR 缺少关单声明::"
        print(f"{prefix}{message}", file=stream)
    if not ok:
        print(
            "::error::在正文的「关闭的 issue」小节写 `Closes #<编号>`;确实不关任何 issue 的写「无」",
            file=sys.stderr,
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
