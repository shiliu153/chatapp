#!/usr/bin/env python3
"""校验 `docs/` 的六条规则:结构、断链、索引覆盖、元信息、术语、手写计数。

为什么需要它
------------
治理方案(`docs/superpowers/archive/specs/2026-11-14-docs-and-scripts-governance-design.md`)
§3.3 把「文档结构」变成了可机械判定的目标:

1. `docs/` 下的脚本 / 补丁 / 二进制 **0 个**;
2. 非归档文档被索引覆盖 **100%**;
3. 相对链接 **0 条断**;
4. 非归档文档的头部元信息(状态 / 复核)齐全;
5. 作用域内禁用术语 **0 处**;
6. 分册首句的手写接口数与接口一览表一致。

这些规则的共同点是**坏了没人当场知道**:脚本躺在文档目录里不会让任何测试红,一份新文档
没进索引也照样能提交,断链只有人在浏览器里点开才看得见,而「六轨」这类术语会一直
写着 —— 直到有人发现它和 10 个 workflow 的事实脱钩。所以它必须是一道门禁,
不能是「大家记得」的纪律。写作规范的 owner 是 `docs/standards/writing.md`。

判什么、不判什么
----------------
判(**六条规则,各自独立**):

- **structure**:`docs/` 下只允许 `.md` / `.yml` / `.json` / 图片
  (`.png .jpg .jpeg .webp .svg`)。脚本、补丁、可执行文件一律进 `scripts/`。
  归档目录同样受此约束 —— 归档只 `git mv`,不新增别的类型。
- **broken-link**:**直接复用** ``scripts.check_docs_links.find_broken_links``,
  不重写链接解析(那边已经把「什么算链接」判准了,重写一份只会产生两套口径)。
- **unindexed**:非归档 `.md` 必须被某个索引文件以**相对链接**指向。索引文件 =
  仓库根的 `README.md` / `CLAUDE.md` / `AGENTS.md` + `docs/` 下任意层级的 `README.md`。
  `docs/superpowers/archive/` 不参与(历史文档保持原样,spec §6)。
- **metadata**:非归档 `.md` 的 front-matter 必须有 `状态` 与 `复核`,且取值合法。
  `docs/superpowers/` 豁免 —— 它的状态 owner 是该目录 README §2 的工作面表,
  元信息再写一份就是同一事实两处(规则细节见 `docs/standards/writing.md` §2)。
- **term**:作用域内禁用术语 0 处。作用域**刻意收窄**到活文档(根三份 +
  `docs/{ops,standards,api,pitfalls,backlog}/**`):归档与常驻 spec 是历史,不改写;
  一次性报告与教学材料同理。`docs/standards/sources-of-truth.md` 整文件白名单
  —— 它本身在**定义**这些禁用词。行内豁免 ``<!-- lint:allow:term -->`` 只豁免它所在的行。
- **number**:`docs/api/*.md` 首句「本分册含 N 个接口」必须等于「接口一览」表里指向该分册
  的行数。这是全仓唯一成体系的手写计数;其余 `N 份` / `N 条` 属历史叙事或已由生成器覆盖,
  机械禁会把门禁变成噪音源。

不判(**刻意**,判不准或会变成噪音):

- 链接锚点是否存在(要解析标题锚点规则,误报率高);
- 外链是否可达(需要联网,会因对方站点抖动误报);
- 「索引文件自己是否被索引」—— 根那三份是入口,不要求被指向;子 `README.md` 要。
- 历史叙事里的数字(`docs/milestones.md`、发版记录、一次性报告)—— 那是「当时的事实」,
  逼着改等于改写历史。

用法
----
    python scripts/docs_lint.py              # 人读:逐条打印违例
    python scripts/docs_lint.py --json       # 机器读:L4 判定器复用
    python scripts/docs_lint.py --root .     # 自测:换一个仓库根

退出码:0 = 0 违例;1 = 有违例;2 = 判定器自己出错(目录不对 / 一个文件都没扫到)。

文件信息:
    文件名称          scripts/docs_lint.py
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
import re
import sys
from pathlib import Path
from typing import Dict, List, Set

# `python scripts/docs_lint.py` 时 sys.path[0] 是 scripts/,所以要显式把仓库根放进去,
# 这样 `from scripts import check_docs_links` 两种调用方式(直接跑 / unittest)都成立。
# 与 `scripts/l4_intake.py` 用的是同一段处理。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import check_docs_links, docs_index  # noqa: E402  (必须在 sys.path 修好之后)

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

#: 元信息规则的必填字段(与 `docs/standards/writing.md` §2 一致)。
METADATA_REQUIRED_FIELDS = ("状态", "复核")

#: `状态` 的合法取值。
METADATA_STATES = ("生效中", "常驻", "一次性", "已归档")

#: `复核` 的周期短语:出现任一即算「写了复核节奏」。
METADATA_REVIEW_CYCLES = (
    "每次",
    "每周",
    "每月",
    "每季度",
    "每年",
    "每轮",
    "每批",
    "每节",
    "发版前",
    "交付后",
    "立项时",
    "归档时",
    "变更时",
    "审计后",
    "巡检时",
)

#: `复核` 的「不再复核」写法(一次性文档)。
METADATA_REVIEW_NONE = "无(一次性)"

#: 元信息豁免:相对 `docs/` 的首段目录 —— `superpowers/` 的状态 owner 是该目录 README §2。
METADATA_EXEMPT_TOP = ("superpowers",)

#: front-matter 块(文件开头的两个 `---` 之间)。
FRONT_MATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.DOTALL)

#: front-matter 里的 `键: 值` 行。
FRONT_MATTER_LINE_RE = re.compile(r"^([A-Za-z_\u4e00-\u9fff]+)\s*[:：]\s*(.+?)\s*$")

#: 术语规则的作用域:根入口三份。
TERM_ROOT_FILES = ("README.md", "CLAUDE.md", "AGENTS.md")

#: 术语规则的作用域:`docs/` 下这些子目录(相对 `docs/`),即「活文档」。
TERM_DOC_DIRS = ("ops", "standards", "api", "pitfalls", "backlog")

#: 禁用术语(完整表见 `docs/standards/sources-of-truth.md` §5)。
BANNED_TERMS = ("六轨", "CI 四轨", "三轮安全审计")

#: 术语规则的白名单:整文件豁免(口径页本身在**定义**这些禁用词)。
TERM_WHITELIST = ("docs/standards/sources-of-truth.md",)

#: 行内豁免标记:只豁免它所在的那一行。
TERM_ALLOW_MARKER = "<!-- lint:allow:term -->"

#: 分册首句的手写计数形态(`本分册含 3 个接口`)。
NUMBER_VOLUME_RE = re.compile(r"本分册含\s*(\d+)\s*个接口")

#: 接口文档目录名(相对 `docs/`)。
API_DOCS_SUBDIR = "api"


def _is_archived(path: Path, docs_dir: Path) -> bool:
    """判断一个路径是否落在 `docs/superpowers/archive/` 子树里。

    参数说明:
        path: 待判断的绝对路径(通常是 `docs/` 下的某个文件)。
        docs_dir: `docs/` 目录的绝对路径。

    返回参数:
        落在归档子树里返回 ``True``;不在 `docs/` 下也返回 ``True``(不在判定范围内)。

    使用示例:
        ``_is_archived(path, docs_dir)``

    备注信息:
        无特殊约束。
    """
    try:
        parts = path.resolve().relative_to(docs_dir.resolve()).parts
    except ValueError:
        return True
    return parts[: len(ARCHIVE_PARTS)] == ARCHIVE_PARTS


def find_misplaced_files(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[str]:
    """找出 `docs/` 下不该出现的文件(结构规则)。

    参数说明:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名,默认 `docs`。

    返回参数:
        违规文件的仓库相对路径列表,按路径排序。空列表表示结构合规。

    使用示例:
        ``find_misplaced_files(repo_root, docs_subdir)``

    备注信息:
        抛 ``FileNotFoundError``:文档目录不存在 —— 那是「判不出来」,不是「合规」。
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

    参数说明:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名,默认 `docs`。

    返回参数:
        索引文件的绝对路径列表,按路径排序;不存在的根入口会被跳过。

    使用示例:
        ``index_files(repo_root, docs_subdir)``

    备注信息:
        索引文件 = 仓库根的 `README.md` / `CLAUDE.md` / `AGENTS.md` + `docs/` 下任意层级的
        `README.md`(归档子树除外)。归档里的 README 不参与:历史文档不改,也不该拿它当入口。
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

    参数说明:
        repo_root: 仓库根目录。
        index: 索引文件的绝对路径。

    返回参数:
        规范化后的绝对路径集合;外链、纯锚点、站点根路径已被上游过滤掉。

    使用示例:
        ``linked_targets(repo_root, index)``

    备注信息:
        这里**复用** ``check_docs_links`` 的解析实现(抹代码 → 取目标 → 解析成绝对路径),
        而不是另写一套正则:链接语义只允许有一个口径,两套实现必然分叉。
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

    参数说明:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名,默认 `docs`。

    返回参数:
        未被覆盖的文档仓库相对路径列表,按路径排序。空列表表示 100% 覆盖。

    使用示例:
        ``find_unindexed_docs(repo_root, docs_subdir)``

    备注信息:
        抛 ``FileNotFoundError``:文档目录不存在。
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


def parse_front_matter(text: str) -> Dict[str, str] | None:
    """解析文件开头的 front-matter 块。

    参数说明:
        text: 文件全文(换行已被 ``Path.read_text`` 归一化,不影响行号)。

    返回参数:
        键值字典;文件开头没有 front-matter 时返回 ``None``。

    使用示例:
        ``parse_front_matter(text)``

    备注信息:
        只认**文件第一行**就是 `---` 的块(与写作规范一致);正文里的 `---` 是水平分隔线,
        不是元信息。键值按 `键: 值` 解析,`#` 开头的行当注释跳过。
    """
    match = FRONT_MATTER_RE.match(text)
    if not match:
        return None
    fields: Dict[str, str] = {}
    for line in match.group(1).splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        pair = FRONT_MATTER_LINE_RE.match(stripped)
        if pair:
            fields[pair.group(1)] = pair.group(2)
    return fields


def review_value_ok(value: str) -> bool:
    """判断 `复核` 字段的取值是否合法。

    参数说明:
        value: `复核` 字段的原始值。

    返回参数:
        合法返回 ``True``。

    使用示例:
        ``review_value_ok(value)``

    备注信息:
        合法形态只有三种(见 `docs/standards/writing.md` §2):反引号命令、周期短语、
        ``无(一次性)``。**日期不算** —— 写日期会变成一条没人验证过的假数据。
    """
    if METADATA_REVIEW_NONE in value:
        return True
    if "`" in value:
        return True
    return any(cycle in value for cycle in METADATA_REVIEW_CYCLES)


def find_metadata_violations(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[dict]:
    """检查非归档文档的头部元信息(metadata 规则)。

    参数说明:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名,默认 `docs`。

    返回参数:
        违例项列表,每项形如 ``{"file": ..., "line": 1, "message": ...}``,按文件排序。

    使用示例:
        ``find_metadata_violations(repo_root, docs_subdir)``

    备注信息:
        作用域是 `docs/` 下全部非归档 `.md`,但 `docs/superpowers/` 豁免 —— 那里的状态 owner
        是该目录 README §2 的工作面表,元信息再写一份就是同一事实两处。
        抛 ``FileNotFoundError``:文档目录不存在。
    """
    repo_root = repo_root.resolve()
    docs_dir = repo_root / docs_subdir
    if not docs_dir.is_dir():
        raise FileNotFoundError(f"找不到文档目录:{docs_dir}")

    violations: List[dict] = []
    for path in sorted(docs_dir.rglob("*.md")):
        if not path.is_file() or _is_archived(path, docs_dir):
            continue
        parts = path.relative_to(docs_dir).parts
        if parts and parts[0] in METADATA_EXEMPT_TOP:
            continue
        rel = path.relative_to(repo_root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        fields = parse_front_matter(text)
        if fields is None:
            violations.append(
                {
                    "file": rel,
                    "line": 1,
                    "message": "缺少头部元信息(front-matter):应有 状态 / 复核,写法见 docs/standards/writing.md §2",
                }
            )
            continue

        missing = [name for name in METADATA_REQUIRED_FIELDS if not fields.get(name)]
        if missing:
            violations.append(
                {"file": rel, "line": 1, "message": f"头部元信息缺字段:{'、'.join(missing)}"}
            )
        state = fields.get("状态", "")
        if state and state not in METADATA_STATES:
            violations.append(
                {
                    "file": rel,
                    "line": 1,
                    "message": f"状态「{state}」不合法,只能是 {' / '.join(METADATA_STATES)}",
                }
            )
        review = fields.get("复核", "")
        if review and not review_value_ok(review):
            violations.append(
                {
                    "file": rel,
                    "line": 1,
                    "message": f"复核「{review}」不是合法形态:写反引号命令、周期短语(每次 / 发版前 …)或 无(一次性),不写日期",
                }
            )
    return violations


def term_scope_files(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[Path]:
    """列出术语规则的作用域文件(活文档)。

    参数说明:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名,默认 `docs`。

    返回参数:
        作用域文件的绝对路径列表,按路径排序;不存在的目录跳过。

    使用示例:
        ``term_scope_files(repo_root, docs_subdir)``

    备注信息:
        作用域 = 仓库根三份入口 + `docs/{ops,standards,api,pitfalls,backlog}/**`。
        归档、常驻 spec、一次性报告、教学材料、生成的 `docs/README.md` 都不在其中
        (理由见 `docs/standards/writing.md` §5.2)。
    """
    repo_root = repo_root.resolve()
    files: List[Path] = [repo_root / name for name in TERM_ROOT_FILES if (repo_root / name).is_file()]
    docs_dir = repo_root / docs_subdir
    if docs_dir.is_dir():
        for name in TERM_DOC_DIRS:
            sub = docs_dir / name
            if not sub.is_dir():
                continue
            files.extend(path for path in sorted(sub.rglob("*.md")) if path.is_file())
    return files


def find_term_violations(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[dict]:
    """找出作用域内出现禁用术语的行(term 规则)。

    参数说明:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名,默认 `docs`。

    返回参数:
        违例项列表,每项带 ``file`` / ``line`` / ``term`` / ``message``,按路径与行号排序。

    使用示例:
        ``find_term_violations(repo_root, docs_subdir)``

    备注信息:
        白名单整文件跳过;行内标记 ``<!-- lint:allow:term -->`` 只豁免它所在的那一行 ——
        不提供「随手关掉整份文档」的口子。
    """
    repo_root = repo_root.resolve()
    workflows = count_workflows(repo_root)
    replacement = f"workflow(当前 {workflows} 个)" if workflows else "workflow(当前 N 个)"

    violations: List[dict] = []
    for path in term_scope_files(repo_root, docs_subdir):
        rel = path.relative_to(repo_root).as_posix()
        if rel in TERM_WHITELIST:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            if TERM_ALLOW_MARKER in line:
                continue
            for term in BANNED_TERMS:
                if term in line:
                    violations.append(
                        {
                            "file": rel,
                            "line": lineno,
                            "term": term,
                            "message": (
                                f"禁用术语「{term}」:改说「{replacement}」或点名具体轨;"
                                f"确需引用该词时在行尾加 {TERM_ALLOW_MARKER}"
                            ),
                        }
                    )
    return violations


def count_workflows(repo_root: Path) -> int:
    """数一数 `.github/workflows/` 下的 workflow 文件(给术语提示写「当前 N 个」)。

    参数说明:
        repo_root: 仓库根目录。

    返回参数:
        `.yml` / `.yaml` 文件个数;目录不存在时返回 0(提示退化成「当前 N 个」)。

    使用示例:
        ``count_workflows(repo_root)``

    备注信息:
        无特殊约束。
    """
    wf_dir = repo_root.resolve() / ".github" / "workflows"
    if not wf_dir.is_dir():
        return 0
    return len(
        [path for path in wf_dir.iterdir() if path.is_file() and path.suffix in (".yml", ".yaml")]
    )


def find_number_violations(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[dict]:
    """核对分册首句的手写接口数(number 规则)。

    参数说明:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名,默认 `docs`。

    返回参数:
        违例项列表,每项带 ``file`` / ``line`` / ``message``,按路径排序。

    使用示例:
        ``find_number_violations(repo_root, docs_subdir)``

    备注信息:
        只判一种形态:`docs/api/*.md` 里的「本分册含 N 个接口」必须等于「接口一览」表里
        指向该分册的行数。这是全仓唯一成体系的手写计数;其余 `N 份` / `N 条` / `N 个操作`
        是历史叙事或已由生成器覆盖,机械禁会把门禁变成噪音源。
        没写这句话的分册不判(可选句式:写了就必须对)。
    """
    repo_root = repo_root.resolve()
    api_dir = repo_root / docs_subdir / API_DOCS_SUBDIR
    if not api_dir.is_dir():
        return []
    if not (api_dir / INDEX_BASENAME).is_file():
        # 没有接口一览表就没有可比的派生量 —— 判不出来时**不判**,而不是把每一句都判红。
        return []
    try:
        counts = docs_index.api_volume_counts(repo_root)
    except (OSError, FileNotFoundError):
        return []

    violations: List[dict] = []
    for path in sorted(api_dir.glob("*.md")):
        if not path.is_file() or path.name == INDEX_BASENAME:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for lineno, line in enumerate(lines, 1):
            match = NUMBER_VOLUME_RE.search(line)
            if not match:
                continue
            declared = int(match.group(1))
            actual = counts.get(path.name, 0)
            if declared != actual:
                violations.append(
                    {
                        "file": path.relative_to(repo_root).as_posix(),
                        "line": lineno,
                        "message": (
                            f"「本分册含 {declared} 个接口」与接口一览表不一致:"
                            f"表里指向 {path.name} 的有 {actual} 行"
                        ),
                    }
                )
            break
    return violations


def lint(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[dict]:
    """跑全部六条规则,返回一个扁平的违例列表。

    参数说明:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名,默认 `docs`。

    返回参数:
        违例列表,每项形如 ``{"rule": "structure", "file": "docs/ops/x.sh", "line": 0, "message": "..."}``。 断链项另带 ``target`` / ``resolved`` / ``suggestion``;术语项另带 ``term``。 按 ``(rule, file, line)`` 排序以保证输出稳定。

    使用示例:
        ``lint(repo_root, docs_subdir)``

    备注信息:
        抛 ``FileNotFoundError``:文档目录不存在。
        抛 ``OSError``:有文档读不了 —— 判不出来,交给上层 fail-closed。
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

    for item in find_metadata_violations(repo_root, docs_subdir):
        violations.append({"rule": "metadata", **item})

    for item in find_term_violations(repo_root, docs_subdir):
        violations.append({"rule": "term", **item})

    for item in find_number_violations(repo_root, docs_subdir):
        violations.append({"rule": "number", **item})

    violations.sort(key=lambda item: (item["rule"], item["file"], item["line"]))
    return violations


def count_docs(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> int:
    """数一数扫到了多少份 Markdown,用来区分「合规」与「一个都没扫到」。

    参数说明:
        repo_root: 仓库根目录。
        docs_subdir: 相对 `repo_root` 的文档目录名,默认 `docs`。

    返回参数:
        `docs/` 下 `.md` 文件的个数;目录不存在时返回 0。

    使用示例:
        ``count_docs(repo_root, docs_subdir)``

    备注信息:
        后者是真故障(检出目录不对 / 路径变了),不该被当成「0 违例」悄悄通过 ——
        与 ``check_docs_links.count_markdown_files`` 是同一个理由。
    """
    return check_docs_links.count_markdown_files(Path(repo_root), docs_subdir)


def _describe(item: dict) -> str:
    """把一条违例渲染成人读的一行(含可执行的改法候选)。

    参数说明:
        item: ``lint`` 返回的违例项。

    返回参数:
        形如 ``[rule] docs/a.md:12 → 目标 (解析为 ...)`` 的字符串,候选行按需追加。

    使用示例:
        ``_describe(item)``

    备注信息:
        无特殊约束。
    """
    where = item["file"] if not item.get("line") else f"{item['file']}:{item['line']}"
    line = f"[{item['rule']}] {where}  {item['message']}"
    if item.get("suggestion"):
        line += f"\n    候选(同名文件唯一):{item['suggestion']}"
    return line


def main(argv: List[str] | None = None) -> int:
    """命令行入口:跑六条规则并输出结果,返回退出码。

    参数说明:
        argv: 命令行参数列表;``None`` 表示用 ``sys.argv[1:]``。

    返回参数:
        0 = 0 违例;1 = 有违例;2 = 判定器自身出错。

    使用示例:
        ``python scripts/docs_lint.py``

    备注信息:
        无特殊约束。
    """
    parser = argparse.ArgumentParser(
        description=(
            "校验 docs/ 的六条规则:放错位置的文件、断链、未被索引的文档、"
            "头部元信息、禁用术语、分册手写计数"
        )
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
            print(f"docs/ 合规:扫描 {scanned} 份 Markdown,0 违例")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
