#!/usr/bin/env python3
"""文档关键数字的机械化:一个计算源 + 哨兵注入 + 三层判定。

为什么需要它
------------
治理第 3 节(2026-11-14,``docs_index.py``)解决了「目录 / 归档 / 接口数」的漂移,
但**正文里的内联数字**没人管。设计文档(``2026-11-16-facts-numbers-design.md``)记录了三个
实测缺口,最关键的一个是「同一份活文档里两个数字互相矛盾」::

    docs/ops/capacity-and-reliability.md:20   「17 条告警」
    docs/ops/capacity-and-reliability.md:131  「Prometheus + Grafana + 10 条告警」
    deploy/observability/alerts.yml            实际 17 条

手写的数字会消失,但**错误的数字不会自己变红**。所以:能数出来的数字交给脚本写,
不是人写 —— 与 ``docs_index.py`` 同一条思路,只是粒度从「整段/整表」降到「句子里的一个数」。

三层结构
--------
1. **计算层**:``FACTS`` 表。每个事实 = id + 说明 + 计算函数 + 断言正则。
   计算函数**只许读文件或复用既有脚本的函数** —— 禁止跑测试、起容器、联网。
   ``contract`` 轨必须秒级,这条硬约束把「测试用例数」这类数字挡在机制外(见设计 §3.5)。
2. **渲染层**(``--write``):把哨兵里的值刷新成计算值,并把命中断言正则的**裸数字**
   就地包上哨兵。只替换捕获组那一段,句子其余部分一字不动。
3. **判定层**(``--check``):三条规则,任一条不满足即红。

    ==========  ========================================================
    R1 值        每个哨兵里的值必须等于计算值
    R2 强制哨兵  作用域内命中某事实断言正则的裸数字**即使数值正确也红**
    R3 位置      哨兵不得出现在 ATX 标题与代码围栏内
    ==========  ========================================================

哨兵写法::

    共 <!-- num:gates_total -->41<!-- /num --> 道门禁

HTML 注释在 GitHub 与本地预览里都不渲染,读者看到的是「共 41 道门禁」;值可以是字符串
(``gates_contract`` 的值是 ``27 / 27``)。

为什么 R2 要「数值对了也红」
--------------------------
留一个「反正我写对了」的口子,等于把机制退化成「今天对」——加一个 workflow、加一道门禁之后
它就不对了,而没有人会记得回来改。R2 的代价是**迁移面从「错的数字」变成「所有出现处」**,
好在 ``--write`` 一次就能做完。

R2 的作用域必须收紧(否则第一版就红一片然后被人关掉 —— 本仓库 ``term`` 规则的前车之鉴):
**只有注册表里声明过的形态受约束**。门禁条数之外的「120 次/小时」「≤50 条」「476 rps」
不匹配任何正则,自然不受影响。断言正则因此**必须带上下文词组**(``\\d+ 条告警``,
绝不写 ``\\d+ 条``)。

判什么、不判什么
----------------
判(R1 / R2 / R3,全部机械)。

不判(**刻意**):

- **B 类规格数字**(阈值 / 上限 / TTL):从代码取会让手册退化成配置镜像;
- **测试用例数**:要跑全量测试才有真数,``contract`` 轨等不起 —— 它是**禁用写法**
  (``docs_lint`` 的 ``number`` 规则后半边),不是本脚本的事实;
- **C++ 注释块数**:要 tree-sitter 才数得准,``docs/standards/cpp.md`` 已给出复跑命令;
- **历史文档**(``milestones.md`` / ``reports/`` / ``security/`` / ``reviews/`` /
  ``learning/`` / ``superpowers/**``):那是「当时的事实」,改它等于改写证据。

豁免
----
- **整文件**:``docs/standards/sources-of-truth.md``(它**故意**保留历史数字,如
  「当时 21 / 21,现 27 / 27」,逐句判会把治理档案逼成假话);
  ``docs/README.md`` 与 ``docs/api/README.md``(生成物,``docs_index.py`` 负责,两个生成器
  不抢同一份文件)。
- **行内**:``<!-- lint:allow:number -->`` 加在行尾,只豁免它所在的那一行。

用法
----
    python scripts/facts.py --check      # 等同默认:逐条打印违例,退出码 1 = 有不一致
    python scripts/facts.py --write      # 刷新哨兵值 + 把裸数字包上哨兵
    python scripts/facts.py --report     # 人读:每个事实算出多少、命中哪些位置
    python scripts/facts.py --json       # 机器读
    python scripts/facts.py --root .     # 自测:换一个仓库根

    # 改了会动 A 类数字的东西(加 workflow / 加门禁 / 加接口 / 增删文档 / 改告警规则 /
    # 加业务码)之后:
    python scripts/facts.py --write && python scripts/facts.py --check

退出码:0 = 全部一致;1 = 有违例;2 = 判不出来(目录不对、某个事实算不出来、参数冲突)。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Sequence, Tuple

# `python scripts/facts.py` 时 sys.path[0] 是 scripts/,显式把仓库根放进去,
# 这样 `from scripts import ...` 两种调用方式(直接跑 / unittest)都成立。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import docs_index, run_gates  # noqa: E402  (必须在 sys.path 修好之后)

#: 文档目录名(相对仓库根)。
DOCS_SUBDIR = "docs"

#: 哨兵语法:``<!-- num:<id> -->值<!-- /num -->``。值单行,允许任意文本(如 ``27 / 27``)。
SENTINEL_RE = re.compile(r"<!--\s*num:([a-z0-9_]+)\s*-->([^\n]*?)<!--\s*/num\s*-->")

#: 渲染哨兵(写入时用)。
SENTINEL_TEMPLATE = "<!-- num:{id} -->{value}<!-- /num -->"

#: 行内豁免标记:只豁免它所在的那一行(与 ``term`` 规则的 ``lint:allow:term`` 同一套机制)。
NUMBER_ALLOW_MARKER = "<!-- lint:allow:number -->"

#: ATX 标题行(R3:标题里不许有哨兵 —— 那会把 anchor 打碎,目录链接全断)。
HEADING_RE = re.compile(r"^#{1,6}\s")

#: 代码围栏行(``` 或 ~~~ 开头,允许缩进)。
FENCE_RE = re.compile(r"^\s*(```|~~~)")

#: 判定规则的作用域:根入口三份(与 ``docs_lint`` 的 ``term`` 规则同款)。
SCOPE_ROOT_FILES = ("README.md", "CLAUDE.md", "AGENTS.md")

#: 判定规则的作用域:``docs/`` 下这些子目录(即「活文档」)。
#:
#: **``backlog/`` 刻意不在其中**:它虽然叫「当前工作面」,但绝大多数内容是「某日交付时
#: 的数字」(``接口 47 个操作`` / ``后端 709 测试绿``),与 ``milestones.md`` 同类 ——
#: 把它们改成今天的事实等于改写证据。目前待办里几乎不写统计数字,覆盖它的收益远小于
#: 强迫人给每条历史记录加豁免标记的成本。
SCOPE_DOC_DIRS = ("ops", "standards", "api", "pitfalls")

#: 整文件豁免(仓库相对路径)。
#:
#: - ``sources-of-truth.md``:口径页,**故意**保留历史数字与裁决过程;
#: - ``docs/README.md`` / ``docs/api/README.md``:``docs_index.py`` 的生成物,
#:   由那条生成器自己保证一致,这里再判一遍会让两个生成器抢同一份文件;
#: - ``docs/milestones.md``:交付时间线,写的是「当时的事实」,只增不改。
EXEMPT_FILES = (
    "docs/standards/sources-of-truth.md",
    "docs/README.md",
    "docs/api/README.md",
    "docs/milestones.md",
)


@dataclass(frozen=True)
class Fact:
    """一个「能数出来的数字」的完整定义。

    Attributes:
        id: 哨兵里用的标识(小写字母 + 下划线),也是报错时被点名的东西。
        summary: 人读说明 —— 这个数字是什么(``--report`` 与报错都用它)。
        compute: 计算函数:仓库根 → 该数字的字符串形态。
        patterns: 断言正则元组。每个正则**恰好一个捕获组**,组内是数字形态
            (可能含空格,如 ``25 / 25``);判定与迁移只认捕获组那一段。
    """

    id: str
    summary: str
    compute: Callable[[Path], str]
    patterns: Tuple[re.Pattern, ...]


# ---------------------------------------------------------------- 计算

#: 中间允许空白与 ``*``(加粗标记):文档里同一个数字常被 ``**…**`` 包着,
#: 正则若不容忍 ``*``,「**17 条**告警」这种写法就会漏判 —— 漏判等于门禁形同虚设。
_GAP = r"[\s*]*"


def _pattern(*tokens: str) -> re.Pattern:
    """把若干字面量片段拼成一个「允许中间有空白 / 加粗标记」的正则。

    数字位用 ``(\\d+)`` 显式写在片段里(它就是要被替换的那一段)。

    Args:
        tokens: 片段序列,原样拼进正则,彼此之间插入 :data:`_GAP`。

    Returns:
        编译好的正则(带 :data:`re.UNICODE`,不需要 DOTALL —— 判定是逐行的)。

    Raises:
        re.error: 片段里的正则语法不合法(写错就当场炸,不要静默退化)。
    """
    return re.compile(_GAP.join(tokens))


def _count_files(directory: Path, suffixes: Sequence[str]) -> int:
    """数一个目录下指定后缀的文件(不递归)。目录不存在时返回 0。

    Args:
        directory: 目录。
        suffixes: 允许的后缀(小写,如 ``(".yml", ".yaml")``)。

    Returns:
        文件个数;目录不存在返回 0(由调用方决定 0 是否合理)。
    """
    if not directory.is_dir():
        return 0
    return len(
        [path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in suffixes]
    )


def _workflows(root: Path) -> str:
    """数 ``.github/workflows/`` 下的 workflow 文件。

    Args:
        root: 仓库根目录。

    Returns:
        workflow 文件个数的字符串。
    """
    return str(_count_files(root / ".github" / "workflows", (".yml", ".yaml")))


def _gates_total(root: Path) -> str:
    """数 ``scripts/gates.toml`` 里注册的门禁总数。

    复用 ``scripts.run_gates.load_registry``:它已经做了字段校验与排序,
    在这里另写一份 TOML 解析只会得到第二套口径。

    Args:
        root: 仓库根目录。

    Returns:
        门禁总数的字符串。

    Raises:
        run_gates.RegistryError: 注册表不合法(判不出来,不是「一致」)。
    """
    return str(len(run_gates.load_registry(_gates_config(root))))


def _gates_contract(root: Path) -> str:
    """数 ``contract`` 组的门禁条数,渲染成 ``N / N``。

    本地与 CI 跑的是同一份清单,所以两边条数必然相等 —— 写成一个值而不是两个数,
    是为了让「本地 25 / CI 27」这种漂移在形态上就不可能出现。

    Args:
        root: 仓库根目录。

    Returns:
        形如 ``27 / 27`` 的字符串。

    Raises:
        run_gates.RegistryError: 注册表不合法。
    """
    scope = "contract"
    count = sum(1 for gate in run_gates.load_registry(_gates_config(root)) if gate.scope == scope)
    return f"{count} / {count}"


def _gates_config(root: Path) -> Path:
    """返回某个仓库根下的门禁注册表路径。

    Args:
        root: 仓库根目录。

    Returns:
        ``<root>/scripts/gates.toml``。
    """
    return Path(root) / "scripts" / "gates.toml"


def _api_operations(root: Path) -> str:
    """数 ``openapi.yml`` 里的操作数(方法 + 路径)。

    Args:
        root: 仓库根目录。

    Returns:
        操作个数的字符串。

    Raises:
        ValueError: 契约里一个操作都没解析出来(格式变了,判定器该响)。
    """
    return str(len(docs_index.parse_openapi_operations(root)))


def _api_paths(root: Path) -> str:
    """数 ``openapi.yml`` 里的路径数(同一路径的多个方法算一个)。

    Args:
        root: 仓库根目录。

    Returns:
        路径个数的字符串。
    """
    return str(len({path for _method, path in docs_index.parse_openapi_operations(root)}))


def _docs_non_archive(root: Path) -> str:
    """数非归档文档份数。

    Args:
        root: 仓库根目录。

    Returns:
        份数字符串。
    """
    return str(docs_index.summarize(root)["non_archive"])


def _docs_archive(root: Path) -> str:
    """数归档文档份数(不含生成的 INDEX.md 自己)。

    Args:
        root: 仓库根目录。

    Returns:
        份数字符串。
    """
    return str(docs_index.summarize(root)["archive"])


def _docs_total(root: Path) -> str:
    """数 ``docs/`` 下全部 Markdown 份数(含两份生成物,去掉重复计数的麻烦)。

    Args:
        root: 仓库根目录。

    Returns:
        份数字符串。
    """
    docs_dir = Path(root) / DOCS_SUBDIR
    if not docs_dir.is_dir():
        return "0"
    return str(len([path for path in docs_dir.rglob("*.md") if path.is_file()]))


def _alert_rules(root: Path) -> str:
    """数 ``deploy/observability/alerts.yml`` 里的告警规则条数。

    规则形态是 YAML 列表项 ``- alert: <名字>``;这里数行而不是解析 YAML ——
    仓库是纯标准库约束(不引 PyYAML),而该文件的形态由 ``contract-observability-selftest``
    守着,行计数足够且不会因为版本差异变行为。

    Args:
        root: 仓库根目录。

    Returns:
        规则条数的字符串。

    Raises:
        FileNotFoundError: 告警规则文件不存在 —— 那是「判不出来」,不是 0 条。
    """
    path = Path(root) / "deploy" / "observability" / "alerts.yml"
    if not path.is_file():
        raise FileNotFoundError(f"找不到告警规则:{path}")
    text = path.read_bytes().decode("utf-8")
    return str(len(re.findall(r"^\s*-\s*alert:\s*\S", text, re.MULTILINE)))


def _error_codes(root: Path) -> str:
    """数业务码个数(去重)。

    Args:
        root: 仓库根目录。

    Returns:
        业务码个数的字符串。

    Raises:
        ValueError: 一个码都没读到(格式变了)。
    """
    return str(len(set(docs_index.read_error_codes(root))))


#: 事实注册表 —— **A 类(统计型)数字的唯一事实来源**。
#:
#: 新增一条事实的改动点 = 这里加一项(计算函数 + 断言正则),再跑一次 ``--write``。
#: 顺序即 ``--report`` 的输出顺序,按 id 的 POSIX 字节序排(跨平台稳定)。
FACTS: Tuple[Fact, ...] = (
    Fact(
        id="alert_rules",
        summary="deploy/observability/alerts.yml 里的告警规则条数",
        compute=_alert_rules,
        # 第二个模式刻意带上「看板」前缀:裸的 ``N 条规则`` 会命中不相关的东西
        # (实测 ``docs/ops/superagent.md`` 的「加载 867 条规则」讲的是 mihomo 的规则数)。
        # 宁可漏判不可误报 —— 漏判只是少守一处,误报会把人逼着把门禁关掉。
        patterns=(
            _pattern(r"(\d+)", r"条", r"告警"),
            # 表格里那一格写作 ``| 告警规则 / 看板 | **17 条规则** |`` —— 中间隔着单元格
            # 分隔符,所以这一条不用 :data:`_GAP`(它不含 ``|``),单独写。
            re.compile(r"看板[\s|*]*(\d+)[\s*]*条[\s*]*规则"),
        ),
    ),
    Fact(
        id="api_operations",
        summary="openapi.yml 里的操作数(方法 + 路径)",
        compute=_api_operations,
        patterns=(
            _pattern(r"(\d+)", r"个", r"操作"),
            _pattern(r"(\d+)", r"operations"),
        ),
    ),
    Fact(
        id="api_paths",
        summary="openapi.yml 里的路径数",
        compute=_api_paths,
        patterns=(_pattern(r"(\d+)", r"paths"),),
    ),
    Fact(
        id="docs_archive",
        summary="归档文档份数(docs/superpowers/archive/)",
        compute=_docs_archive,
        # 负向前瞻挡住「非归档 80 份」被当成归档:两个事实共用「归档」这个词。
        patterns=(_pattern(r"(?<!非)归档", r"(\d+)", r"份"),),
    ),
    Fact(
        id="docs_non_archive",
        summary="非归档文档份数",
        compute=_docs_non_archive,
        patterns=(_pattern(r"非归档", r"(\d+)", r"份"),),
    ),
    Fact(
        id="docs_total",
        summary="docs/ 下全部 Markdown 份数(含两份生成物)",
        compute=_docs_total,
        patterns=(_pattern(r"docs/`,?", r"下", r"(\d+)", r"份"),),
    ),
    Fact(
        id="error_codes",
        summary="chatapp/config/error_codes.py 里的业务码个数",
        compute=_error_codes,
        patterns=(_pattern(r"(\d+)", r"个", r"业务码"),),
    ),
    Fact(
        id="gates_contract",
        summary="contract 组门禁条数(本地与 CI 同一条数,渲染成 N / N)",
        compute=_gates_contract,
        patterns=(
            _pattern(r"`contract`", r"组", r"\*{0,2}", r"(\d+[\s*]*/[\s*]*\d+)"),
        ),
    ),
    Fact(
        id="gates_total",
        summary="scripts/gates.toml 注册的门禁总数",
        compute=_gates_total,
        patterns=(_pattern(r"共", r"(\d+)", r"道门禁"),),
    ),
    Fact(
        id="workflows",
        summary=".github/workflows/ 下的 workflow 文件个数",
        compute=_workflows,
        patterns=(
            _pattern(r"workflow[（(]", r"当前", r"(\d+)", r"个"),
            _pattern(r"workflows/`", r"现在", r"(\d+)", r"个文件"),
        ),
    ),
)

#: id → 事实,判定时按 id 反查哨兵。
FACTS_BY_ID: Dict[str, Fact] = {fact.id: fact for fact in FACTS}


# ---------------------------------------------------------------- 作用域


def scope_files(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[Path]:
    """列出参与判定的文档(活文档,已排除整文件豁免项)。

    与 ``docs_lint`` 的 ``term`` 规则同一套作用域(根三份入口 + 活文档目录),另加
    ``docs/`` 根的散装文档(``architecture.md`` 就在这里,它写过「workflow(当前 N 个)」)。
    历史文档(``milestones.md``、``backlog/``、``reports/``、``security/``、``reviews/``、
    ``learning/``、``superpowers/**``)刻意不在其中 —— 改历史等于改写证据。

    Args:
        repo_root: 仓库根目录。
        docs_subdir: 相对 ``repo_root`` 的文档目录名,默认 ``docs``。

    Returns:
        作用域文件的绝对路径列表,按 ``as_posix()`` 排序(跨平台稳定);不存在的跳过。
    """
    root = Path(repo_root).resolve()
    exempt = {root / rel for rel in EXEMPT_FILES}
    found: List[Path] = [
        root / name for name in SCOPE_ROOT_FILES if (root / name).is_file()
    ]
    docs_dir = root / docs_subdir
    if docs_dir.is_dir():
        found.extend(path for path in docs_dir.glob("*.md") if path.is_file())
        for name in SCOPE_DOC_DIRS:
            sub = docs_dir / name
            if not sub.is_dir():
                continue
            found.extend(path for path in sub.rglob("*.md") if path.is_file())
    return sorted(
        (path for path in found if path.resolve() not in exempt),
        key=lambda path: path.as_posix(),
    )


# ---------------------------------------------------------------- 文本处理


def read_text(path: Path) -> str:
    """按原样读取文件(不做换行归一化)。

    为什么不用 ``Path.read_text``:它默认把 CRLF 折成 LF,写回时就会把「只改数字」
    变成「整文件换行全改」—— diff 从此不可 review。与 ``docs_index._read_text`` 同一个理由。

    Args:
        path: 文件路径。

    Returns:
        文件内容,换行符与磁盘完全一致。
    """
    return path.read_bytes().decode("utf-8")


def write_text(path: Path, text: str) -> None:
    """按原样写文件(不做换行归一化)。

    Args:
        path: 文件路径。
        text: 要写入的内容,换行符原样落盘。
    """
    path.write_bytes(text.encode("utf-8"))


def same_value(raw: str, expected: str) -> bool:
    """判断哨兵里的值与事实是否相同(只抹掉首尾空白,不做别的归一化)。

    为什么**不做**「去掉全部空白」这种归一化:``25/25`` 与 ``25 / 25`` 在渲染上确实是
    同一个数,但只要允许多种形态并存,``--check`` 与 ``--write`` 就会对「谁才算规范」
    各说一套(实测踩过:判定放过 ``25/25``、渲染又把它改成 ``25 / 25``,于是每轮都报
    「判定与渲染不一致」)。规范形态只有一个,由 :data:`SENTINEL_TEMPLATE` 写出。

    Args:
        raw: 哨兵里的原始取值。
        expected: 事实的计算值。

    Returns:
        抹掉首尾空白后逐字符相同时返回 ``True``。
    """
    return raw.strip() == expected.strip()


def _mask_sentinels(line: str) -> str:
    """把一行里的哨兵整块换成占位符(不含数字),供 R2 扫描用。

    不这么做的话,哨兵自己携带的数字会被断言正则再命中一次 —— 变成「永远红」。

    Args:
        line: 一行原文(不含换行符)。

    Returns:
        哨兵被替换成 ``«num»`` 的行;没有哨兵时原样返回。
    """
    return SENTINEL_RE.sub("«num»", line)


def _line_flags(lines: Sequence[str]) -> List[Tuple[bool, bool]]:
    """逐行标记「在代码围栏内」与「是 ATX 标题」。

    Args:
        lines: 文件的所有行(不含换行符)。

    Returns:
        与 ``lines`` 等长的 ``(in_fence, is_heading)`` 列表。围栏行自身算「在围栏内」。
    """
    flags: List[Tuple[bool, bool]] = []
    in_fence = False
    for line in lines:
        if FENCE_RE.match(line):
            flags.append((True, False))
            in_fence = not in_fence
            continue
        flags.append((in_fence, bool(HEADING_RE.match(line))))
    return flags


def apply_fixes(text: str, values: Dict[str, str]) -> str:
    """算出「这份文档在机制下应有的样子」(刷新哨兵 + 包住裸数字)。

    只改两处:哨兵里的值、命中断言正则的裸数字。**标题行与代码围栏内的行整行不动** ——
    那两处是 R3 的判红对象,自动改只会制造新的违例(标题 anchor 被打碎)。

    Args:
        text: 文件全文(换行符原样)。
        values: ``{事实 id: 计算值}``。

    Returns:
        修好之后的全文;没有可改之处时与入参逐字节相同。
    """
    parts = text.splitlines(keepends=True)
    lines = [part.rstrip("\r\n") for part in parts]
    endings = [part[len(line) :] for part, line in zip(parts, lines)]

    # 第一遍:刷新已有哨兵的值(未知 id 原样留着,由 check 报「未知事实 id」)。
    refreshed: List[str] = []
    for line in lines:
        refreshed.append(
            SENTINEL_RE.sub(
                lambda match: (
                    SENTINEL_TEMPLATE.format(id=match.group(1), value=values[match.group(1)])
                    if match.group(1) in values
                    else match.group(0)
                ),
                line,
            )
        )

    # 第二遍:把裸数字包上哨兵。标题、围栏、带豁免标记的行整行不动。
    flags = _line_flags(lines)
    fixed: List[str] = []
    for index, line in enumerate(refreshed):
        in_fence, is_heading = flags[index]
        if in_fence or is_heading or NUMBER_ALLOW_MARKER in line:
            fixed.append(line)
            continue
        fixed.append(_wrap_bare_numbers(line, values))

    return "".join(line + ending for line, ending in zip(fixed, endings))


def _wrap_bare_numbers(line: str, values: Dict[str, str]) -> str:
    """把一行里命中断言正则的裸数字就地包上哨兵。

    做法是「先按哨兵切段,只在非哨兵段里替换」:哨兵自带数字,重复替换会套娃。
    每段内按事实顺序、模式顺序替换;偏移从右往左应用,避免前面的替换挪动后面的下标。

    Args:
        line: 一行原文(不含换行符)。
        values: ``{事实 id: 计算值}``。

    Returns:
        替换后的行;没有命中时与入参相同。
    """
    segments: List[str] = []
    cursor = 0
    for match in SENTINEL_RE.finditer(line):
        segments.append(line[cursor : match.start()])
        segments.append(match.group(0))
        cursor = match.end()
    segments.append(line[cursor:])

    for position in range(0, len(segments), 2):  # 偶数位 = 非哨兵段
        segments[position] = _replace_in_segment(segments[position], values)
    return "".join(segments)


def _replace_in_segment(segment: str, values: Dict[str, str]) -> str:
    """在一个非哨兵文本段里,把命中的裸数字替换成哨兵。

    Args:
        segment: 一段不含哨兵的文本。
        values: ``{事实 id: 计算值}``。

    Returns:
        替换后的文本。
    """
    for fact in FACTS:
        if fact.id not in values:
            continue
        for pattern in fact.patterns:
            spans: List[Tuple[int, int]] = [
                match.span(1) for match in pattern.finditer(segment)
            ]
            for start, stop in sorted(spans, reverse=True):
                segment = (
                    segment[:start]
                    + SENTINEL_TEMPLATE.format(id=fact.id, value=values[fact.id])
                    + segment[stop:]
                )
    return segment


# ---------------------------------------------------------------- 判定


def compute_values(repo_root: Path) -> Dict[str, str]:
    """算出全部事实的当前值。

    Args:
        repo_root: 仓库根目录。

    Returns:
        ``{事实 id: 值}``。

    Raises:
        Exception: 任一事实算不出来 —— 由 :func:`main` 映射成退出码 2(判不出来 ≠ 合规)。
    """
    return {fact.id: fact.compute(Path(repo_root)) for fact in FACTS}


def check_file(
    path: Path, repo_root: Path, values: Dict[str, str]
) -> Tuple[List[dict], str]:
    """判定一份文档,并返回它「应有的样子」。

    Args:
        path: 文档路径。
        repo_root: 仓库根目录(算仓库相对路径用)。
        values: :func:`compute_values` 的结果。

    Returns:
        ``(违例列表, 修好后的全文)``。违例项带 ``file`` / ``line`` / ``rule`` / ``message``。
    """
    text = read_text(path)
    rel = _display(path, repo_root)
    parts = text.splitlines(keepends=True)
    lines = [part.rstrip("\r\n") for part in parts]
    flags = _line_flags(lines)

    problems: List[dict] = []
    for index, line in enumerate(lines):
        lineno = index + 1
        for match in SENTINEL_RE.finditer(line):
            fact_id, raw = match.group(1), match.group(2)
            if fact_id not in values:
                problems.append(
                    _problem(rel, lineno, "sentinel-unknown", f"哨兵里的事实 id 不存在:{fact_id}")
                )
                continue
            if not same_value(raw, values[fact_id]):
                problems.append(
                    _problem(
                        rel,
                        lineno,
                        "sentinel-value",
                        f"「{FACTS_BY_ID[fact_id].summary}」的哨兵值 {raw.strip()!r} "
                        f"不等于事实 {values[fact_id]!r}",
                    )
                )
            in_fence, is_heading = flags[index]
            if is_heading:
                problems.append(
                    _problem(
                        rel,
                        lineno,
                        "sentinel-heading",
                        "标题里不许放哨兵(会打碎 anchor、目录链接全断):改用文字表述",
                    )
                )
            elif in_fence:
                problems.append(
                    _problem(
                        rel,
                        lineno,
                        "sentinel-fence",
                        "代码围栏里不许放哨兵:HTML 注释在 ``` 里会当字面量显示出来",
                    )
                )

        if flags[index][0] or flags[index][1] or NUMBER_ALLOW_MARKER in line:
            continue
        masked = _mask_sentinels(line)
        for fact in FACTS:
            if fact.id not in values:
                continue
            for pattern in fact.patterns:
                for match in pattern.finditer(masked):
                    problems.append(
                        _problem(
                            rel,
                            lineno,
                            "bare-number",
                            f"「{fact.summary}」写成了裸数字 {match.group(1).strip()!r}"
                            f"(事实是 {values[fact.id]!r}):包上哨兵,或改用文字表述",
                        )
                    )

    fixed = apply_fixes(text, values)
    if fixed != text and not problems:
        # 兜底:能力上不该发生(可改之处都会先报违例),发生了说明判定与渲染不一致。
        problems.append(
            _problem(rel, 0, "unstable", "判定与渲染结果不一致 —— 这是判定器的 bug")
        )
    return problems, fixed


def _problem(rel: str, lineno: int, rule: str, message: str) -> dict:
    """构造一条违例项。

    Args:
        rel: 文档的仓库相对路径。
        lineno: 行号(0 表示整文件级问题)。
        rule: 规则名(``sentinel-*`` / ``bare-number`` / ``unstable``)。
        message: 人读描述(带可执行的改法)。

    Returns:
        违例字典。
    """
    return {"file": rel, "line": lineno, "rule": rule, "message": message}


def check(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[dict]:
    """判全部作用域文档,返回扁平违例列表。

    Args:
        repo_root: 仓库根目录。
        docs_subdir: 相对 ``repo_root`` 的文档目录名。

    Returns:
        违例列表,按 ``(file, line, rule)`` 排序;空列表表示全部一致。

    Raises:
        FileNotFoundError: 文档目录不存在。
        Exception: 任一事实算不出来。
    """
    root = Path(repo_root).resolve()
    if not (root / docs_subdir).is_dir():
        raise FileNotFoundError(f"找不到文档目录:{root / docs_subdir}")
    values = compute_values(root)
    problems: List[dict] = []
    for path in scope_files(root, docs_subdir):
        file_problems, _fixed = check_file(path, root, values)
        problems.extend(file_problems)
    problems.sort(key=lambda item: (item["file"], item["line"], item["rule"]))
    return problems


def write_all(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[str]:
    """跑一遍修复并写盘(只在内容确实变化时落盘)。

    Args:
        repo_root: 仓库根目录。
        docs_subdir: 相对 ``repo_root`` 的文档目录名。

    Returns:
        实际改动的仓库相对路径列表。
    """
    root = Path(repo_root).resolve()
    values = compute_values(root)
    changed: List[str] = []
    for path in scope_files(root, docs_subdir):
        text = read_text(path)
        fixed = apply_fixes(text, values)
        if fixed == text:
            continue
        write_text(path, fixed)
        changed.append(_display(path, root))
    return changed


def report(repo_root: Path, docs_subdir: str = DOCS_SUBDIR) -> List[dict]:
    """统计每个事实的值与命中位置(人读 ``--report`` 用)。

    Args:
        repo_root: 仓库根目录。
        docs_subdir: 相对 ``repo_root`` 的文档目录名。

    Returns:
        每个事实一条 ``{"id", "summary", "value", "sentinels", "bare", "files"}``:
        ``sentinels`` 是已包哨兵的出现次数,``bare`` 是仍未包的出现次数,
        ``files`` 是涉及的文档数。
    """
    root = Path(repo_root).resolve()
    values = compute_values(root)
    stats = {
        fact.id: {
            "id": fact.id,
            "summary": fact.summary,
            "value": values[fact.id],
            "sentinels": 0,
            "bare": 0,
            "files": set(),
        }
        for fact in FACTS
    }
    for path in scope_files(root, docs_subdir):
        rel = _display(path, root)
        lines = [line for line in read_text(path).splitlines()]
        flags = _line_flags(lines)
        for index, line in enumerate(lines):
            for match in SENTINEL_RE.finditer(line):
                if match.group(1) in stats:
                    stats[match.group(1)]["sentinels"] += 1
                    stats[match.group(1)]["files"].add(rel)
            if flags[index][0] or flags[index][1] or NUMBER_ALLOW_MARKER in line:
                continue
            masked = _mask_sentinels(line)
            for fact in FACTS:
                for pattern in fact.patterns:
                    for _match in pattern.finditer(masked):
                        stats[fact.id]["bare"] += 1
                        stats[fact.id]["files"].add(rel)
    return [
        {**item, "files": len(item["files"])}
        for item in sorted(stats.values(), key=lambda item: item["id"])
    ]


def _display(path: Path, repo_root: Path) -> str:
    """把路径渲染成仓库相对的 POSIX 形式(报告与报错都用它)。

    Args:
        path: 目标路径。
        repo_root: 仓库根目录。

    Returns:
        ``docs/ops/x.md`` 形式;不在仓库内时原样返回。
    """
    try:
        return path.resolve().relative_to(Path(repo_root).resolve()).as_posix()
    except ValueError:
        return str(path)


# ---------------------------------------------------------------- 命令行


def render_human(problems: Iterable[dict]) -> str:
    """把违例列表渲染成人读的多行文本。

    Args:
        problems: :func:`check` 的返回值。

    Returns:
        每行一条,形如 ``docs/a.md:12 [bare-number] …``;空列表返回空串。
    """
    lines: List[str] = []
    for item in problems:
        where = item["file"] if not item.get("line") else f"{item['file']}:{item['line']}"
        lines.append(f"{where} [{item['rule']}] {item['message']}")
    return "\n".join(lines)


def render_report(rows: Sequence[dict]) -> str:
    """把 :func:`report` 的结果渲染成一张人读的表。

    Args:
        rows: :func:`report` 的返回值。

    Returns:
        多行文本(表头 + 每个事实一行)。
    """
    lines = [f"{'fact':<18}{'值':<12}{'哨兵':>4}{'裸写':>6}{'文件':>6}  说明"]
    for item in rows:
        lines.append(
            f"{item['id']:<18}{item['value']:<12}{item['sentinels']:>4}"
            f"{item['bare']:>6}{item['files']:>6}  {item['summary']}"
        )
    return "\n".join(lines)


def main(argv: List[str] | None = None) -> int:
    """命令行入口。

    Args:
        argv: 命令行参数列表;``None`` 表示用 ``sys.argv[1:]``。

    Returns:
        0 = 全部一致;1 = 有违例;2 = 判不出来。
    """
    parser = argparse.ArgumentParser(
        description="文档关键数字的机械化:计算 + 哨兵注入 + 判定(见 docs/superpowers/specs/2026-11-16-facts-numbers-design.md)"
    )
    parser.add_argument("--root", default=".", help="仓库根目录(默认当前目录)")
    parser.add_argument("--check", action="store_true", help="只判定(默认行为)")
    parser.add_argument("--write", action="store_true", help="刷新哨兵值并把裸数字包上哨兵")
    parser.add_argument("--report", action="store_true", help="打印每个事实的值与命中位置")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    if args.write and (args.check or args.report):
        print("facts: --write 不能与 --check / --report 同时用", file=sys.stderr)
        return 2

    root = Path(args.root)
    try:
        if args.write:
            changed = write_all(root)
            counts = compute_values(root)
        elif args.report:
            rows = report(root)
            counts = compute_values(root)
        else:
            problems = check(root)
            counts = compute_values(root)
    except (OSError, ValueError, run_gates.RegistryError) as exc:
        print(f"facts: 判定失败 —— {exc}", file=sys.stderr)
        return 2

    if args.write:
        if args.json:
            print(json.dumps({"ok": True, "changed": changed, "values": counts}, ensure_ascii=False))
        elif changed:
            for rel in changed:
                print(f"已更新:{rel}")
        else:
            print("facts: 全部哨兵已是最新,无需写入")
        return 0

    if args.report:
        if args.json:
            print(json.dumps({"values": counts, "rows": rows}, ensure_ascii=False))
        else:
            print(render_report(rows))
        return 0

    if args.json:
        print(json.dumps({"ok": not problems, "problems": problems, "values": counts}, ensure_ascii=False))
    elif problems:
        print(render_human(problems))
        print(f"\n共 {len(problems)} 处违例;修复:python scripts/facts.py --write", file=sys.stderr)
    else:
        print(f"facts: {len(FACTS)} 个事实全部一致 —— " + ", ".join(
            f"{fact_id}={value}" for fact_id, value in sorted(counts.items())
        ))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
