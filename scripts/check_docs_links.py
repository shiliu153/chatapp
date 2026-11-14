#!/usr/bin/env python3
"""巡检 `docs/**/*.md` 里的**相对链接**指向的路径是否真的存在。

为什么需要它
------------
仓库里有一批「已有确定性判定、但默认分支的 push 轨看不见」的失败。文档断链是其中
最典型的一类:Markdown 的相对链接指到一个被改名 / 删掉 / 从未创建的文件时,

- 没有任何 workflow 会红(六轨都不读 Markdown 链接);
- 人在浏览器里点开才看得到 404;
- 文件被改名时旧链接也不会被任何工具报出来。

判定是纯机械的:链接目标按 Markdown 语义解析成仓库内路径,存在 / 不存在。所以它是
L4「需求自动入队」的机械一致性信号的唯一实现(见
`docs/superpowers/specs/2026-11-08-superagent-automation-ladder-design.md` §5.2)。

判什么、不判什么
----------------
判:行内链接 `[文案](目标)`、图片 `![alt](目标)`、引用式定义 `[id]: 目标`。

不判(**刻意**,这些都判不准或会变成噪音):

- 外链(`http://` / `https://` / `mailto:` / `tel:`):需要联网,且会因对方站点抖动误报;
- 纯锚点(`#xxx`)与 `?query`:锚点是否存在要解析标题锚点规则,误报率高;
- 以 `/` 开头的路径:语义是站点根,不是仓库相对路径;
- 代码块与行内代码里的东西:那不是链接。

被检文件范围:`docs/` 下的全部 `.md`。**只读**,不改任何文件。

用法
----
    python scripts/check_docs_links.py            # 人读:逐条打印断链
    python scripts/check_docs_links.py --json     # 机器读:L4 判定器消费
    python scripts/check_docs_links.py --root .   # 自测:换一个仓库根

退出码:0 = 没有断链;1 = 有断链;2 = 判定器自己出错(参数 / 读文件失败)。

文件信息:
    文件名称          scripts/check_docs_links.py
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
import os
import re
import sys
from pathlib import Path
from typing import Iterator, List, Tuple

# `[文案](目标 "title")` 与 `![alt](目标)`;文案里允许出现一层方括号(如 `模块[废弃]`)。
INLINE_LINK = re.compile(r"!?\[(?:[^\[\]]|\[[^\[\]]*\])*\]\(\s*<?([^()<>]+?)>?(?:\s+\"[^\"]*\")?\s*\)")
# 引用式定义:`[id]: 目标`
REF_DEF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?(\S+?)>?\s*$")
FENCE = re.compile(r"^\s{0,3}(```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")

EXTERNAL_PREFIXES = ("http://", "https://", "mailto:", "tel:", "ftp://", "//")

# 找「同名文件」时跳过的目录:要么体积巨大,要么与本仓库文档无关。
SKIP_DIRS = {".git", "node_modules", ".dart_tool", "build", "dist", "flutter", "__pycache__", ".venv"}


def _iter_markdown_files(docs_dir: Path) -> Iterator[Path]:
    """按路径顺序产出 docs 目录下的全部 Markdown 文件。

    参数说明:
        docs_dir: 要遍历的目录(通常是仓库根下的 `docs/`)。

    返回参数:
        该目录下每个 `.md` 文件的绝对路径,按字符串排序以保证输出稳定。

    使用示例:
        ``_iter_markdown_files(docs_dir)``

    备注信息:
        无特殊约束。
    """
    for path in sorted(docs_dir.rglob("*.md")):
        if path.is_file():
            yield path


def _strip_code(text: str) -> str:
    """把代码块与行内代码从文本里抹掉,避免把代码里的方括号当成链接。

    参数说明:
        text: 单个 Markdown 文件的全文。

    返回参数:
        与入参等长、行结构不变的文本,其中代码区域已被空格覆盖。

    使用示例:
        ``_strip_code(text)``

    备注信息:
        抹掉而不是删除,是为了**保留行号**:替换成等长空白,后续报错的行号才对得上。
    """
    out_lines: List[str] = []
    in_fence = False
    for line in text.splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            out_lines.append(" " * len(line))
            continue
        if in_fence:
            out_lines.append(" " * len(line))
            continue
        out_lines.append(INLINE_CODE.sub(lambda m: " " * len(m.group(0)), line))
    return "\n".join(out_lines)


def _candidate_targets(text: str) -> Iterator[Tuple[int, str]]:
    """从已抹掉代码的 Markdown 里取出所有待判定的链接目标。

    参数说明:
        text: 已经过 `_strip_code` 处理的 Markdown 全文。

    返回参数:
        `(行号, 原始目标)` 二元组;行号从 1 起。外链与纯锚点在此已被过滤掉。

    使用示例:
        ``_candidate_targets(text)``

    备注信息:
        无特殊约束。
    """
    for lineno, line in enumerate(text.splitlines(), start=1):
        found: List[str] = []
        found.extend(m.group(1) for m in INLINE_LINK.finditer(line))
        ref = REF_DEF.match(line)
        if ref:
            found.append(ref.group(1))
        for raw in found:
            target = raw.strip()
            if not target or target.startswith("#"):
                continue
            # 以 `/` 开头是「站点根」语义(以及 `//host` 协议相对),不是仓库相对路径。
            if target.startswith("/") or target.startswith(EXTERNAL_PREFIXES):
                continue
            yield lineno, target


def _resolve(repo_root: Path, source: Path, target: str) -> Path:
    """把 Markdown 里的相对目标解析成仓库内路径。

    参数说明:
        repo_root: 仓库根目录(用于把 `..` 越界的目标判为不存在)。
        source: 链接所在的 Markdown 文件。
        target: 链接目标原文(可能带 `#anchor` 或 `%20`)。

    返回参数:
        规范化后的绝对路径;`#anchor` 与 `?query` 已剥离,百分号编码已解码。

    使用示例:
        ``_resolve(repo_root, source, target)``

    备注信息:
        无特殊约束。
    """
    clean = target.split("#", 1)[0].split("?", 1)[0]
    clean = clean.replace("%20", " ")
    return (source.parent / clean).resolve()


def _index_basenames(repo_root: Path) -> dict:
    """建立「文件名 → 仓库内路径列表」的索引,给断链提供**机器可得的改法候选**。

    参数说明:
        repo_root: 仓库根目录。

    返回参数:
        字典,键是文件名(如 `AGENTS.md`),值是该文件名全部出现位置的仓库相对路径列表。

    使用示例:
        ``_index_basenames(repo_root)``

    备注信息:
        只有「同名文件在全仓唯一」时才算候选:那是「链接写错了相对深度」这一类最常见的断链,
        改法是确定的(指向那个文件)。同名文件有多个时不给候选 —— 选哪个是人的判断。
    """
    index: dict = {}
    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            try:
                rel = path.relative_to(repo_root).as_posix()
            except ValueError:
                continue
            index.setdefault(name, []).append(rel)
    return index


def _suggestion(index: dict, target: str) -> str:
    """从同名索引里给出一条可执行的改法候选,拿不准就返回空串。

    参数说明:
        index: `_index_basenames` 建出的索引。
        target: 断链的目标原文(可能带 `#anchor`)。

    返回参数:
        唯一同名文件的仓库相对路径;没有或不止一个时返回空串。

    使用示例:
        ``_suggestion(index, target)``

    备注信息:
        无特殊约束。
    """
    base = target.split("#", 1)[0].split("?", 1)[0].replace("%20", " ").rstrip("/")
    name = base.rsplit("/", 1)[-1]
    if not name:
        return ""
    hits = index.get(name, [])
    return hits[0] if len(hits) == 1 else ""


def count_markdown_files(repo_root: Path, docs_subdir: str = "docs") -> int:
    """数一数「到底扫了多少个文件」。

    参数说明:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名,默认 `docs`。

    返回参数:
        `docs/` 下 `.md` 文件的个数;目录不存在时返回 0。

    使用示例:
        ``count_markdown_files(repo_root, docs_subdir)``

    备注信息:
        存在的意义是让判定器能区分**两种看起来一样的结论**:「扫了 128 个文件、没有断链」
        与「一个文件都没扫到」。后者是真故障(检出目录不对 / 路径变了),不该被当成
        「没有断链」悄悄通过 —— 2026-11-12 首次真跑就是被这种歧义困住过。
    """
    docs_dir = repo_root.resolve() / docs_subdir
    if not docs_dir.is_dir():
        return 0
    return sum(1 for _ in _iter_markdown_files(docs_dir))


def find_broken_links(repo_root: Path, docs_subdir: str = "docs") -> List[dict]:
    """扫描文档目录,返回全部断链。

    参数说明:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名,默认 `docs`。

    返回参数:
        断链列表,每项形如 `{"file": "docs/ops/x.md", "line": 12, "target": "../y.md", "resolved": "docs/y.md", "suggestion": "docs/superpowers/y.md"}`, 按文件与行号排序。`suggestion` 为空串表示没有唯一候选。空列表表示没有断链。

    使用示例:
        ``find_broken_links(repo_root, docs_subdir)``

    备注信息:
        失败时抛 ``FileNotFoundError``,由调用方处理。
    """
    repo_root = repo_root.resolve()
    docs_dir = repo_root / docs_subdir
    if not docs_dir.is_dir():
        raise FileNotFoundError(f"找不到文档目录:{docs_dir}")

    broken: List[dict] = []
    for md in _iter_markdown_files(docs_dir):
        rel_source = md.relative_to(repo_root).as_posix()
        try:
            text = md.read_text(encoding="utf-8")
        except OSError as exc:  # 读不动就是判不出来,交给上层 fail-closed
            raise OSError(f"读不了 {rel_source}:{exc}") from exc
        for lineno, target in _candidate_targets(_strip_code(text)):
            resolved = _resolve(repo_root, md, target)
            if resolved.exists():
                continue
            try:
                shown = resolved.relative_to(repo_root).as_posix()
            except ValueError:
                shown = os.path.relpath(str(resolved), str(repo_root))
            broken.append(
                {
                    "file": rel_source,
                    "line": lineno,
                    "target": target,
                    "resolved": shown,
                    "suggestion": "",
                }
            )
    if broken:
        index = _index_basenames(repo_root)
        for item in broken:
            item["suggestion"] = _suggestion(index, item["target"])
    broken.sort(key=lambda item: (item["file"], item["line"], item["target"]))
    return broken


def main(argv: List[str] | None = None) -> int:
    """命令行入口:扫描并输出断链,返回退出码。

    参数说明:
        argv: 命令行参数列表;`None` 表示用 `sys.argv[1:]`。

    返回参数:
        0 = 无断链;1 = 有断链;2 = 判定器自身出错。

    使用示例:
        ``python scripts/check_docs_links.py``

    备注信息:
        无特殊约束。
    """
    parser = argparse.ArgumentParser(
        description="检查 docs/ 下 Markdown 的相对链接是否指向存在的路径"
    )
    parser.add_argument("--root", default=".", help="仓库根目录(默认当前目录)")
    parser.add_argument("--json", action="store_true", help="输出 JSON(L4 判定器用)")
    args = parser.parse_args(argv)

    try:
        broken = find_broken_links(Path(args.root))
    except (OSError, FileNotFoundError) as exc:
        print(f"check_docs_links: 判定失败 —— {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({"broken": broken, "count": len(broken)}, ensure_ascii=False))
    else:
        for item in broken:
            line = f"{item['file']}:{item['line']} → {item['target']}  (解析为 {item['resolved']})"
            if item["suggestion"]:
                line += f"\n    候选(同名文件唯一):{item['suggestion']}"
            print(line)
        if broken:
            print(f"\n共 {len(broken)} 处断链", file=sys.stderr)
        else:
            print("docs/ 下没有断链")
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
