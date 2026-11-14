"""发版记录:``docs/releases.yml`` 是 owner,``release.md`` §5 是渲染物(C8 / D1-B)。

为什么不再用 Markdown 表格当数据库
----------------------------------
2026-11-14 之前,发版记录是 ``docs/ops/release.md`` §5 的一张 13 行 Markdown 表,门禁
``sync_version.py --check`` 靠 ``read_release_record`` 猜「表头同时含『版本』与『tag』」——
**改一次表格格式就可能误红**,而历史里还有 4 行是散文(``—`` / ``无(规则生效前发版)`` /
``历史遗留:…``),结构化解析与人的阅读体验被硬绑在一起。

现在反过来:``docs/releases.yml`` 是唯一事实来源(结构化、逐字段),``release.md`` §5 的
表格由本模块**渲染**进 ``<!-- BEGIN generated:release-records -->`` 区间,``--check`` 比对
渲染物与磁盘是否一致(逐字节;区间外的手写内容一字不动,换行风格跟随原文件 —— 与
``docs_index.py`` 的 ``generated:api-summary`` 同一套做法)。

YAML 的子集(刻意)
-----------------
仓库是**纯标准库**约束(不引 PyYAML),而这份文件是我们自己写的,所以只支持:

- 一个**扁平的记录列表**:每条以 ``- `` 开头,后续字段缩进两格;
- 值只有三种:双引号字符串(按 JSON 转义)、整数、``null``;
- ``#`` 开头的整行注释与空行忽略;
- 字段名必须在本模块 ``FIELDS`` 里(拼错即报错,不会静默丢一列)。

这足够表达「版本 / 日期 / tag / Release 链接 / 标题 / 附件名 / 附件字节 / SHA-1 / 上线 SHA /
备注」,也足够表达历史里的散文行(``release`` 留空 + ``note`` 写原文)。

错误处理口径
------------
``DocsError`` = **判不出来**(YAML 语法错、字段拼错、标记缺失):CLI 映射成退出码 2,
不是「合规」也不是「不一致」。记录缺失 / tag 不对 / Release 为空属于**判定失败**,由
:func:`check_current` 返回问题列表,调用方退出码 1。

文件信息:
    文件名称          scripts/lib/docs.py
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

import json
from pathlib import Path

from scripts.lib import REPO_ROOT

#: 发版记录的唯一事实来源(结构化数据)。
RELEASES_YML = REPO_ROOT / "docs" / "releases.yml"

#: 人读发版手册(§5 的表格由本模块渲染,其余手写)。
RELEASE_DOC = REPO_ROOT / "docs" / "ops" / "release.md"

#: 生成区间的起止标记。只覆盖两标记之间的内容,区间外一个字都不动。
BLOCK_BEGIN = "<!-- BEGIN generated:release-records -->"
BLOCK_END = "<!-- END generated:release-records -->"

#: 表格列(顺序即渲染顺序;``tag`` / ``Release`` / ``APK`` 的表头与旧表逐字一致)。
TABLE_HEADER = ("版本", "日期", "tag", "Release", "上线 SHA", "APK")

#: 允许的字段名。拼错即 ``DocsError`` —— 静默忽略会让「填了但没渲染」成为新的漂移。
FIELDS = (
    "version",      # 版本名,如 1.0.13
    "date",         # 发版日期 YYYY-MM-DD
    "tag",          # tag 名,如 v1.0.13;规则生效前为空
    "title",        # Release 标题,如 v1.0.13 — R–W 六批…
    "release",      # Release URL;散文行留空
    "note",         # Release 列的散文(历史遗留 / 规则生效前发版)
    "asset",        # 附件名,如 chatapp-1.0.13.apk
    "asset_bytes",  # 附件字节数(整数;未知写 0)
    "asset_sha1",   # 附件 SHA-1(未知留空)
    "deploy_sha",   # 上线 SHA(短 SHA 即可);未知留空
)

#: 每条记录必须出现的字段。
REQUIRED_FIELDS = ("version", "date")


class DocsError(RuntimeError):
    """发版记录判不出来(YAML 语法错 / 字段拼错 / 生成标记缺失)。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``raise DocsError(...)``

    备注信息:
        调用方应映射成退出码 2 —— 「判不出来」不等于「合规」。
    """


def parse_records(text: str, source: str = "docs/releases.yml") -> list[dict]:
    """解析 ``releases.yml`` 的文本(只支持模块 docstring 里写的那个 YAML 子集)。

    参数说明:
        text: 文件全文。
        source: 出错时用来定位的说明(通常是仓库相对路径)。

    返回参数:
        记录列表,顺序即文件顺序;每条是「字段名 → 值」的字典。

    使用示例:
        ``parse_records(text, source)``

    备注信息:
        抛 ``DocsError``:缩进不对、字段名不在 ``FIELDS`` 里、必需字段缺失、版本重复或值格式不合法。
    """
    records: list[dict] = []
    current: dict | None = None
    for lineno, raw in enumerate(text.splitlines(), start=1):
        line = raw.rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith("- "):
            current = {}
            records.append(current)
            _assign(current, line[2:], source, lineno)
            continue
        if line.startswith("  "):
            if current is None:
                raise DocsError(f"{source}:{lineno} 的字段出现在任何一条记录之前")
            _assign(current, line[2:], source, lineno)
            continue
        raise DocsError(f"{source}:{lineno} 既不是记录开头也不是缩进字段:{line!r}")

    if not records:
        raise DocsError(f"{source} 里一条记录都没有(文件被清空了?)")

    seen: set[str] = set()
    for index, record in enumerate(records, start=1):
        where = f"{source} 第 {index} 条记录"
        for field in REQUIRED_FIELDS:
            if not str(record.get(field) or "").strip():
                raise DocsError(f"{where} 缺必需字段 {field}")
        version = str(record["version"])
        if version in seen:
            raise DocsError(f"{where} 的版本重复:{version}")
        seen.add(version)
    return records


def load_records(path: Path = RELEASES_YML) -> list[dict]:
    """读取并解析发版记录文件。

    参数说明:
        path: ``releases.yml`` 路径;默认仓库里的那一份。

    返回参数:
        记录列表。

    使用示例:
        ``load_records(path)``

    备注信息:
        抛 ``DocsError``:文件不存在、读不出来或解析失败。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as error:
        raise DocsError(f"读不到发版记录 {path}:{error}") from error
    return parse_records(text, _display(path))


def find_record(version: str, records: list[dict]) -> dict | None:
    """在记录列表里找某个版本。

    参数说明:
        version: 版本名,如 ``1.0.13``。
        records: :func:`parse_records` / :func:`load_records` 的结果。

    返回参数:
        命中的记录;没有该版本时返回 ``None``。

    使用示例:
        ``find_record(version, records)``

    备注信息:
        无特殊约束。
    """
    return next((item for item in records if str(item.get("version")) == version), None)


def release_cell(record: dict) -> str:
    """渲染「Release」列:链接(+附件细节)或散文备注。

    参数说明:
        record: 一条发版记录。

    返回参数:
        可直接放进表格单元格的文本;三者都为空时返回 ``—``。

    使用示例:
        ``release_cell(record)``

    备注信息:
        历史行用 ``release`` 留空 + ``note`` 写散文(``无(规则生效前发版)`` /
        ``历史遗留:…``),渲染时原样还原 —— 迁移不改写历史(治理方案 §6)。
    """
    url = str(record.get("release") or "")
    note = str(record.get("note") or "")
    if not url:
        return note or "—"
    title = str(record.get("title") or "")
    cell = f"[{title}]({url})" if title else url
    asset = str(record.get("asset") or "")
    if asset:
        detail = f"`{asset}`"
        size = record.get("asset_bytes") or 0
        if size:
            detail += f",{int(size):,} 字节"
        sha1 = str(record.get("asset_sha1") or "")
        if sha1:
            detail += f",SHA-1 `{sha1}`"
        cell += f"(附件 {detail})"
    return cell


def render_row(record: dict) -> str:
    """渲染一条记录为 Markdown 表格行。

    参数说明:
        record: 一条发版记录。

    返回参数:
        形如 ``| 1.0.13 | 2026-11-11 | `v1.0.13` | … | `e7456f6` | `chatapp-1.0.13.apk` |``。

    使用示例:
        ``render_row(record)``

    备注信息:
        无特殊约束。
    """
    tag = f"`{record['tag']}`" if record.get("tag") else "—"
    deploy = f"`{record['deploy_sha']}`" if record.get("deploy_sha") else "—"
    asset = f"`{record['asset']}`" if record.get("asset") else "—"
    return (
        f"| {record['version']} | {record['date']} | {tag} | {release_cell(record)} "
        f"| {deploy} | {asset} |"
    )


def render_table(records: list[dict]) -> str:
    """渲染整张发版记录表(表头 + 分隔行 + 每条一行)。

    参数说明:
        records: 记录列表(顺序即渲染顺序,即文件顺序)。

    返回参数:
        Markdown 表格全文(以 ``\n`` 分隔,不含首尾换行)。**不含时间戳** —— 同一份 YAML 永远渲染出同一份字节,``--check`` 才有意义。

    使用示例:
        ``render_table(records)``

    备注信息:
        无特殊约束。
    """
    header = "| " + " | ".join(TABLE_HEADER) + " |"
    separator = "|" + "|".join("---" for _ in TABLE_HEADER) + "|"
    return "\n".join([header, separator, *(render_row(record) for record in records)])


def splice_block(text: str, body: str) -> str:
    """把渲染结果替换进 ``release.md`` 的生成区间,区间外一个字节都不动。

    参数说明:
        text: ``release.md`` 的当前全文。
        body: :func:`render_table` 的结果(以 ``\n`` 分隔)。

    返回参数:
        替换后的全文,换行风格跟随原文件(Windows 检出是 CRLF,不能整文件重写)。

    使用示例:
        ``splice_block(text, body)``

    备注信息:
        抛 ``DocsError``:两个标记缺一个或顺序颠倒。
    """
    newline = "\r\n" if "\r\n" in text else "\n"
    try:
        start = text.index(BLOCK_BEGIN) + len(BLOCK_BEGIN)
        stop = text.index(BLOCK_END, start)
    except ValueError as error:
        raise DocsError(
            f"release.md 里找不到成对的生成标记 {BLOCK_BEGIN} / {BLOCK_END}"
        ) from error
    return text[:start] + newline + body.replace("\n", newline) + newline + text[stop:]


def render_doc(repo_root: Path = REPO_ROOT) -> str:
    """渲染 ``release.md`` 的「期望全文」(只在当前内容上替换生成区间)。

    参数说明:
        repo_root: 仓库根目录。

    返回参数:
        期望全文;区间外与磁盘当前内容一致。

    使用示例:
        ``render_doc(repo_root)``

    备注信息:
        抛 ``DocsError``:记录文件或发版手册读不到、解析失败,或缺生成标记。
    """
    records = load_records(records_path(repo_root))
    doc_path = release_doc_path(repo_root)
    try:
        text = doc_path.read_text(encoding="utf-8")
    except OSError as error:
        raise DocsError(f"读不到发版手册 {doc_path}:{error}") from error
    return splice_block(text, render_table(records))


def check_current(version: str, path: Path = RELEASES_YML) -> list[str]:
    """校验发版记录已为指定版本留痕,且 tag / Release 两列可用。

    参数说明:
        version: 版本名,如 ``1.0.13``。
        path: ``releases.yml`` 路径;默认仓库里的那一份。

    返回参数:
        问题描述列表;空列表表示通过。

    使用示例:
        ``check_current(version, path)``

    备注信息:
        这是 ``sync_version.py --check`` 从第 5 节起读的东西 —— 语义与它读 Markdown 表格时
        **完全一致**(当前版本必须有行 / ``tag`` 含 ``v<版本>`` / ``Release`` 非空),只是数据
        来源换成了结构化文件。
        抛 ``DocsError``:记录文件不存在或解析失败(判不出来,不是「不一致」)。
    """
    if not path.exists():
        return [
            f"发版记录 {_display(path)} 不存在",
            "修复:恢复 docs/releases.yml(格式见文件头部注释)",
        ]
    record = find_record(version, load_records(path))
    if record is None:
        return [
            f"发版记录 {_display(path)} 里没有 {version} 这一条",
            "修复:在 docs/releases.yml 加一条(版本 / 日期 / tag / Release / 上线 SHA / APK),"
            "再跑 python scripts/releases.py --render",
        ]
    problems: list[str] = []
    tag = str(record.get("tag") or "")
    if f"v{version}" not in tag:
        problems.append(f"发版记录 {version} 的 tag 是 {tag or '(空)'},应写成 `v{version}`")
    release = release_cell(record)
    if release in ("", "—"):
        problems.append(
            f"发版记录 {version} 的 Release 为空 —— 建好后填链接;"
            "暂时建不了写「待建」并注明原因(例:本机无 gh/token)"
        )
    elif "待建" in release:
        # 2026-11-12 起「待建」不再算留痕:1.0.4 就是这么挂了整整一周还没建 Release。
        # 先加行、再发版是允许的(那时写「待建」),但**合并进默认分支之前**必须补成链接,
        # 否则门禁等于只校验了一句中文。
        problems.append(
            f"发版记录 {version} 的 Release 仍是「待建」—— 发版未完成;"
            "用 python scripts/create_release.py 建好 Release 后把链接填回来"
        )
    if problems:
        problems.append(
            f"修复:编辑 {_display(path)} 后再跑 python scripts/sync_version.py --check"
        )
    return problems


def check(repo_root: Path = REPO_ROOT) -> list[str]:
    """校验 ``release.md`` 的生成区间与 ``releases.yml`` 渲染结果一致。

    参数说明:
        repo_root: 仓库根目录。

    返回参数:
        问题描述列表;空列表表示一致。

    使用示例:
        ``check(repo_root)``

    备注信息:
        抛 ``DocsError``:记录文件 / 发版手册读不到、解析失败,或缺生成标记(判不出来)。
    """
    doc_path = release_doc_path(repo_root)
    if not doc_path.is_file():
        return [f"发版手册不存在:{_display(doc_path)}"]
    try:
        actual = doc_path.read_text(encoding="utf-8")
    except OSError as error:
        raise DocsError(f"读不到发版手册 {doc_path}:{error}") from error
    expected = render_doc(repo_root)
    if actual == expected:
        return []
    return [
        "发版记录区与 docs/releases.yml 不一致:"
        f"{_display(doc_path)} 的 §5 表格是**渲染物**,禁止手改",
        "修复:python scripts/releases.py --render",
    ]


def write(repo_root: Path = REPO_ROOT) -> bool:
    """把渲染结果写回 ``release.md``(只在内容确实变化时落盘)。

    参数说明:
        repo_root: 仓库根目录。

    返回参数:
        ``True`` 表示文件被改动。

    使用示例:
        ``write(repo_root)``

    备注信息:
        抛 ``DocsError``:同 :func:`render_doc`。
    """
    doc_path = release_doc_path(repo_root)
    expected = render_doc(repo_root)
    try:
        actual = doc_path.read_text(encoding="utf-8")
    except OSError:
        actual = None
    if actual == expected:
        return False
    # 按字节写:``Path.write_text`` 在 Windows 上会把 ``\n`` 翻成 CRLF,整文件换行就变了。
    doc_path.write_bytes(expected.encode("utf-8"))
    return True


def records_path(repo_root: Path) -> Path:
    """返回某个仓库根下的发版记录文件路径。

    参数说明:
        repo_root: 仓库根目录。

    返回参数:
        ``<root>/docs/releases.yml``。

    使用示例:
        ``records_path(repo_root)``

    备注信息:
        无特殊约束。
    """
    return Path(repo_root) / "docs" / "releases.yml"


def release_doc_path(repo_root: Path) -> Path:
    """返回某个仓库根下的发版手册路径。

    参数说明:
        repo_root: 仓库根目录。

    返回参数:
        ``<root>/docs/ops/release.md``。

    使用示例:
        ``release_doc_path(repo_root)``

    备注信息:
        无特殊约束。
    """
    return Path(repo_root) / "docs" / "ops" / "release.md"


def _assign(record: dict, pair: str, source: str, lineno: int) -> None:
    """解析一行 ``key: value`` 并写进记录。

    参数说明:
        record: 目标记录(原地修改)。
        pair: 冒号之后的原始文本之前的部分,即 ``key: value``。
        source: 出错时的定位说明。
        lineno: 行号。

    返回参数:
        无返回值。

    使用示例:
        ``_assign(record, pair, source, lineno)``

    备注信息:
        抛 ``DocsError``:缺冒号、字段名不在 ``FIELDS`` 里、字段重复,或值的格式不合法。
    """
    key, separator, value = pair.partition(":")
    key = key.strip()
    if not separator or not key:
        raise DocsError(f"{source}:{lineno} 不是 key: value 形式:{pair!r}")
    if key not in FIELDS:
        raise DocsError(f"{source}:{lineno} 的字段名 {key!r} 不在允许集合里:{', '.join(FIELDS)}")
    if key in record:
        raise DocsError(f"{source}:{lineno} 的字段 {key} 重复")
    record[key] = _value(value.strip(), source, lineno)


def _value(raw: str, source: str, lineno: int) -> str | int | None:
    """把 YAML 子集里的一个值转成 Python 值。

    参数说明:
        raw: 冒号之后、去掉首尾空白的文本。
        source: 出错时的定位说明。
        lineno: 行号。

    返回参数:
        字符串(双引号按 JSON 转义解析)、整数,或 ``None``(``null`` / ``~``)。

    使用示例:
        ``_value(raw, source, lineno)``

    备注信息:
        抛 ``DocsError``:双引号不配对 / 转义不合法。
    """
    if raw in ("", '""'):
        return ""
    if raw in ("null", "~"):
        return None
    if raw.startswith('"'):
        try:
            return json.loads(raw)
        except ValueError as error:
            raise DocsError(f"{source}:{lineno} 的字符串值不合法:{raw!r}({error})") from error
    if raw.lstrip("-").isdigit():
        return int(raw)
    return raw


def _display(path: Path) -> str:
    """把路径转成相对仓库根的展示形式(不在仓库内时原样返回)。

    参数说明:
        path: 文件路径。

    返回参数:
        便于阅读的路径字符串。

    使用示例:
        ``_display(path)``

    备注信息:
        无特殊约束。
    """
    try:
        return str(Path(path).relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path)
