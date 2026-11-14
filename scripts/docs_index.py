#!/usr/bin/env python3
"""生成 `docs/` 的索引,并机械校验「索引 == 事实」。

为什么需要它
------------
治理方案(`docs/superpowers/specs/2026-11-14-docs-and-scripts-governance-design.md`)
第 3 节的前提是一句话:**手写计数必然过期**。本仓库已经过期过五次 ——
`docs/api/` 的接口数在 5 个地方各写一个版本、`docs/superpowers/` 的工作面 4 → 5
没人跟着改、归档表自称 105 份实际只链接了 98 份(7 份 R–W 批次 plan 被压成一句
「7 份文档一并归档」的叙述)。

所以索引不能是「谁记得同步」的纪律,必须是「扫描出来 + CI 比对」的机制。

生成的三个产物
--------------
1. ``docs/README.md`` —— **唯一目录入口**。非归档文档按目录分组(相对链接 + H1 标题)
   + 每目录份数 + 总数;归档只报数并指向第 2 项(同一份清单不写两遍)。
2. ``docs/superpowers/archive/INDEX.md`` —— 归档清单(日期 / 主题 / plan / spec)。
   全部由**文件名派生**;``spec`` 列只报「同名 ``-design`` 是否存在」,不做交付判断。
3. ``docs/api/README.md`` 里的标记区间 ``generated:api-summary`` —— 只覆盖两个标记之间的
   几行计数,其余手写内容一字不动。

为什么接口一览表**不整表生成**
------------------------------
``openapi.yml`` 没有 ``summary`` 字段(本项目的 ``@extend_schema`` 只给 description,
即视图 docstring),而表里「说明」列是人写的要点(如「注销(拉黑 refresh + 清 Cookie,
幂等 204)」)。整表生成的唯一可行来源是分册小节标题,实测 70 行里 43 行会丢掉括号里的
补充说明。所以这里换一条判据:表**保持手写**,但它的 ``(方法, 路径)`` 集合必须与
``openapi.yml`` 的操作集合**完全相等** —— 缺一行、多一行、重复一行都判红。
漂移同样被掐死,健康内容不动。

判什么、不判什么
----------------
判(**全部机械,无人工复核**):

- **生成物一致**:``--check`` 比对「内存里重新生成的结果」与磁盘;**只比字节**,
  不比 git(「已提交」由注册表的 ``kind = "artifact"`` 门禁兜,见 ``sources-of-truth.md`` §4 C9)。
- **归档完整性**:``docs/superpowers/archive/`` 下每一份 ``.md`` 必须在 INDEX.md 里
  **出现且仅出现一次**(漏登与重复登记都判红)。
- **入口完整性**:每一份非归档文档必须在 ``docs/README.md`` 里出现至少一次。
- **接口一览表 ≡ openapi.yml 的操作集合**。

不判(**刻意**):

- 「哪天交付了什么、结论是什么」—— 那是人的判断,owner 是 ``docs/milestones.md``;
- 归档里的历史文档内容 —— spec §6 规定一个字都不改;
- 链接锚点是否存在(归 ``docs_lint`` 的 broken-link 规则,这里不重写解析)。

用法
----
    python scripts/docs_index.py            # 等同 --check:人读,逐条打印差异
    python scripts/docs_index.py --check    # 不一致 → 退出码 1
    python scripts/docs_index.py --write    # 重新生成(改完文档后跑,再一起提交)
    python scripts/docs_index.py --json     # 机器读:L4 判定器复用
    python scripts/docs_index.py --root .   # 自测:换一个仓库根

退出码:0 = 一致;1 = 不一致 / 有违例;2 = 判定器自己出错(目录不对、openapi 解析不出来、
标记缺失)—— 那是「判不出来」,不是「合规」。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

# `python scripts/docs_index.py` 时 sys.path[0] 是 scripts/,显式把仓库根放进去,
# 这样 `from scripts import check_docs_links` 两种调用方式(直接跑 / unittest)都成立。
# 与 `scripts/docs_lint.py` 用的是同一段处理。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import check_docs_links  # noqa: E402  (必须在 sys.path 修好之后)

#: 文档目录名(相对仓库根)。
DOCS_SUBDIR = "docs"

#: 生成物:唯一目录入口(整份生成)。
INDEX_REL = "docs/README.md"

#: 生成物:归档清单(整份生成)。
ARCHIVE_INDEX_REL = "docs/superpowers/archive/INDEX.md"

#: 归档子树的路径片段(相对 `docs/`);该子树只报数,不逐份列进入口。
ARCHIVE_PARTS = ("superpowers", "archive")

#: 人读接口文档的入口(只替换标记区间,其余手写)。
API_README_REL = "docs/api/README.md"

#: 机器可读契约 —— 接口数量的唯一 owner。
OPENAPI_REL = "docs/api/openapi.yml"

#: 生成区间的起止标记。只覆盖两标记之间的内容,区间外一个字都不动。
API_BLOCK_BEGIN = "<!-- BEGIN generated:api-summary -->"
API_BLOCK_END = "<!-- END generated:api-summary -->"

#: 接口一览表的章节标题(表在它之后、下一个 `## ` 之前)。
API_TABLE_HEADING = "## 接口一览"

#: 生成物头部声明。禁止手改的约定靠它传达,不靠「大家知道」。
GENERATED_NOTICE = "> **本文件由 `scripts/docs_index.py` 生成,勿手改。**"

#: OpenAPI 里算「一个操作」的 HTTP 方法(小写,与 yml 的写法一致)。
HTTP_METHODS = ("get", "post", "put", "patch", "delete")

#: 第一个 H1 标题(用于给清单补「人读名称」)。
HEADING_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)

#: 归档文件名:`YYYY-MM-DD-<主题>.md`。
DATE_PREFIX_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)$")

#: `openapi.yml` 里 `paths:` 下一层的路径键(两空格缩进)。
OPENAPI_PATH_RE = re.compile(r"^  (/\S+):\s*$")

#: `openapi.yml` 里路径下一层的方法键(四空格缩进)。
OPENAPI_OP_RE = re.compile(r"^    (get|post|put|patch|delete):\s*$")

#: 接口一览表的行:`| POST | `/api/v1/...` | 说明 | [分册](x.md) |`。
API_ROW_RE = re.compile(r"^\|\s*(GET|POST|PATCH|DELETE)\s*\|\s*`([^`]+)`\s*\|")


# ---------------------------------------------------------------- 读 / 写


def _root(repo_root: Path | str) -> Path:
    """把「仓库根」参数统一成绝对路径。

    公开函数既接受 ``Path`` 也接受命令行传进来的字符串(``--root``),
    统一在这里归一化,避免每个函数各写一遍。

    Args:
        repo_root: 仓库根目录,``Path`` 或字符串均可。

    Returns:
        绝对路径形式的仓库根。
    """
    return Path(repo_root).resolve()


def _read_text(path: Path) -> str:
    """按原样读取文件(不做换行归一化)。

    为什么不用 ``Path.read_text``:它在默认参数下会把 CRLF 折成 LF,写回时就会
    把「只替换生成区间」变成「整文件换行全改」—— 手写内容就不再是「一字不动」。

    Args:
        path: 文件路径。

    Returns:
        文件内容,换行符与磁盘完全一致。
    """
    return path.read_bytes().decode("utf-8")


def _write_text(path: Path, text: str) -> None:
    """按原样写文件(不做换行归一化)。

    Args:
        path: 文件路径;父目录按需创建。
        text: 要写入的内容,换行符原样落盘。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def _rel(path: Path, base: Path) -> str:
    """把绝对路径渲染成相对 `base` 的 POSIX 路径(链接与显示都用它)。

    Args:
        path: 目标路径。
        base: 基准目录(通常是 `docs/`)。

    Returns:
        形如 ``api/auth.md`` 的相对路径。
    """
    return path.relative_to(base).as_posix()


def _cell(text: str) -> str:
    """把一段文本放进 Markdown 表格单元格(转义竖线、压掉换行)。

    Args:
        text: 原始文本(通常是文档 H1 标题或文件名派生的主题)。

    Returns:
        可以直接塞进 ``| ... |`` 的单行字符串。
    """
    return " ".join(text.split()).replace("|", "\\|")


# ---------------------------------------------------------------- 扫描


def _docs_dir(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> Path:
    """返回文档目录的绝对路径。

    Args:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名。

    Returns:
        `docs/` 的绝对路径。

    Raises:
        FileNotFoundError: 目录不存在 —— 那是「判不出来」,不是「合规」。
    """
    docs_dir = _root(repo_root) / docs_subdir
    if not docs_dir.is_dir():
        raise FileNotFoundError(f"找不到文档目录:{docs_dir}")
    return docs_dir


def _in_archive(path: Path, docs_dir: Path) -> bool:
    """判断一个路径是否落在 `docs/superpowers/archive/` 子树里。

    Args:
        path: 待判断的路径。
        docs_dir: `docs/` 的绝对路径。

    Returns:
        落在归档子树里返回 ``True``;不在 `docs/` 下也返回 ``True``(不在本模块判定范围内)。
    """
    try:
        parts = path.resolve().relative_to(docs_dir.resolve()).parts
    except ValueError:
        return True
    return parts[: len(ARCHIVE_PARTS)] == ARCHIVE_PARTS


def _sorted_by_path(paths: Iterable[Path]) -> List[Path]:
    """按 POSIX 路径字符串排序。

    为什么不用 `sorted(paths)`:``Path`` 的比较在 **Windows 上是大小写不敏感**的
    (`README.md` 排在 `app.md` 之后),在 **POSIX 上是大小写敏感**的(排在之前)。
    生成物必须跨平台逐字节一致 —— 否则本地 Windows 生成的索引到 CI(Ubuntu)上
    `--check` 会红,而那种红最难查(两边的文件完全一样,只是顺序不同)。

    Args:
        paths: 待排序的路径序列。

    Returns:
        排序后的列表,键是 ``path.as_posix()``(与平台无关)。
    """
    return sorted(paths, key=lambda path: path.as_posix())


def read_title(path: Path) -> str:
    """取一份文档的 H1 标题,没有标题就退回文件名。

    Args:
        path: Markdown 文件路径。

    Returns:
        第一行 ``# ...`` 的文本;文件读不了或没有 H1 时返回文件名(不含扩展名)。
    """
    try:
        text = _read_text(path)
    except OSError:
        return path.stem
    match = HEADING_RE.search(text)
    return match.group(1) if match else path.stem


def iter_docs(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[Path]:
    """列出参与入口清单的**非归档**文档。

    归档子树不逐份列进入口(它有自己的 INDEX.md);生成物 ``docs/README.md`` 自己
    也不列进自己(否则每次生成都多一行)。

    Args:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名。

    Returns:
        非归档 `.md` 的绝对路径列表,按路径排序。

    Raises:
        FileNotFoundError: 文档目录不存在。
    """
    docs_dir = _docs_dir(repo_root, docs_subdir)
    index_path = (_root(repo_root) / INDEX_REL).resolve()
    found: List[Path] = []
    for path in _sorted_by_path(docs_dir.rglob("*.md")):
        if not path.is_file() or _in_archive(path, docs_dir):
            continue
        if path.resolve() == index_path:
            continue
        found.append(path)
    return found


def group_docs(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> Dict[str, List[Path]]:
    """把非归档文档按所在目录分组(`docs/` 根用 ``.`` 表示)。

    Args:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名。

    Returns:
        有序字典:键是相对 `docs/` 的目录(根为 ``.``),值是文件列表;
        根排在最前,其余按路径字典序。
    """
    docs_dir = _docs_dir(repo_root, docs_subdir)
    groups: Dict[str, List[Path]] = {}
    for path in iter_docs(repo_root, docs_subdir):
        key = _rel(path.parent, docs_dir) or "."
        groups.setdefault(key, []).append(path)
    return dict(sorted(groups.items(), key=lambda item: (item[0] != ".", item[0])))


def iter_archive(repo_root: Path) -> Dict[str, List[Path]]:
    """列出归档目录下的 spec 与 plan(排除生成物 INDEX.md 自己)。

    Args:
        repo_root: 仓库根目录。

    Returns:
        ``{"specs": [...], "plans": [...]}``,各自按文件名排序(日期前缀天然等于时间序)。

    Raises:
        FileNotFoundError: 归档目录不存在。
    """
    archive_dir = (_root(repo_root) / ARCHIVE_INDEX_REL).parent
    if not archive_dir.is_dir():
        raise FileNotFoundError(f"找不到归档目录:{archive_dir}")
    index_path = (_root(repo_root) / ARCHIVE_INDEX_REL).resolve()
    groups: Dict[str, List[Path]] = {"specs": [], "plans": []}
    for name in groups:
        sub = archive_dir / name
        if not sub.is_dir():
            continue
        for path in _sorted_by_path(sub.rglob("*.md")):
            if path.is_file() and path.resolve() != index_path:
                groups[name].append(path)
    return groups


def count_archive(repo_root: Path) -> Dict[str, int]:
    """数一数归档有多少份(总数 / spec / plan)。

    Args:
        repo_root: 仓库根目录。

    Returns:
        ``{"total": N, "specs": N, "plans": N}``;不含生成物 INDEX.md 自己。
    """
    groups = iter_archive(repo_root)
    specs, plans = len(groups["specs"]), len(groups["plans"])
    return {"total": specs + plans, "specs": specs, "plans": plans}


def split_stem(stem: str) -> Tuple[str, str]:
    """把 ``YYYY-MM-DD-<主题>`` 拆成日期与主题。

    Args:
        stem: 不含扩展名的文件名。

    Returns:
        ``(日期, 主题)``;没有日期前缀时日期为空串,主题是原文件名。
    """
    match = DATE_PREFIX_RE.match(stem)
    if not match:
        return "", stem
    return match.group(1), match.group(2)


def parse_openapi_operations(repo_root: Path) -> List[Tuple[str, str]]:
    """从 `openapi.yml` 里解析出全部操作(方法 + 路径),按文件顺序。

    为什么手写解析而不是 ``import yaml``:本模块的定位是**纯标准库、秒级、离线**,
    和 `scripts/` 下其它门禁一致;而 `openapi.yml` 是 `spectacular` 生成的,
    缩进是稳定的两空格 / 四空格两级,行解析足够且不会因为 PyYAML 版本差异变行为。
    解析不出任何操作时**报错而不是返回空** —— 那说明格式变了,是判定器该响的时候。

    Args:
        repo_root: 仓库根目录。

    Returns:
        ``[(方法, 路径)]``,方法与 yml 一致用大写,如 ``("POST", "/api/v1/auth/logout")``。

    Raises:
        FileNotFoundError: 契约文件不存在。
        ValueError: 一个操作都没解析出来(格式变了)。
    """
    path = _root(repo_root) / OPENAPI_REL
    lines = _read_text(path).splitlines()
    operations: List[Tuple[str, str]] = []
    current: str | None = None
    in_paths = False
    for line in lines:
        if not in_paths:
            if line.rstrip() == "paths:":
                in_paths = True
            continue
        # 顶层键(顶格)出现即意味着 `paths:` 段结束。
        if line and not line.startswith(" "):
            break
        path_match = OPENAPI_PATH_RE.match(line)
        if path_match:
            current = path_match.group(1)
            continue
        op_match = OPENAPI_OP_RE.match(line)
        if op_match and current:
            operations.append((op_match.group(1).upper(), current))
    if not operations:
        raise ValueError(f"{OPENAPI_REL} 里一个操作都没解析出来(格式变了?)")
    return operations


def parse_api_table(repo_root: Path) -> List[Tuple[str, str]]:
    """解析 `docs/api/README.md`「接口一览」表里的 ``(方法, 路径)``。

    只认该章节内的表格行:README 别处的表格(目录、错误码说明)不该被当成接口。
    代码围栏内的示例也不算(与 `config/api_doc_coverage.py` 的口径一致)。

    Args:
        repo_root: 仓库根目录。

    Returns:
        ``[(方法, 路径)]``,按表中出现顺序;表不存在时返回空列表。

    Raises:
        FileNotFoundError: 接口文档入口不存在。
    """
    lines = _read_text(_root(repo_root) / API_README_REL).splitlines()
    rows: List[Tuple[str, str]] = []
    in_section = False
    in_fence = False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.startswith("## "):
            in_section = line.strip() == API_TABLE_HEADING
            continue
        if not in_section:
            continue
        match = API_ROW_RE.match(line)
        if match:
            rows.append((match.group(1), match.group(2)))
    return rows


def count_api_volumes(repo_root: Path) -> int:
    """数一数 `docs/api/` 下有多少份人读分册(不含本页 README)。

    Args:
        repo_root: 仓库根目录。

    Returns:
        分册份数。
    """
    api_dir = (_root(repo_root) / API_README_REL).parent
    return len([path for path in _sorted_by_path(api_dir.glob("*.md")) if path.name != "README.md"])


# ---------------------------------------------------------------- 渲染


def _usage_rows(docs_dir: Path) -> List[str]:
    """渲染入口页顶部「想知道 → 去哪」的固定表格行。

    链接按**存在性**过滤:目标文档被改名/删掉时这一行自动消失,不会制造断链
    (``check_docs_links`` 会兜住真正的断链,这里不重复报)。

    Args:
        docs_dir: `docs/` 的绝对路径。

    Returns:
        Markdown 表格的数据行列表(不含表头与分隔行)。
    """
    wanted = (
        ("现在该做什么(待办总表)", "backlog/2026-11-03-todo.md"),
        ("哪天交付了什么(里程碑时间线)", "milestones.md"),
        ("进行中 / 已归档的设计与计划", "superpowers/README.md"),
        ("对外接口(交付级)", "api/README.md"),
        ("写代码 / 排障前(踩坑手册)", "pitfalls/README.md"),
        ("编码规范", "standards/README.md"),
        ("某条事实谁说了算(口径地图)", "standards/sources-of-truth.md"),
        ("运维手册 / 测量报告 / 安全审计 / 教学", "ops/README.md"),
    )
    rows: List[str] = []
    for label, rel in wanted:
        if (docs_dir / rel).is_file():
            rows.append(f"| {label} | [{rel}]({rel}) |")
    return rows


def render_docs_index(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> str:
    """渲染 `docs/README.md` 的全文。

    Args:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名。

    Returns:
        生成物全文(以 ``\\n`` 结尾)。内容只依赖磁盘上的文件名与 H1,不含时间戳 ——
        同一份树永远渲染出同一份字节,``--check`` 才有意义。
    """
    repo_root = _root(repo_root)
    docs_dir = _docs_dir(repo_root, docs_subdir)
    groups = group_docs(repo_root, docs_subdir)
    total = sum(len(paths) for paths in groups.values())
    archive = count_archive(repo_root)

    lines: List[str] = [
        "# docs/ — 文档总索引",
        "",
        GENERATED_NOTICE,
        "> 重新生成:`python scripts/docs_index.py --write`;校验:`python scripts/docs_index.py --check`"
        "(CI `contract` 轨 + `verify.sh contract`)。",
        "> 本页的每个数字都是扫描结果 —— 手写的计数不算数(口径见"
        " [standards/sources-of-truth.md](standards/sources-of-truth.md) §2.4)。",
        "",
        "## 怎么用这个入口",
        "",
        "| 想知道 | 去哪 |",
        "|---|---|",
    ]
    lines.extend(_usage_rows(docs_dir))
    lines.extend(
        [
            "",
            "下面才是扫描结果:**非归档文档逐份列出**(按目录分组),**归档只报数**"
            "(逐份清单在归档自己的 INDEX.md 里,同一份清单不写两遍)。",
            "",
            "## 1. 非归档文档",
            "",
            f"共 **{total}** 份 / **{len(groups)}** 个目录(不含本文件)。",
            "",
        ]
    )

    for dir_rel, paths in groups.items():
        where = "`docs/` 根" if dir_rel == "." else f"`docs/{dir_rel}/`"
        lines.append(f"### {where}({len(paths)} 份)")
        lines.append("")
        lines.append("| 文档 | 标题 |")
        lines.append("|---|---|")
        for path in paths:
            lines.append(f"| [{_cell(path.name)}]({_rel(path, docs_dir)}) | {_cell(read_title(path))} |")
        lines.append("")

    lines.extend(
        [
            "## 2. 归档",
            "",
            f"`docs/superpowers/archive/` 共 **{archive['total']}** 份 = "
            f"**{archive['specs']}** spec + **{archive['plans']}** plan。",
            "",
            "逐份清单(日期 / 主题 / plan ↔ spec 对照)见"
            " **[superpowers/archive/INDEX.md](superpowers/archive/INDEX.md)**。",
            "",
            "> 这里只报数、不重复列表:同一份清单两处手写,正是本方案要消灭的那类漂移。",
            "> 「哪天交付了什么、结论是什么」看 [milestones.md](milestones.md)。",
            "",
        ]
    )
    return "\n".join(lines)


def render_archive_index(repo_root: Path) -> str:
    """渲染 `docs/superpowers/archive/INDEX.md` 的全文。

    Args:
        repo_root: 仓库根目录。

    Returns:
        生成物全文。日期与主题从文件名派生,``spec`` 列只报「同名 ``-design`` 是否存在」。
    """
    repo_root = _root(repo_root)
    groups = iter_archive(repo_root)
    specs, plans = groups["specs"], groups["plans"]
    spec_names = {path.name for path in specs}

    lines: List[str] = [
        "# docs/superpowers/archive/ — 归档清单",
        "",
        GENERATED_NOTICE,
        f"> 共 **{len(specs) + len(plans)}** 份 = **{len(specs)}** spec + **{len(plans)}** plan"
        "(扫描 `specs/` 与 `plans/`)。",
        "> 机器判定:每份归档文件在本表**以链接形式出现且仅出现一次**"
        "(`python scripts/docs_index.py --check`)。",
        "> 「哪天交付了什么、结论是什么」看 [../../milestones.md](../../milestones.md);"
        "归档流程见 [../README.md](../README.md)。",
        "",
        f"## 1. specs({len(specs)} 份)",
        "",
        "| 日期 | 主题 | 文档 |",
        "|---|---|---|",
    ]
    for path in specs:
        date, topic = split_stem(path.stem)
        lines.append(f"| {date or '—'} | {_cell(topic)} | [{_cell(path.name)}](specs/{path.name}) |")

    lines.extend(
        [
            "",
            f"## 2. plans({len(plans)} 份)",
            "",
            "> `spec` 列写**文件名而不是链接**:这样每份归档文件在本表里只以链接形式出现**一次**",
            "> (它自己那一行),「出现且仅出现一次」才能被机械判定,而不是靠格式约定。",
            "> 该列只报同名 `<plan 名>-design.md` 是否存在(纯文件名派生);文件名不对应的历史配对",
            "> (如 `m0-foundation` 对应整体 MVP 设计 `dating-app-mvp-design`)显示 `—` ——",
            "> 那需要人判断,不是生成器该猜的东西;人的判断见 [../README.md](../README.md) §2 与",
            "> [../../milestones.md](../../milestones.md)。",
            "",
            "| 日期 | 主题 | plan | spec |",
            "|---|---|---|---|",
        ]
    )
    for path in plans:
        date, topic = split_stem(path.stem)
        spec_name = f"{path.stem}-design.md"
        spec_cell = f"`{spec_name}`" if spec_name in spec_names else "—"
        lines.append(
            f"| {date or '—'} | {_cell(topic)} | [{_cell(path.name)}](plans/{path.name}) | {spec_cell} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_api_summary(repo_root: Path) -> str:
    """渲染 `docs/api/README.md` 生成区间的内容(不含标记行)。

    Args:
        repo_root: 仓库根目录。

    Returns:
        区间正文;份数全部来自扫描(分册数 = `docs/api/*.md` 减本页,
        路径数 / 操作数 = `openapi.yml`,表行数 = 实际表格行数)。
    """
    operations = parse_openapi_operations(repo_root)
    paths = {path for _method, path in operations}
    rows = parse_api_table(repo_root)
    volumes = count_api_volumes(repo_root)
    return "\n".join(
        [
            f"本目录共 **{volumes}** 份人读分册 + 本页;`openapi.yml` 共 "
            f"**{len(paths)}** paths / **{len(operations)}** operations。",
            "",
            f"下表 **{len(rows)}** 行与 `openapi.yml` 的操作集合**逐一相等**"
            "(缺一行 / 多一行 / 重复一行,`python scripts/docs_index.py --check` 即红)。",
        ]
    )


def _newline_of(text: str) -> str:
    """判断文本的主换行风格(用于在生成区间里跟随原文件)。

    Args:
        text: 文件全文。

    Returns:
        ``"\\r\\n"`` 或 ``"\\n"``。
    """
    return "\r\n" if "\r\n" in text else "\n"


def splice_api_block(text: str, body: str) -> str:
    """把生成区间的内容替换进接口文档入口,区间外一个字节都不动。

    Args:
        text: `docs/api/README.md` 的当前全文。
        body: ``render_api_summary`` 的结果(以 ``\\n`` 分隔)。

    Returns:
        替换后的全文,换行风格跟随原文件。

    Raises:
        ValueError: 两个标记缺一个或顺序颠倒。
    """
    newline = _newline_of(text)
    try:
        start = text.index(API_BLOCK_BEGIN) + len(API_BLOCK_BEGIN)
        stop = text.index(API_BLOCK_END, start)
    except ValueError as exc:
        raise ValueError(
            f"{API_README_REL} 里找不到成对的生成标记 {API_BLOCK_BEGIN} / {API_BLOCK_END}"
        ) from exc
    return text[:start] + newline + body.replace("\n", newline) + newline + text[stop:]


def render_api_readme(repo_root: Path) -> str:
    """渲染 `docs/api/README.md` 的「期望全文」。

    只在磁盘当前内容上替换生成区间 —— 因此 ``--check`` 实际比对的**只有区间**,
    区间外的手写内容不会被误判成「过期」。

    Args:
        repo_root: 仓库根目录。

    Returns:
        期望全文(区间外与原文件一致)。

    Raises:
        FileNotFoundError: 接口文档入口不存在。
        ValueError: 生成标记缺失。
    """
    path = _root(repo_root) / API_README_REL
    return splice_api_block(_read_text(path), render_api_summary(repo_root))


def render_all(repo_root: Path) -> Dict[str, str]:
    """渲染全部生成物(仓库相对路径 → 期望内容)。

    Args:
        repo_root: 仓库根目录。

    Returns:
        三个产物的期望内容;``docs/api/README.md`` 的值是「替换区间后的全文」。
    """
    return {
        INDEX_REL: render_docs_index(repo_root),
        ARCHIVE_INDEX_REL: render_archive_index(repo_root),
        API_README_REL: render_api_readme(repo_root),
    }


# ---------------------------------------------------------------- 判定


def _linked_paths(source: Path, repo_root: Path) -> List[Path]:
    """取出一个 Markdown 文件里全部仓库内相对链接(解析成绝对路径,保留重复)。

    复用 ``check_docs_links`` 的解析实现(抹代码 → 取目标 → 解析),不重写正则:
    链接语义只允许一个口径,两套实现必然分叉 —— 与 ``docs_lint`` 的做法一致。

    Args:
        source: 链接所在的 Markdown 文件。
        repo_root: 仓库根目录(用于把 `..` 越界的目标判为不存在)。

    Returns:
        解析后的绝对路径列表(按出现顺序,重复项保留,供「出现且仅出现一次」判定用)。
    """
    stripped = check_docs_links._strip_code(_read_text(source))  # noqa: SLF001  (同包复用)
    return [
        check_docs_links._resolve(repo_root, source, target)  # noqa: SLF001
        for _lineno, target in check_docs_links._candidate_targets(stripped)  # noqa: SLF001
    ]


def check_archive_completeness(repo_root: Path) -> List[str]:
    """校验「归档里每一份 `.md` 在 INDEX.md 里出现且仅出现一次」。

    这是本节最核心的一条机械规则:它把「手写归档表必然漏登」变成「漏登即红」。
    当前实现由生成器保证,但规则本身仍要独立可判 —— 手改生成物、生成器回归、
    或者把 INDEX.md 换成手写版本,都必须在这里响。

    Args:
        repo_root: 仓库根目录。

    Returns:
        问题描述列表,按路径排序;空列表表示归档清单完整。
    """
    repo_root = _root(repo_root)
    index_path = repo_root / ARCHIVE_INDEX_REL
    problems: List[str] = []
    if not index_path.is_file():
        return [f"{ARCHIVE_INDEX_REL} 不存在:先跑 python scripts/docs_index.py --write"]

    archive_dir = index_path.parent
    groups = iter_archive(repo_root)
    files = {path.resolve(): path for group in groups.values() for path in group}
    counts = Counter(_linked_paths(index_path, repo_root))

    for resolved, path in sorted(files.items(), key=lambda item: item[1].as_posix()):
        seen = counts.get(resolved, 0)
        if seen == 0:
            problems.append(f"归档文件没有登记进索引:{_rel(path, archive_dir)}")
        elif seen > 1:
            problems.append(f"归档文件在索引里重复出现 {seen} 次:{_rel(path, archive_dir)}")

    for resolved, seen in sorted(counts.items(), key=lambda item: item[0].as_posix()):
        if resolved in files or seen == 0:
            continue
        # 只判「本目录内」的悬空链接:INDEX.md 头部还指向 `../README.md` / `../../milestones.md`,
        # 那些不属于归档清单,不该被这里当成「多出来的登记」。
        try:
            resolved.relative_to(archive_dir.resolve())
        except ValueError:
            continue
        problems.append(f"索引里有指向不存在文件的链接:{resolved.name}({seen} 次)")
    return problems


def check_entry_completeness(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[str]:
    """校验「每一份非归档文档都在 `docs/README.md` 里出现至少一次」。

    ``docs_lint`` 判的是「被**任意**索引覆盖」,这里判的是「被**唯一入口**覆盖」——
    两者不重复:前者允许子 README 各自兜一部分,后者保证「一个入口能看到全部」。

    Args:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名。

    Returns:
        问题描述列表,按路径排序;空列表表示入口完整。
    """
    repo_root = _root(repo_root)
    index_path = repo_root / INDEX_REL
    if not index_path.is_file():
        return [f"{INDEX_REL} 不存在:先跑 python scripts/docs_index.py --write"]

    docs_dir = _docs_dir(repo_root, docs_subdir)
    covered = set(_linked_paths(index_path, repo_root))
    problems: List[str] = []
    for path in iter_docs(repo_root, docs_subdir):
        if path.resolve() not in covered:
            problems.append(f"非归档文档没有进入口索引:{_rel(path, docs_dir)}")
    return problems


def check_api_table(repo_root: Path) -> List[str]:
    """校验「接口一览表 ≡ `openapi.yml` 的操作集合」。

    为什么这条能替代「整表生成」:表里唯一会**静默过期**的东西是「有哪几个接口」。
    说明列是人写要点,不会因为代码改动而过期;而多一个 / 少一个接口正是漂移的形状
    (第 1 节修的就是「表里缺 `users/me/voice` 两行」)。

    Args:
        repo_root: 仓库根目录。

    Returns:
        问题描述列表;空列表表示表的操作集合与契约完全一致。
    """
    expected = parse_openapi_operations(repo_root)
    actual = parse_api_table(repo_root)
    problems: List[str] = []

    expected_set, actual_set = set(expected), set(actual)
    for method, path in expected:
        if (method, path) not in actual_set:
            problems.append(f"「接口一览」表缺 {method} {path}(`openapi.yml` 里有)")
    for method, path in actual:
        if (method, path) not in expected_set:
            problems.append(f"「接口一览」表多出 {method} {path}(`openapi.yml` 里没有)")

    duplicates = [(op, n) for op, n in Counter(actual).items() if n > 1]
    for (method, path), seen in sorted(duplicates):
        problems.append(f"「接口一览」表里 {method} {path} 重复出现 {seen} 次")
    return problems


def check_generated_files(repo_root: Path) -> List[str]:
    """校验三个生成物与「重新生成的结果」逐字节一致。

    Args:
        repo_root: 仓库根目录。

    Returns:
        问题描述列表;每个不一致的文件一条(缺文件也在这里报)。
    """
    repo_root = _root(repo_root)
    problems: List[str] = []
    expected = render_all(repo_root)
    for rel, text in expected.items():
        path = repo_root / rel
        if not path.is_file():
            problems.append(f"生成物不存在:{rel}(跑 python scripts/docs_index.py --write)")
            continue
        if _read_text(path) != text:
            problems.append(f"生成物与事实不一致:{rel}(跑 python scripts/docs_index.py --write)")
    return problems


def check(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[str]:
    """跑全部判定,返回一个扁平的问题列表。

    Args:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名。

    Returns:
        问题描述列表(先生成物一致性,再完整性,最后接口表);空列表表示全部通过。

    Raises:
        FileNotFoundError: 文档目录 / 归档目录 / 契约文件不存在。
        ValueError: `openapi.yml` 解析不出操作,或接口文档入口缺生成标记。
    """
    problems: List[str] = []
    problems.extend(check_generated_files(repo_root))
    problems.extend(check_archive_completeness(repo_root))
    problems.extend(check_entry_completeness(repo_root, docs_subdir))
    problems.extend(check_api_table(repo_root))
    return problems


def write_all(repo_root: Path) -> List[str]:
    """把三个生成物写回磁盘(只在内容确实变化时落盘)。

    Args:
        repo_root: 仓库根目录。

    Returns:
        实际改动的仓库相对路径列表;已一致的文件不写(避免无意义的 mtime 变化)。
    """
    repo_root = _root(repo_root)
    changed: List[str] = []
    for rel, text in render_all(repo_root).items():
        path = repo_root / rel
        if path.is_file() and _read_text(path) == text:
            continue
        _write_text(path, text)
        changed.append(rel)
    return changed


def summarize(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> Dict[str, int]:
    """收集一组计数,供 ``--json`` 与输出尾巴使用。

    Args:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名。

    Returns:
        计数字典:非归档份数 / 目录数 / 归档总数 / spec / plan / 接口操作数 / 表行数。
    """
    repo_root = _root(repo_root)
    groups = group_docs(repo_root, docs_subdir)
    archive = count_archive(repo_root)
    return {
        "non_archive": sum(len(paths) for paths in groups.values()),
        "directories": len(groups),
        "archive": archive["total"],
        "archive_specs": archive["specs"],
        "archive_plans": archive["plans"],
        "api_operations": len(parse_openapi_operations(repo_root)),
        "api_table_rows": len(parse_api_table(repo_root)),
    }


# ---------------------------------------------------------------- 命令行


def main(argv: List[str] | None = None) -> int:
    """命令行入口:生成或校验,返回退出码。

    Args:
        argv: 命令行参数列表;``None`` 表示用 ``sys.argv[1:]``。

    Returns:
        0 = 一致;1 = 不一致 / 有违例;2 = 判定器自身出错。
    """
    parser = argparse.ArgumentParser(
        description="生成 docs/ 的索引(docs/README.md + 归档 INDEX.md + 接口计数),并校验索引与事实一致"
    )
    parser.add_argument("--root", default=".", help="仓库根目录(默认当前目录)")
    parser.add_argument("--check", action="store_true", help="校验(默认行为)")
    parser.add_argument("--write", action="store_true", help="重新生成并写盘")
    parser.add_argument("--json", action="store_true", help="输出 JSON(L4 判定器用)")
    args = parser.parse_args(argv)

    if args.check and args.write:
        print("docs_index: --check 与 --write 不能同时用", file=sys.stderr)
        return 2

    root = Path(args.root)
    try:
        if args.write:
            changed = write_all(root)
            counts = summarize(root)
        else:
            problems = check(root)
            counts = summarize(root)
    except (OSError, FileNotFoundError, ValueError) as exc:
        print(f"docs_index: 判定失败 —— {exc}", file=sys.stderr)
        return 2

    if args.write:
        if args.json:
            print(json.dumps({"ok": True, "changed": changed, "counts": counts}, ensure_ascii=False))
        elif changed:
            for rel in changed:
                print(f"已生成:{rel}")
        else:
            print("docs_index: 三个生成物都已是最新,无需写入")
        return 0

    if args.json:
        payload = {"ok": not problems, "problems": problems, "counts": counts}
        print(json.dumps(payload, ensure_ascii=False))
    elif problems:
        for item in problems:
            print(item)
        print(f"\n共 {len(problems)} 处不一致,扫描:{_describe_counts(counts)}", file=sys.stderr)
    else:
        print(f"docs_index: 索引与事实一致 —— {_describe_counts(counts)}")
    return 1 if problems else 0


def _describe_counts(counts: Dict[str, int]) -> str:
    """把计数字典渲染成一行人读摘要。

    Args:
        counts: ``summarize`` 的返回值。

    Returns:
        形如「非归档 77 份 / 13 目录;归档 105 = 40 spec + 65 plan;接口 70 个(表 70 行)」的字符串。
    """
    return (
        f"非归档 {counts['non_archive']} 份 / {counts['directories']} 目录;"
        f"归档 {counts['archive']} = {counts['archive_specs']} spec + {counts['archive_plans']} plan;"
        f"接口 {counts['api_operations']} 个(表 {counts['api_table_rows']} 行)"
    )


if __name__ == "__main__":
    sys.exit(main())
