#!/usr/bin/env python3
"""校验 `docs/` 的三条结构规则:放错了文件、写坏了链接、文档不在索引里。

为什么需要它
------------
治理方案(`docs/superpowers/specs/2026-11-14-docs-and-scripts-governance-design.md`)
§3.3 把「文档结构」变成了三个可机械判定的目标:

1. `docs/` 下的脚本 / 补丁 / 二进制 **0 个**;
2. 非归档文档被索引覆盖 **100%**;
3. 相对链接 **0 条断**。

这三条的共同点是**坏了没人当场知道**:脚本躺在文档目录里不会让任何测试红,一份新文档
没进索引也照样能提交,而断链只有人在浏览器里点开才看得见。所以它必须是一道门禁,
不能是「大家记得」的纪律。

判什么、不判什么
----------------
判(**三条规则,各自独立**):

- **structure**:`docs/` 下只允许 `.md` / `.yml` / `.json` / 图片
  (`.png .jpg .jpeg .webp .svg`)。脚本、补丁、可执行文件一律进 `scripts/`。
  归档目录同样受此约束 —— 归档只 `git mv`,不新增别的类型。
- **broken-link**:**直接复用** ``scripts.check_docs_links.find_broken_links``,
  不重写链接解析(那边已经把「什么算链接」判准了,重写一份只会产生两套口径)。
- **unindexed**:非归档 `.md` 必须被某个索引文件以**相对链接**指向。索引文件 =
  仓库根的 `README.md` / `CLAUDE.md` / `AGENTS.md` + `docs/` 下任意层级的 `README.md`。
  `docs/superpowers/archive/` 不参与(历史文档保持原样,spec §6)。

不判(**刻意**,判不准或会变成噪音):

- 链接锚点是否存在(要解析标题锚点规则,误报率高);
- 外链是否可达(需要联网,会因对方站点抖动误报);
- 「索引文件自己是否被索引」—— 根那三份是入口,不要求被指向;子 `README.md` 要。

用法
----
    python scripts/docs_lint.py              # 人读:逐条打印违例
    python scripts/docs_lint.py --json       # 机器读:L4 判定器复用
    python scripts/docs_lint.py --root .     # 自测:换一个仓库根

退出码:0 = 0 违例;1 = 有违例;2 = 判定器自己出错(目录不对 / 一个文件都没扫到)。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Set

# `python scripts/docs_lint.py` 时 sys.path[0] 是 scripts/,所以要显式把仓库根放进去,
# 这样 `from scripts import check_docs_links` 两种调用方式(直接跑 / unittest)都成立。
# 与 `scripts/l4_intake.py` 用的是同一段处理。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import check_docs_links  # noqa: E402  (必须在 sys.path 修好之后)

#: `docs/` 下允许出现的文件类型。判定用小写后缀,`.YML` 与 `.yml` 同等对待。
ALLOWED_SUFFIXES = frozenset({".md", ".yml", ".json", ".png", ".jpg", ".jpeg", ".webp", ".svg"})

#: 文档目录名(相对仓库根)。
DOCS_SUBDIR = "docs"

#: 归档目录(相对 `docs/`)的路径片段;该子树不参与索引覆盖判定。
ARCHIVE_PARTS = ("superpowers", "archive")

#: 仓库根上算「索引」的三份入口文件(它们自己不需要被指向)。
ROOT_INDEX_NAMES = ("README.md", "CLAUDE.md", "AGENTS.md")

#: 索引文件的文件名:根上那三份 + `docs/` 下任意层级的 `README.md`。
INDEX_BASENAME = "README.md"


def _is_archived(path: Path, docs_dir: Path) -> bool:
    """判断一个路径是否落在 `docs/superpowers/archive/` 子树里。

    Args:
        path: 待判断的绝对路径(通常是 `docs/` 下的某个文件)。
        docs_dir: `docs/` 目录的绝对路径。

    Returns:
        落在归档子树里返回 ``True``;不在 `docs/` 下也返回 ``True``(不在判定范围内)。
    """
    try:
        parts = path.resolve().relative_to(docs_dir.resolve()).parts
    except ValueError:
        return True
    return parts[: len(ARCHIVE_PARTS)] == ARCHIVE_PARTS


def find_misplaced_files(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[str]:
    """找出 `docs/` 下不该出现的文件(结构规则)。

    Args:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名,默认 `docs`。

    Returns:
        违规文件的仓库相对路径列表,按路径排序。空列表表示结构合规。

    Raises:
        FileNotFoundError: 文档目录不存在 —— 那是「判不出来」,不是「合规」。
    """
    repo_root = repo_root.resolve()
    docs_dir = repo_root / docs_subdir
    if not docs_dir.is_dir():
        raise FileNotFoundError(f"找不到文档目录:{docs_dir}")

    misplaced: List[str] = []
    for path in sorted(docs_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() in ALLOWED_SUFFIXES:
            continue
        misplaced.append(path.relative_to(repo_root).as_posix())
    return misplaced


def index_files(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[Path]:
    """列出参与「索引覆盖」判定的全部索引文件。

    索引文件 = 仓库根的 `README.md` / `CLAUDE.md` / `AGENTS.md` + `docs/` 下任意层级的
    `README.md`(归档子树除外)。归档里的 README 不参与:历史文档不改,也不该拿它当入口。

    Args:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名,默认 `docs`。

    Returns:
        索引文件的绝对路径列表,按路径排序;不存在的根入口会被跳过。
    """
    repo_root = repo_root.resolve()
    found: List[Path] = [repo_root / name for name in ROOT_INDEX_NAMES if (repo_root / name).is_file()]
    docs_dir = repo_root / docs_subdir
    if docs_dir.is_dir():
        for path in sorted(docs_dir.rglob(INDEX_BASENAME)):
            if path.is_file() and not _is_archived(path, docs_dir):
                found.append(path)
    return found


def linked_targets(repo_root: Path, index: Path) -> Set[Path]:
    """取出一个索引文件以相对链接指向的全部仓库内路径。

    这里**复用** ``check_docs_links`` 的解析实现(抹代码 → 取目标 → 解析成绝对路径),
    而不是另写一套正则:链接语义只允许有一个口径,两套实现必然分叉。

    Args:
        repo_root: 仓库根目录。
        index: 索引文件的绝对路径。

    Returns:
        规范化后的绝对路径集合;外链、纯锚点、站点根路径已被上游过滤掉。
    """
    repo_root = repo_root.resolve()
    text = index.read_text(encoding="utf-8")
    stripped = check_docs_links._strip_code(text)  # noqa: SLF001  (同包复用,不复制正则)
    targets: Set[Path] = set()
    for _lineno, target in check_docs_links._candidate_targets(stripped):  # noqa: SLF001
        targets.add(check_docs_links._resolve(repo_root, index, target))  # noqa: SLF001
    return targets


def find_unindexed_docs(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[str]:
    """找出没有被任何索引文件以相对链接覆盖的非归档文档。

    Args:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名,默认 `docs`。

    Returns:
        未被覆盖的文档仓库相对路径列表,按路径排序。空列表表示 100% 覆盖。

    Raises:
        FileNotFoundError: 文档目录不存在。
    """
    repo_root = repo_root.resolve()
    docs_dir = repo_root / docs_subdir
    if not docs_dir.is_dir():
        raise FileNotFoundError(f"找不到文档目录:{docs_dir}")

    covered: Set[Path] = set()
    for index in index_files(repo_root, docs_subdir):
        covered |= linked_targets(repo_root, index)

    unindexed: List[str] = []
    for path in sorted(docs_dir.rglob("*.md")):
        if not path.is_file() or _is_archived(path, docs_dir):
            continue
        if path.resolve() in covered:
            continue
        unindexed.append(path.relative_to(repo_root).as_posix())
    return unindexed


def lint(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[dict]:
    """跑全部三条规则,返回一个扁平的违例列表。

    Args:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名,默认 `docs`。

    Returns:
        违例列表,每项形如
        ``{"rule": "structure", "file": "docs/ops/x.sh", "message": "..."}``。
        断链项另带 ``line`` / ``target`` / ``resolved`` / ``suggestion``。
        按 ``(rule, file, line)`` 排序以保证输出稳定。

    Raises:
        FileNotFoundError: 文档目录不存在。
        OSError: 有文档读不了 —— 判不出来,交给上层 fail-closed。
    """
    violations: List[dict] = []

    for path in find_misplaced_files(repo_root, docs_subdir):
        violations.append(
            {
                "rule": "structure",
                "file": path,
                "line": 0,
                "message": f"docs/ 下只允许 .md / .yml / .json / 图片;脚本、补丁、配置进 scripts/",
            }
        )

    for item in check_docs_links.find_broken_links(Path(repo_root), docs_subdir):
        violations.append(
            {
                "rule": "broken-link",
                "file": item["file"],
                "line": item["line"],
                "target": item["target"],
                "resolved": item["resolved"],
                "suggestion": item["suggestion"],
                "message": f"相对链接指向不存在的路径:{item['target']}",
            }
        )

    for path in find_unindexed_docs(repo_root, docs_subdir):
        violations.append(
            {
                "rule": "unindexed",
                "file": path,
                "line": 0,
                "message": "非归档文档没有被任何索引(README/CLAUDE/AGENTS/子 README)链接",
            }
        )

    violations.sort(key=lambda item: (item["rule"], item["file"], item["line"]))
    return violations


def count_docs(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> int:
    """数一数扫到了多少份 Markdown,用来区分「合规」与「一个都没扫到」。

    后者是真故障(检出目录不对 / 路径变了),不该被当成「0 违例」悄悄通过 ——
    与 ``check_docs_links.count_markdown_files`` 是同一个理由。

    Args:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名,默认 `docs`。

    Returns:
        `docs/` 下 `.md` 文件的个数;目录不存在时返回 0。
    """
    return check_docs_links.count_markdown_files(Path(repo_root), docs_subdir)


def _describe(item: dict) -> str:
    """把一条违例渲染成人读的一行(含可执行的改法候选)。

    Args:
        item: ``lint`` 返回的违例项。

    Returns:
        形如 ``[rule] docs/a.md:12 → 目标 (解析为 ...)`` 的字符串,候选行按需追加。
    """
    where = item["file"] if not item.get("line") else f"{item['file']}:{item['line']}"
    line = f"[{item['rule']}] {where}  {item['message']}"
    if item.get("suggestion"):
        line += f"\n    候选(同名文件唯一):{item['suggestion']}"
    return line


def main(argv: List[str] | None = None) -> int:
    """命令行入口:跑三条规则并输出结果,返回退出码。

    Args:
        argv: 命令行参数列表;``None`` 表示用 ``sys.argv[1:]``。

    Returns:
        0 = 0 违例;1 = 有违例;2 = 判定器自身出错。
    """
    parser = argparse.ArgumentParser(
        description="校验 docs/ 的结构规则:放错位置的文件、断链、未被索引的文档"
    )
    parser.add_argument("--root", default=".", help="仓库根目录(默认当前目录)")
    parser.add_argument("--json", action="store_true", help="输出 JSON(L4 判定器用)")
    args = parser.parse_args(argv)

    root = Path(args.root)
    try:
        scanned = count_docs(root)
        if scanned == 0:
            print(f"docs_lint: 判定失败 —— {root.resolve() / DOCS_SUBDIR} 下一份 Markdown 都没扫到", file=sys.stderr)
            return 2
        violations = lint(root)
    except (OSError, FileNotFoundError) as exc:
        print(f"docs_lint: 判定失败 —— {exc}", file=sys.stderr)
        return 2

    by_rule: Dict[str, int] = {}
    for item in violations:
        by_rule[item["rule"]] = by_rule.get(item["rule"], 0) + 1

    if args.json:
        payload = {
            "violations": violations,
            "count": len(violations),
            "by_rule": by_rule,
            "scanned": scanned,
        }
        print(json.dumps(payload, ensure_ascii=False))
    else:
        for item in violations:
            print(_describe(item))
        if violations:
            summary = "、".join(f"{rule} {count}" for rule, count in sorted(by_rule.items()))
            print(f"\n共 {len(violations)} 处违例({summary}),扫描 {scanned} 份 Markdown", file=sys.stderr)
        else:
            print(f"docs/ 结构合规:扫描 {scanned} 份 Markdown,0 违例")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
