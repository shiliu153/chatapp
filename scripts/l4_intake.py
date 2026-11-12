#!/usr/bin/env python3
"""L4「需求自动入队」的确定性判定器:把**机器可判**的信号变成规范化工单。

它替掉的是「人写 issue」这个闸门,**不替人做任何产品判断**。所以本文件里没有一处
「要不要做」的逻辑,只有三类信号的机器判据:

| 信号 | 事实来源 | 是(开单)的判据 |
|---|---|---|
| `ci-red` | 默认分支上每条 workflow 的最新 push run | 结论是 `failure`,且该 workflow 映射到**单一条栈**、该栈在 `scripts/verify.sh` 里有子命令 |
| `dep-advisory` | `npm audit --json` + 仓库锁文件 | 公告命中、severity ≥ 阈值、**有** first_patched_version、**锁文件里实际装的版本仍落在受影响区间内** |
| `mech-docs-links` | `scripts/check_docs_links.py` | `docs/` 里存在指向不存在路径的相对链接 |

设计文档:`docs/superpowers/specs/2026-11-08-superagent-automation-ladder-design.md` §6。
运维口径:`docs/ops/superagent.md` §14。开关是仓库 variable `L4_INTAKE`(不是 `eval.mode`)。

三条硬规矩(全部有对应自测)
--------------------------
1. **fail-closed**:判不出来(字段缺失 / 区间解析不了 / 锁文件里找不到该包 / API 形状不对)
   → **不开单**,并把整轮 run 标红。漏开单只是少一件事,误开单会污染待办。
2. **去重**:每张单带稳定指纹(`<!-- l4-fingerprint: … -->`)。同一失败重复出现只**追加评论**
   (已关闭过就 reopen),绝不每天新开一条。指纹里**不含 SHA / 时间**,否则天天都是新单。
3. **绝不 @ 任何人**:superagent 把 issue 的 opening body 当作派工触发源(见
   `docs/ops/superagent.md` §4.1),L4 生成的标题/正文里出现 `@xxx` 等于**绕过人工派单**
   —— 见 `_scrub_mentions`,并且有自测钉住。

用法
----
    # 依赖信号的事实源是 `npm audit --json`(私有仓库上 GITHUB_TOKEN 读 dependabot
    # 告警接口是 403,实测),先规整成与告警同形状的记录:
    (cd web && npm audit --json > ../.l4/npm-audit.json)    # 退出码非 0 是正常的
    python scripts/l4_intake.py from-npm-audit --input .l4/npm-audit.json --out .l4/alerts.json

    # 判定(纯函数,离线;输入是 gh api 的 JSON 快照)
    python scripts/l4_intake.py plan --runs runs.json --alerts alerts.json \
        --existing issues.json --root . --json-out plan.json --summary-out summary.md

    # 执行(plan → gh 命令);--dry-run 只打印
    python scripts/l4_intake.py apply --plan plan.json --repo shiliu153/chatapp --dry-run

    # 复用:main-health.yml 的红轨列表由同一个解析器产出(不复制扫描逻辑)
    python scripts/l4_intake.py ci-red-summary --runs runs.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# `python scripts/l4_intake.py` 时 sys.path[0] 是 scripts/,所以要显式把仓库根放进去,
# 这样 `from scripts import check_docs_links` 两种调用方式(直接跑 / unittest)都成立。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts import check_docs_links  # noqa: E402  (必须在 sys.path 修好之后)

# ── 信号名与标签

SIG_CI_RED = "ci-red"
SIG_DEP = "dep-advisory"
SIG_DOCS_LINKS = "mech-docs-links"
DETECTORS = (SIG_CI_RED, SIG_DEP, SIG_DOCS_LINKS)

LABEL_AUTO = "l4-auto"
LABEL_PREFIX = "l4-sig:"

# ── 白名单:workflow 显示名 → (栈路径, verify.sh 子命令, scope 词)
#
# **入白名单的唯一判据**:该栈在 `scripts/verify.sh` 里有对应子命令 —— 也就是 worker 能
# 在工单目录里**自己复现并自证**这个失败。做不到自证的一律留给人(见 HUMAN_ONLY)。
CI_RED_STACKS: Dict[str, Tuple[str, str, str]] = {
    "Backend (Django)": ("chatapp/", "backend", "backend"),
    "Web (Vue)": ("web/", "web", "web"),
    "imserver": ("imserver/", "imserver", "imserver"),
    "App (Flutter)": ("app/", "app", "app"),
}

# 明确不开单的 workflow,以及**为什么**。写在这里是为了让人一眼看出「漏掉的」不是忘了。
CI_RED_HUMAN_ONLY: Dict[str, str] = {
    "跨栈契约": "失败横跨 app/ web/ chatapp/ scripts/ 四栈,且最常见原因是版本号不一致 —— "
    "升版本号按 AGENTS.md 属「绝对不要做」,必须人做",
    "App UI (emulator smoke)": "模拟器轨只能在 CI 上跑,worker 无法在工单目录里自证"
    "(scripts/verify.sh 没有对应子命令)",
    "Web E2E (smoke)": "端到端冒烟要真 MySQL+Redis+Django+preview,verify.sh 无对应子命令,"
    "失败多为环境/时序",
    "自动合并（白名单）": "流程轨自身,修法属流程改动(人)",
    "默认分支健康": "流程轨自身,修法属流程改动(人)",
    "L4 需求自动入队": "本 workflow 自身 —— 排除自环,也避免「判定器坏了就给自己开一张单」",
}

# Dependabot 告警:生态 → 能不能开单。docker / github-actions 的修复动的是 deploy/ 与
# .github/(worker 不可写或必须人审),所以只记录不开单。
#
# 2026-11-12 收窄到只认 npm:私有仓库上 `GITHUB_TOKEN` 读 `/dependabot/alerts` 是
# **403 Resource not accessible by integration**(实测,见 ops §14.4),而 `npm audit`
# 同一套公告库、直接读锁文件,任何 token 都能跑。pip 侧没有等价的本地扫描器,
# 所以 pip 明确留给人(不再假装覆盖)。
DEP_ECOSYSTEMS = {"npm": "web"}

# 锁文件位置(相对仓库根)。生态 → 锁文件 + 解析方式。
NPM_LOCK = "web/package-lock.json"
PIP_LOCK = "chatapp/requirements.lock"

# 严重度排序;低于阈值不开单(仍由 Dependabot 自己的告警/PR 兜着)。
SEVERITY_ORDER = {"low": 0, "medium": 1, "moderate": 1, "high": 2, "critical": 3}

FINGERPRINT_RE = re.compile(r"<!--\s*l4-fingerprint:\s*([0-9a-f]{16})\s*-->")
_VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?$")
_COMPARATOR_RE = re.compile(r"^(>=|<=|>|<|=|\^|~)?\s*v?(\d+(?:\.\d+){0,2})$")


# ── 数据结构


@dataclass
class Decision:
    """一条判定结果:要么开单 / 评论 / 重开,要么跳过并写明原因。

    Attributes:
        action: `create` / `comment` / `reopen` / `skip` / `defer`。
        detector: 触发的信号名(见 `DETECTORS`)。
        fingerprint: 稳定指纹(16 位十六进制),去重就靠它。
        reason: `skip` / `defer` / `comment` / `reopen` 的原因(也是 job summary 里的说明)。
        title: 工单标题(`create` 用)。
        body: 工单正文(`create` 用)。
        labels: 要打的标签(`create` 用)。
        issue: 要评论 / 重开的已有 issue 编号。
    """

    action: str
    detector: str
    fingerprint: str
    reason: str = ""
    title: str = ""
    body: str = ""
    labels: List[str] = field(default_factory=list)
    issue: Optional[int] = None


# ── 小工具


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 8601 字符串(秒级,带 Z)。

    Returns:
        形如 `2026-11-13T01:20:00Z` 的字符串。
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fingerprint(identity: str) -> str:
    """把「同一失败的身份串」压成稳定指纹。

    身份串里**不许**出现时间戳或 SHA —— 否则同一失败每天都会算出新指纹,去重就失效了。

    Args:
        identity: 身份串,如 `ci-red|Backend (Django)`。

    Returns:
        16 位十六进制指纹(sha256 前 16 位)。
    """
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]


def _scrub_mentions(text: str) -> str:
    """去掉正文里的 `@提及`,防止开单被 superagent 当成派工。

    Args:
        text: 任意文本(通常是要写进 issue 的标题或正文)。

    Returns:
        所有 `@handle` 里的 `@` 已被去掉的文本。
    """
    return re.sub(r"@([A-Za-z0-9][A-Za-z0-9\-]*)", r"\1", text)


def _load_json(path: str) -> Any:
    """读一个 JSON 文件;`-` 表示从 stdin 读。

    Args:
        path: 文件路径或 `-`。

    Returns:
        解析后的 JSON 值。

    Raises:
        OSError: 文件读不了。
        json.JSONDecodeError: 内容不是合法 JSON(调用方负责 fail-closed)。
    """
    if path == "-":
        return json.load(sys.stdin)
    return json.loads(Path(path).read_text(encoding="utf-8"))


# ── 版本区间判定(依赖信号的核心:不看告警的 state,看锁文件里到底装的什么)


def parse_version(text: str) -> Optional[Tuple[int, int, int]]:
    """把版本号解析成三元组,忽略预发布 / 构建元数据。

    Args:
        text: 版本号,如 `11.0.8` / `v1.16.3` / `8.3.8-beta.1`。

    Returns:
        `(major, minor, patch)`;解析不了返回 `None`(调用方按 fail-closed 处理)。
    """
    match = _VERSION_RE.match(text.strip())
    if not match:
        return None
    return tuple(int(part or 0) for part in match.groups())  # type: ignore[return-value]


def _match_comparator(version: Tuple[int, int, int], comparator: str) -> Optional[bool]:
    """判定单个比较式(如 `>= 7.0.0` / `^8.3.0`)是否成立。

    Args:
        version: 已解析的版本三元组。
        comparator: 单个比较式(不含逗号)。

    Returns:
        `True` / `False`;无法解析时返回 `None`。
    """
    text = comparator.strip()
    if not text or text == "*":
        return True
    match = _COMPARATOR_RE.match(text)
    if not match:
        return None
    op = match.group(1) or "="
    bound = parse_version(match.group(2))
    if bound is None:
        return None

    if op == ">=":
        return version >= bound
    if op == "<=":
        return version <= bound
    if op == ">":
        return version > bound
    if op == "<":
        return version < bound
    if op == "=":
        return version == bound
    if op == "^":
        if bound[0] > 0:
            upper = (bound[0] + 1, 0, 0)
        elif bound[1] > 0:
            upper = (0, bound[1] + 1, 0)
        else:
            upper = (0, 0, bound[2] + 1)
        return bound <= version < upper
    if op == "~":
        return bound <= version < (bound[0], bound[1] + 1, 0)
    return None


def _normalize_spec(spec: str) -> str:
    """把两种常见的区间写法归一化,再交给比较器。

    GitHub 公告用逗号分隔(`>= 7.0.0, < 7.30.1`),**npm 用空格分隔**
    (`>=8.3.0 <=8.3.2`)。旧版只按逗号切,于是 npm 的写法会整串被当成一个比较式而
    判不出来 —— 换成 npm audit 之后这是**主路径**,必须归一化。

    Args:
        spec: 原始区间表达式。

    Returns:
        去掉了「操作符与版本号之间空格」的表达式;分组仍保留逗号与空格作为分隔符。
    """
    return re.sub(r"([<>=^~]+)\s+", r"\1", spec.strip())


def version_in_range(version: str, spec: str) -> Optional[bool]:
    """判定某个版本是否落在 npm / pip 风格的受影响区间里。

    支持 `||`、逗号**或空格**表示「且」、以及 `>= <= > < = ^ ~` 与裸版本(等价于 `=`)。

    Args:
        version: 待判定的版本号(锁文件里实际装的那个)。
        spec: 区间表达式,如 `>= 7.0.0, < 7.30.1` 或 `>=8.3.0 <=8.3.2`。

    Returns:
        `True`(在区间内)/ `False`(不在)/ `None`(判不出来 —— 调用方必须按不开单处理)。
    """
    parsed = parse_version(version)
    if parsed is None or not spec or not spec.strip():
        return None
    unknown = False
    for group in _normalize_spec(spec).split("||"):
        parts = [part for part in re.split(r"[,\s]+", group.strip()) if part]
        if not parts:
            continue
        results = [_match_comparator(parsed, part) for part in parts]
        if any(result is False for result in results):
            continue
        if any(result is None for result in results):
            unknown = True
            continue
        return True
    return None if unknown else False


def _normalize_pip_name(name: str) -> str:
    """按 PEP 503 归一化 Python 包名(`-` / `_` / `.` 等价,大小写不敏感)。

    Args:
        name: 原始包名。

    Returns:
        归一化后的包名。
    """
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def locked_version(repo_root: Path, ecosystem: str, package: str) -> Optional[str]:
    """从仓库的锁文件里读出该包**实际会被装上**的版本。

    这是依赖信号的关键:GitHub 的告警 state 会滞后于仓库(实测:2026-11-12 修复后仍有
    13 条 `open` 告警),只信 state 会为**已经修好的漏洞**开单。

    Args:
        repo_root: 仓库根目录。
        ecosystem: `npm` 或 `pip`。
        package: 包名。

    Returns:
        锁文件里的版本号;找不到 / 锁文件缺失 / 同包多版本判不了时返回 `None`。
    """
    if ecosystem == "npm":
        lock = repo_root / NPM_LOCK
        if not lock.is_file():
            return None
        data = json.loads(lock.read_text(encoding="utf-8"))
        packages = data.get("packages") or {}
        exact = packages.get(f"node_modules/{package}")
        if exact and exact.get("version"):
            return exact["version"]
        # 嵌套安装(`node_modules/a/node_modules/b`)只接受唯一命中的情况。
        nested = [
            info.get("version")
            for key, info in packages.items()
            if key.endswith(f"node_modules/{package}") and info.get("version")
        ]
        unique = sorted(set(nested))
        return unique[0] if len(unique) == 1 else None

    if ecosystem == "pip":
        lock = repo_root / PIP_LOCK
        if not lock.is_file():
            return None
        wanted = _normalize_pip_name(package)
        for line in lock.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "==" not in line:
                continue
            name, version = line.split("==", 1)
            if _normalize_pip_name(name) == wanted:
                return version.strip()
        return None

    return None


# ── 事实提取:ci-red


def latest_runs_by_workflow(runs: Any) -> List[dict]:
    """取出「每条 workflow 的最新一次 run」(与 `main-health.yml` 同口径)。

    Args:
        runs: `gh api .../actions/runs` 的响应(需含 `workflow_runs`),或直接是列表。

    Returns:
        每项是一个 run 字典,按创建时间倒序。空列表表示没有任何 run。

    Raises:
        ValueError: 形状不对(调用方 fail-closed)。
    """
    if isinstance(runs, dict):
        items = runs.get("workflow_runs")
    else:
        items = runs
    if not isinstance(items, list):
        raise ValueError("runs 响应里没有 workflow_runs 列表")

    ordered = sorted(
        (run for run in items if isinstance(run, dict)),
        key=lambda run: str(run.get("created_at") or ""),
        reverse=True,
    )
    seen: set = set()
    latest: List[dict] = []
    for run in ordered:
        name = run.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        latest.append(run)
    return latest


def red_runs(runs: Any) -> List[dict]:
    """从 runs 快照里挑出「最新一次 push run 是红的」那些 workflow。

    Args:
        runs: `gh api .../actions/runs` 的响应。

    Returns:
        失败 run 的字典列表,按 workflow 名字典序。

    Raises:
        ValueError: 形状不对。
    """
    failed = [run for run in latest_runs_by_workflow(runs) if run.get("conclusion") == "failure"]
    return sorted(failed, key=lambda run: str(run.get("name")))


def render_ci_red_summary(runs: Any) -> str:
    """把红轨渲染成 Markdown 列表(`main-health.yml` 的 issue 正文原样用这一份)。

    Args:
        runs: `gh api .../actions/runs` 的响应。

    Returns:
        Markdown 文本;没有红轨时返回空串。
    """
    items = [
        f"- `{run.get('name')}` @ {str(run.get('head_sha') or '')[:7]} — {run.get('html_url')}"
        for run in red_runs(runs)
    ]
    return "\n".join(items)


# ── 事实提取:依赖告警


def _alert_severity(alert: dict) -> str:
    """取告警的严重度(小写)。

    Args:
        alert: Dependabot 告警字典。

    Returns:
        严重度字符串;缺失时返回空串。
    """
    advisory = alert.get("security_advisory") or {}
    return str(advisory.get("severity") or "").lower()


def _alert_stack(alert: dict) -> Optional[Tuple[str, str, str]]:
    """把一条告警映射到「单一条栈」,映射不了返回 `None`。

    Args:
        alert: Dependabot 告警字典。

    Returns:
        `(栈路径, verify.sh 子命令, scope 词)`;生态或 manifest 不在白名单时返回 `None`。
    """
    dependency = alert.get("dependency") or {}
    package = dependency.get("package") or {}
    ecosystem = str(package.get("ecosystem") or "")
    manifest = str(dependency.get("manifest_path") or "")
    if ecosystem not in DEP_ECOSYSTEMS:
        return None
    if manifest.startswith("web/"):
        return ("web/", "web", "web")
    if manifest.startswith("chatapp/"):
        return ("chatapp/", "backend", "backend")
    return None


GHSA_RE = re.compile(r"(GHSA-[0-9a-z]{4}-[0-9a-z]{4}-[0-9a-z]{4})", re.IGNORECASE)


def normalize_npm_audit(report: Any, manifest: str = "web/package.json") -> List[dict]:
    """把 `npm audit --json` 的输出规整成判定器认识的「告警记录」。

    为什么要转换而不是直接判:`npm audit` 是**在任何 token 下都能跑**的事实源
    (Dependabot 告警接口在私有仓库上对 `GITHUB_TOKEN` 返回 403,实测),
    而它的输出形状与 GitHub 告警 API 不同。转换之后,严重度阈值、锁文件比对、
    指纹去重这些口径与「告警」那条路径完全共用,不必各写一份。

    一个包可能命中多条公告(`via` 里每个对象一条),**按公告拆开**——指纹
    `dep|npm|<包>|<GHSA>` 因此天然区分得开。

    Args:
        report: `npm audit --json` 解析后的字典。
        manifest: 写进记录的清单路径,用于映射到栈。

    Returns:
        告警记录列表。`via` 里的字符串项(传递依赖、没有公告号)被跳过:
        没有公告号就做不出稳定指纹,也就无法去重 ⇒ 不开单。
    """
    vulnerabilities = (report or {}).get("vulnerabilities") or {}
    if not isinstance(vulnerabilities, dict):
        return []

    records: List[dict] = []
    for name in sorted(vulnerabilities):
        entry = vulnerabilities[name]
        if not isinstance(entry, dict):
            continue
        fix = entry.get("fixAvailable")
        patched = str(fix.get("version") or "") if isinstance(fix, dict) else ""
        for via in entry.get("via") or []:
            if not isinstance(via, dict):
                continue
            url = str(via.get("url") or "")
            match = GHSA_RE.search(url)
            if not match:
                continue
            records.append(
                {
                    "state": "open",
                    "dismissed_at": None,
                    "html_url": url,
                    "dependency": {
                        "package": {"name": name, "ecosystem": "npm"},
                        "manifest_path": manifest,
                    },
                    "security_advisory": {
                        "ghsa_id": match.group(1).upper(),
                        "severity": str(
                            via.get("severity") or entry.get("severity") or ""
                        ).lower(),
                        "summary": str(via.get("title") or ""),
                    },
                    "security_vulnerability": {
                        "vulnerable_version_range": str(
                            via.get("range") or entry.get("range") or ""
                        ),
                        "first_patched_version": (
                            {"identifier": patched} if patched else None
                        ),
                    },
                }
            )
    return records


# ── 工单正文渲染


def _envelope(
    detector: str,
    identity: str,
    fp: str,
    judged_at: str,
    facts: Sequence[Tuple[str, str]],
    what: str,
    acceptance: List[str],
    stack: str,
    allowed: str,
    forbidden: str,
) -> str:
    """渲染工单正文的统一骨架:指纹 / 事实 / 改什么 / 验收 / 栈 / 边界。

    Args:
        detector: 信号名。
        identity: 人的可读身份串(如 workflow 名)。
        fp: 稳定指纹。
        judged_at: 判定时间(UTC ISO)。
        facts: 「项 → 值」的事实表,全部由机器从 API / 文件里取。
        what: 「改什么」的说明。
        acceptance: 验收命令列表。
        stack: 唯一允许改动的栈路径。
        allowed: 允许的动作(一句话)。
        forbidden: 禁止的动作(一句话)。

    Returns:
        完整的 Markdown 正文(已过 `_scrub_mentions`)。
    """
    table = "\n".join(f"| {key} | {value} |" for key, value in facts)
    commands = "\n".join(acceptance)
    body = f"""<!-- l4-fingerprint: {fp} -->
<!-- l4: detector={detector} · subject={identity} · judged-at={judged_at} -->

> 本单由 `.github/workflows/l4-intake.yml` 按**白名单信号**自动创建(标签 `{LABEL_AUTO}`)。
> 正文里的事实全部来自命令输出,不含「要不要做」的判断;**派单仍由人执行**。

## 改什么

{what}

## 事实(机器生成,勿手改)

| 项 | 值 |
|---|---|
{table}

## 验收

```bash
{commands}
```

## 栈

`{stack}` —— 只准改这一条栈。需要跨栈就在评论里说明并**关单**,由人拆单。

## 边界

- 允许:{allowed}
- 禁止:{forbidden}
- 根因不在本栈时:关单 + 评论写明理由,**不要**跨栈顺手改。
"""
    return _scrub_mentions(body)


def _ci_red_ticket(run: dict, stack: Tuple[str, str, str], judged_at: str) -> Decision:
    """把一条红轨事实转成开单判定。

    Args:
        run: 失败 run 的字典。
        stack: `(栈路径, verify.sh 子命令, scope 词)`。
        judged_at: 判定时间(UTC ISO)。

    Returns:
        `create` 判定。
    """
    path, command, scope = stack
    name = str(run.get("name"))
    fp = fingerprint(f"ci-red|{name}")
    sha = str(run.get("head_sha") or "")
    facts = [
        ("workflow", f"`{name}`"),
        ("最新 push run", f"[#{run.get('id')}]({run.get('html_url')})"),
        ("结论", f"`{run.get('conclusion')}`"),
        ("提交", f"`{sha[:7]}`"),
        ("触发时间", f"`{run.get('created_at')}`"),
        ("判定时间", f"`{judged_at}`"),
    ]
    body = _envelope(
        detector=SIG_CI_RED,
        identity=name,
        fp=fp,
        judged_at=judged_at,
        facts=facts,
        what=f"让默认分支上 `{name}` 的最新一次 push run 重新变绿。"
        f"先按失败日志定位(上面的 run 链接),改动只落在 `{path}`。",
        acceptance=[
            "# 在工单目录里跑(必须绿):",
            f"scripts/verify.sh {command}",
        ],
        stack=path,
        allowed=f"只改 `{path}` 下的文件,修掉该 run 的失败原因",
        forbidden="改 `.github/workflows/`(门禁本身)、升版本号、跨栈改动",
    )
    return Decision(
        action="create",
        detector=SIG_CI_RED,
        fingerprint=fp,
        title=_scrub_mentions(f"fix({scope}): 默认分支「{name}」轨最新 push run 变红"),
        body=body,
        labels=[LABEL_AUTO, f"{LABEL_PREFIX}{SIG_CI_RED}"],
    )


def _dep_ticket(
    alert: dict,
    stack: Tuple[str, str, str],
    current: str,
    judged_at: str,
) -> Decision:
    """把一条仍成立的依赖告警转成开单判定。

    Args:
        alert: Dependabot 告警字典。
        stack: `(栈路径, verify.sh 子命令, scope 词)`。
        current: 锁文件里实际装的版本。
        judged_at: 判定时间(UTC ISO)。

    Returns:
        `create` 判定。
    """
    path, command, scope = stack
    dependency = alert.get("dependency") or {}
    package = dependency.get("package") or {}
    vuln = alert.get("security_vulnerability") or {}
    advisory = alert.get("security_advisory") or {}
    name = str(package.get("name"))
    ecosystem = str(package.get("ecosystem"))
    ghsa = str(advisory.get("ghsa_id") or "")
    patched = str((vuln.get("first_patched_version") or {}).get("identifier") or "")
    fp = fingerprint(f"dep|{ecosystem}|{name}|{ghsa}")

    facts = [
        ("包", f"`{name}`({ecosystem})"),
        ("清单", f"`{dependency.get('manifest_path')}`"),
        ("锁定版本", f"`{current}`"),
        ("受影响区间", f"`{vuln.get('vulnerable_version_range')}`"),
        ("首个修复版本", f"`{patched}`"),
        ("严重度", f"`{_alert_severity(alert)}`"),
        ("公告", f"[{ghsa}]({alert.get('html_url') or ''})"),
        ("摘要", _scrub_mentions(str(advisory.get("summary") or ""))),
        ("判定时间", f"`{judged_at}`"),
    ]
    if ecosystem == "npm":
        what = (
            f"把 `{name}` 从 `{current}` 升到 `{patched}` 或更高。"
            "如果是传递依赖,用 `overrides` 正向钉死(**不要**接受依赖降级 —— "
            "见 `docs/backlog/2026-11-03-todo.md` §7.1 的裁决口径),然后重生成 `package-lock.json`。"
        )
        acceptance = [
            "cd web && npm ci",
            f"cd web && npm audit --audit-level=high   # 该公告必须消失",
            "scripts/verify.sh web",
        ]
    else:
        what = (
            f"把 `{name}` 从 `{current}` 升到 `{patched}` 或更高:"
            "改 `chatapp/requirements.txt` 的区间 → 在干净 venv 里 `pip install -r` → "
            "按现有流程重生成 `chatapp/requirements.lock`。"
        )
        acceptance = [
            "grep -i '^" + name + "==' chatapp/requirements.lock   # 版本必须 >= " + patched,
            "scripts/verify.sh backend",
        ]
    body = _envelope(
        detector=SIG_DEP,
        identity=f"{ecosystem}/{name} {ghsa}",
        fp=fp,
        judged_at=judged_at,
        facts=facts,
        what=what,
        acceptance=acceptance,
        stack=path,
        allowed=f"只改 `{path}` 下的依赖清单 / 锁文件",
        forbidden="接受顶层依赖的降级;改业务代码;更新无关依赖",
    )
    return Decision(
        action="create",
        detector=SIG_DEP,
        fingerprint=fp,
        title=_scrub_mentions(f"fix({scope}): {name} 存在{_alert_severity(alert)}漏洞({ghsa})"),
        body=body,
        labels=[LABEL_AUTO, f"{LABEL_PREFIX}{SIG_DEP}"],
    )


def _docs_ticket(file: str, items: List[dict], judged_at: str) -> Decision:
    """把一个文件的全部断链聚合成一张单。

    Args:
        file: 出现断链的 Markdown 文件(仓库相对路径)。
        items: 该文件的断链条目(每项含 line / target / resolved / suggestion)。
        judged_at: 判定时间(UTC ISO)。

    Returns:
        `create` 判定。
    """
    fp = fingerprint(f"mech|docs-links|{file}")
    rows = []
    for item in items:
        fix = f"改指向 `{item['suggestion']}`" if item.get("suggestion") else "改指向或删除该链接"
        rows.append(f"- 第 {item['line']} 行:`{item['target']}` → 解析为 `{item['resolved']}`;{fix}")
    facts = [
        ("文件", f"`{file}`"),
        ("断链处数", str(len(items))),
        ("判定时间", f"`{judged_at}`"),
    ]
    body = _envelope(
        detector=SIG_DOCS_LINKS,
        identity=file,
        fp=fp,
        judged_at=judged_at,
        facts=facts,
        what="修掉下面这些相对链接(每行都给了机器解析出的目标与候选):\n\n" + "\n".join(rows),
        acceptance=[
            "python scripts/check_docs_links.py   # 退出码必须是 0",
        ],
        stack="docs/",
        allowed="改链接指向已存在的文件,或删掉指向不存在内容的链接",
        forbidden="为满足链接**新建文档**(那等于替人决定写什么);改 docs/ 以外的任何文件",
    )
    return Decision(
        action="create",
        detector=SIG_DOCS_LINKS,
        fingerprint=fp,
        title=_scrub_mentions(f"docs(docs): 修复 {file} 的 {len(items)} 处断链"),
        body=body,
        labels=[LABEL_AUTO, f"{LABEL_PREFIX}{SIG_DOCS_LINKS}"],
    )


# ── 三个判定器


def decide_ci_red(runs: Any, judged_at: str) -> Tuple[List[Decision], List[str]]:
    """ci-red 信号:白名单内的红轨 → 开单;其余 → 记原因跳过。

    Args:
        runs: `gh api .../actions/runs` 的响应。
        judged_at: 判定时间(UTC ISO)。

    Returns:
        `(判定列表, 判不出来的原因列表)`。原因列表非空表示这轮**不可信**。
    """
    decisions: List[Decision] = []
    undecidable: List[str] = []
    try:
        failed = red_runs(runs)
    except ValueError as exc:
        return [], [f"ci-red: {exc}"]

    for run in failed:
        name = str(run.get("name"))
        if name in CI_RED_HUMAN_ONLY:
            decisions.append(
                Decision(
                    action="skip",
                    detector=SIG_CI_RED,
                    fingerprint=fingerprint(f"ci-red|{name}"),
                    reason=f"留给人:{CI_RED_HUMAN_ONLY[name]}",
                )
            )
            continue
        stack = CI_RED_STACKS.get(name)
        if stack is None:
            # 没登记的 workflow = 判不出栈 → fail-closed,不开单,但要让 run 变红。
            undecidable.append(f"ci-red: workflow「{name}」没有栈映射,判不出该派给谁")
            continue
        decisions.append(_ci_red_ticket(run, stack, judged_at))
    return decisions, undecidable


def decide_dep(
    alerts: Any, repo_root: Path, judged_at: str, min_severity: str = "high"
) -> Tuple[List[Decision], List[str]]:
    """依赖信号:只有「锁文件里仍受影响」的告警才开单。

    Args:
        alerts: `gh api .../dependabot/alerts` 的响应(列表,或 `{"alerts": [...]}`)。
        repo_root: 仓库根目录(用于读锁文件)。
        judged_at: 判定时间(UTC ISO)。
        min_severity: 严重度阈值,低于它只记录不开单。

    Returns:
        `(判定列表, 判不出来的原因列表)`。
    """
    decisions: List[Decision] = []
    undecidable: List[str] = []

    items = alerts.get("alerts") if isinstance(alerts, dict) else alerts
    if not isinstance(items, list):
        return [], ["dep-advisory: 告警响应不是列表,判不出有没有漏洞"]

    threshold = SEVERITY_ORDER.get(min_severity.lower(), 2)
    for alert in items:
        if not isinstance(alert, dict):
            undecidable.append("dep-advisory: 告警条目不是对象")
            continue
        dependency = alert.get("dependency") or {}
        package = dependency.get("package") or {}
        name = str(package.get("name") or "")
        ecosystem = str(package.get("ecosystem") or "")
        ghsa = str((alert.get("security_advisory") or {}).get("ghsa_id") or "")
        fp = fingerprint(f"dep|{ecosystem}|{name}|{ghsa}")

        if str(alert.get("state") or "") != "open" or alert.get("dismissed_at"):
            continue
        severity = _alert_severity(alert)
        if SEVERITY_ORDER.get(severity, 0) < threshold:
            decisions.append(
                Decision(
                    action="skip",
                    detector=SIG_DEP,
                    fingerprint=fp,
                    reason=f"严重度 {severity or '未知'} 低于阈值 {min_severity}(只记录,不开单)",
                )
            )
            continue
        stack = _alert_stack(alert)
        if stack is None:
            decisions.append(
                Decision(
                    action="skip",
                    detector=SIG_DEP,
                    fingerprint=fp,
                    reason=f"生态 {ecosystem or '?'} / 清单 {dependency.get('manifest_path')} "
                    "不在白名单(修复动的是 worker 不可写或必须人审的文件)",
                )
            )
            continue
        patched = str(
            ((alert.get("security_vulnerability") or {}).get("first_patched_version") or {}).get(
                "identifier"
            )
            or ""
        )
        if not patched:
            decisions.append(
                Decision(
                    action="skip",
                    detector=SIG_DEP,
                    fingerprint=fp,
                    reason="没有修复版本 —— 「怎么办」变成判断(绕开 / 接受风险 / 换库),留给人",
                )
            )
            continue

        current = locked_version(repo_root, ecosystem, name)
        if current is None:
            undecidable.append(
                f"dep-advisory: 锁文件里找不到 {ecosystem}/{name},判不出是否仍受影响"
            )
            continue
        affected = version_in_range(current, str((alert.get("security_vulnerability") or {}).get("vulnerable_version_range") or ""))
        if affected is None:
            undecidable.append(
                f"dep-advisory: {name} 的受影响区间解析不了"
                f"({(alert.get('security_vulnerability') or {}).get('vulnerable_version_range')!r})"
            )
            continue
        if not affected:
            decisions.append(
                Decision(
                    action="skip",
                    detector=SIG_DEP,
                    fingerprint=fp,
                    reason=f"锁文件里已是 {current},不在受影响区间内(告警滞后,可顺手 dismiss)",
                )
            )
            continue
        decisions.append(_dep_ticket(alert, stack, current, judged_at))
    return decisions, undecidable


def decide_docs_links(repo_root: Path, judged_at: str) -> Tuple[List[Decision], List[str]]:
    """机械一致性信号:文档断链,按文件聚合,一个文件一张单。

    Args:
        repo_root: 仓库根目录。
        judged_at: 判定时间(UTC ISO)。

    Returns:
        `(判定列表, 判不出来的原因列表)`。
    """
    try:
        broken = check_docs_links.find_broken_links(repo_root)
    except (OSError, FileNotFoundError) as exc:
        return [], [f"mech-docs-links: 判定失败 —— {exc}"]

    grouped: Dict[str, List[dict]] = {}
    for item in broken:
        grouped.setdefault(str(item["file"]), []).append(item)
    return [_docs_ticket(file, items, judged_at) for file, items in sorted(grouped.items())], []


def scan_info(repo_root: Path, runs: Any, alerts: Any) -> dict:
    """统计这一轮「到底扫到了多少」,写进计划与日报。

    没有它,「扫了 128 个文件、没有断链」与「一个文件都没扫到」在日报里长得一模一样
    —— 2026-11-12 首次真跑就卡在这个歧义上(见 `docs/ops/superagent.md` §14.4)。
    这里任何一项取不到都只是 `None`,绝不影响判定。

    Args:
        repo_root: 仓库根目录。
        runs: 默认分支 push runs 快照。
        alerts: 告警快照。

    Returns:
        含各信号「扫到了多少」的字典。
    """
    info: Dict[str, Any] = {
        "workflows_seen": None,
        "red_workflows": None,
        "alerts_seen": None,
        "docs_root": str((repo_root / "docs").resolve()),
        "docs_markdown_files": None,
        "broken_links": None,
        "broken_files": None,
    }
    try:
        latest = latest_runs_by_workflow(runs)
        info["workflows_seen"] = len(latest)
        info["red_workflows"] = sum(1 for run in latest if run.get("conclusion") == "failure")
    except (ValueError, TypeError):
        pass

    items = alerts.get("alerts") if isinstance(alerts, dict) else alerts
    if isinstance(items, list):
        info["alerts_seen"] = len(items)

    try:
        info["docs_markdown_files"] = check_docs_links.count_markdown_files(repo_root)
        broken = check_docs_links.find_broken_links(repo_root)
        info["broken_links"] = len(broken)
        info["broken_files"] = len({str(item["file"]) for item in broken})
        # 采样几个被扫到的文件:用来证明「扫的到底是哪棵树」。
        docs_dir = (repo_root / "docs")
        if docs_dir.is_dir():
            info["docs_sample"] = [
                path.relative_to(repo_root.resolve()).as_posix()
                for path in sorted(docs_dir.rglob("*.md"))[:3]
            ]
    except (OSError, FileNotFoundError):
        pass
    return info


# ── 去重 + 限额


def existing_fingerprints(issues: Any) -> Dict[str, dict]:
    """从已有 issue 快照里抽出「指纹 → issue」映射。

    Args:
        issues: `gh issue list --json number,title,state,body,createdAt` 的结果(列表)。

    Returns:
        字典:指纹 → `{"number":…, "state":…, "title":…}`。没有指纹的 issue 被忽略。
    """
    index: Dict[str, dict] = {}
    items = issues if isinstance(issues, list) else []
    for issue in items:
        if not isinstance(issue, dict):
            continue
        match = FINGERPRINT_RE.search(str(issue.get("body") or ""))
        if not match:
            continue
        index[match.group(1)] = {
            "number": issue.get("number"),
            "state": str(issue.get("state") or ""),
            "title": str(issue.get("title") or ""),
        }
    return index


def created_today(issues: Any, today: str) -> int:
    """统计今天(UTC 日)已经由 L4 开出的 issue 数,用于每日限额。

    Args:
        issues: `gh issue list --json number,createdAt` 的结果(列表)。
        today: `YYYY-MM-DD`(UTC)。

    Returns:
        当天创建的 issue 数。
    """
    if not isinstance(issues, list):
        return 0
    return sum(
        1
        for issue in issues
        if isinstance(issue, dict) and str(issue.get("createdAt") or "")[:10] == today
    )


def apply_dedup(
    decisions: List[Decision],
    existing: Dict[str, dict],
    already_today: int,
    max_per_day: int,
    judged_at: str,
) -> List[Decision]:
    """把「开单」判定按去重与限额改写为 comment / reopen / defer。

    Args:
        decisions: 三个判定器给出的原始判定。
        existing: `existing_fingerprints` 的结果。
        already_today: 今天已开的单数。
        max_per_day: 每日新建上限(0 表示今天一张都不许新建)。
        judged_at: 判定时间(UTC ISO)。

    Returns:
        改写后的判定列表(顺序不变)。
    """
    out: List[Decision] = []
    created = already_today
    for decision in decisions:
        if decision.action != "create":
            out.append(decision)
            continue
        known = existing.get(decision.fingerprint)
        if known and known.get("number"):
            reopen = known.get("state", "").lower() == "closed"
            decision.action = "reopen" if reopen else "comment"
            decision.issue = int(known["number"])
            decision.reason = (
                f"同一失败已有 issue #{decision.issue},已关闭 → 重开而不是新建"
                if reopen
                else f"同一失败已有 open 的 issue #{decision.issue},只追加一次命中记录"
            )
            decision.body = _scrub_mentions(
                f"**再次命中**(`{judged_at}`)\n\n"
                f"信号 `{decision.detector}` 的判据仍然成立(指纹 `{decision.fingerprint}` 未变)。"
                "这条评论由 `l4-intake.yml` 自动追加,**没有新建 issue**。"
            )
            out.append(decision)
            continue
        if created >= max_per_day:
            decision.action = "defer"
            decision.reason = f"今日配额已满({created}/{max_per_day}),明天再判"
            out.append(decision)
            continue
        created += 1
        out.append(decision)
    return out


# ── plan / apply


def build_plan(
    runs: Any,
    alerts: Any,
    issues: Any,
    repo_root: Path,
    judged_at: str,
    max_per_day: int = 5,
    min_severity: str = "high",
    enabled: bool = True,
    today: Optional[str] = None,
) -> dict:
    """把三份事实快照跑成一份可审阅的计划(纯函数,不碰网络、不碰 issue)。

    Args:
        runs: 默认分支 push runs 快照。
        alerts: Dependabot 告警快照。
        issues: 已有 `l4-auto` issue 快照。
        repo_root: 仓库根目录。
        judged_at: 判定时间(UTC ISO)。
        max_per_day: 每日新建上限。
        min_severity: 依赖告警的严重度阈值。
        enabled: 总闸;`False` 时返回空计划(但仍报告判不出来的项)。
        today: 覆盖「今天」的 UTC 日期(自测用)。

    Returns:
        plan 字典,含 `decisions` / `undecidable` / `summary`。
    """
    day = today or judged_at[:10]
    if not enabled:
        return {
            "enabled": False,
            "judged_at": judged_at,
            "decisions": [],
            "undecidable": [],
            "summary": {},
            "note": "L4_INTAKE 关闭:本轮只记录不动作",
        }

    decisions: List[Decision] = []
    undecidable: List[str] = []

    for produced, reasons in (
        decide_ci_red(runs, judged_at),
        decide_dep(alerts, repo_root, judged_at, min_severity),
        decide_docs_links(repo_root, judged_at),
    ):
        decisions.extend(produced)
        undecidable.extend(reasons)

    before = len([d for d in decisions if d.action == "create"])
    decisions = apply_dedup(
        decisions,
        existing_fingerprints(issues),
        created_today(issues, day),
        max_per_day,
        judged_at,
    )
    summary: Dict[str, int] = {}
    for decision in decisions:
        summary[decision.action] = summary.get(decision.action, 0) + 1
    return {
        "enabled": True,
        "judged_at": judged_at,
        "today": day,
        "max_per_day": max_per_day,
        "candidates": before,
        "scan": scan_info(repo_root, runs, alerts),
        "decisions": [asdict(decision) for decision in decisions],
        "undecidable": undecidable,
        "summary": summary,
    }


def render_plan_markdown(plan: dict) -> str:
    """把计划渲染成 job summary(人每天扫一眼的日报)。

    Args:
        plan: `build_plan` 的返回值。

    Returns:
        Markdown 文本。
    """
    lines = ["## L4 需求自动入队", ""]
    if not plan.get("enabled", True):
        lines.append(f"- 总闸:`L4_INTAKE` 关闭 —— {plan.get('note', '')}")
        return "\n".join(lines) + "\n"
    summary = plan.get("summary") or {}
    lines.append(
        f"- 判定时间:`{plan.get('judged_at')}` · 今日({plan.get('today')})"
        f"新建上限:{plan.get('max_per_day')}"
    )
    lines.append(
        "- 结论:"
        + " · ".join(f"{key} {value}" for key, value in sorted(summary.items()))
        if summary
        else "- 结论:本轮没有命中任何白名单信号(没有断链、没有红轨、没有仍受影响的漏洞)"
    )
    scan = plan.get("scan") or {}
    if scan:
        lines.append(
            "- 扫描面(区分「没命中」与「根本没扫」):"
            f"workflow {scan.get('workflows_seen')} 条(红 {scan.get('red_workflows')}) · "
            f"告警 {scan.get('alerts_seen')} 条 · "
            f"`{scan.get('docs_root')}` 下 {scan.get('docs_markdown_files')} 个 .md"
            f"(断链 {scan.get('broken_links')} 处 / {scan.get('broken_files')} 个文件)"
        )
    lines.append("")
    lines.append("| 信号 | 动作 | 对象 | 说明 |")
    lines.append("|---|---|---|---|")
    for decision in plan.get("decisions") or []:
        subject = decision.get("title") or decision.get("fingerprint")
        if decision.get("issue"):
            subject = f"#{decision['issue']}"
        lines.append(
            f"| `{decision.get('detector')}` | {decision.get('action')} | "
            f"{_scrub_mentions(str(subject))} | {_scrub_mentions(str(decision.get('reason') or ''))} |"
        )
    if plan.get("undecidable"):
        lines += ["", "### ⚠️ 判不出来(按 fail-closed 处理:没有开单)", ""]
        lines += [f"- {_scrub_mentions(item)}" for item in plan["undecidable"]]
    return "\n".join(lines) + "\n"


def build_gh_commands(plan: dict, repo: str) -> List[List[str]]:
    """把计划翻译成 `gh` 命令序列(纯函数,自测直接断言 argv)。

    Args:
        plan: `build_plan` 的返回值。
        repo: `owner/name`。

    Returns:
        命令列表,每项是 `gh` 的 argv(不含 `gh` 本身)。
    """
    commands: List[List[str]] = []
    actions = {decision["action"] for decision in plan.get("decisions") or []}
    if actions & {"create", "comment", "reopen"}:
        commands.append(
            [
                "label", "create", LABEL_AUTO,
                "--color", "5319E7",
                "--description", "L4 自动入队创建(机器判定,非产品设想)",
                "--force",
            ]
        )
        for signal in DETECTORS:
            commands.append(
                [
                    "label", "create", f"{LABEL_PREFIX}{signal}",
                    "--color", "BFD4F2",
                    "--description", f"L4 信号:{signal}",
                    "--force",
                ]
            )
    for decision in plan.get("decisions") or []:
        action = decision["action"]
        if action == "create":
            commands.append(
                [
                    "issue", "create",
                    "--title", decision["title"],
                    "--body", decision["body"],
                    "--label", LABEL_AUTO,
                    "--label", f"{LABEL_PREFIX}{decision['detector']}",
                    "--repo", repo,
                ]
            )
        elif action == "comment":
            commands.append(
                ["issue", "comment", str(decision["issue"]), "--body", decision["body"], "--repo", repo]
            )
        elif action == "reopen":
            commands.append(["issue", "reopen", str(decision["issue"]), "--repo", repo])
            commands.append(
                ["issue", "comment", str(decision["issue"]), "--body", decision["body"], "--repo", repo]
            )
    return commands


def run_gh_commands(commands: List[List[str]], dry_run: bool = False) -> List[str]:
    """执行 gh 命令,收集失败说明。

    Args:
        commands: `build_gh_commands` 的输出。
        dry_run: `True` 时只打印,不执行。

    Returns:
        失败说明列表(空列表表示全部成功)。
    """
    failures: List[str] = []
    for argv in commands:
        printable = " ".join(argv)
        if dry_run:
            print(f"[dry-run] gh {printable}")
            continue
        result = subprocess.run(
            ["gh", *argv], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            failures.append(f"gh {argv[0]} {argv[1]} 失败:{result.stderr.strip()[:300]}")
        else:
            print(f"ok gh {argv[0]} {argv[1]}:{(result.stdout or '').strip()[:200]}")
    return failures


# ── CLI


def _cmd_plan(args: argparse.Namespace) -> int:
    """`plan` 子命令的实现。

    Args:
        args: 命令行参数。

    Returns:
        进程退出码。
    """
    try:
        runs = _load_json(args.runs)
    except (OSError, json.JSONDecodeError) as exc:
        runs = {"__error__": str(exc)}
    try:
        alerts = _load_json(args.alerts)
    except (OSError, json.JSONDecodeError) as exc:
        alerts = {"__error__": str(exc)}
    try:
        issues = _load_json(args.existing) if args.existing else []
    except (OSError, json.JSONDecodeError) as exc:
        issues = {"__error__": str(exc)}

    plan = build_plan(
        runs=runs,
        alerts=alerts,
        issues=issues,
        repo_root=Path(args.root),
        judged_at=_now_iso(),
        max_per_day=args.max_per_day,
        min_severity=args.min_severity,
        enabled=args.enabled,
        today=args.today,
    )
    # 输入坏掉 = 判不出来 → fail-closed:一条都不开,并把整轮标红。
    bad_input = False
    for label, payload in (("runs", runs), ("alerts", alerts), ("existing", issues)):
        if isinstance(payload, dict) and "__error__" in payload:
            plan["undecidable"].append(f"{label}: 输入读不出来({payload['__error__']})")
            bad_input = True
    if bad_input:
        plan["decisions"] = [d for d in plan["decisions"] if d["action"] != "create"]
        # 计划里「开了几张」必须与最终 decisions 一致:日报是唯一的复核入口,
        # 报 3 张实际开 0 张会让人以为机制正常。
        plan["summary"] = {}
        for decision in plan["decisions"]:
            key = decision["action"]
            plan["summary"][key] = plan["summary"].get(key, 0) + 1

    payload = json.dumps(plan, ensure_ascii=False, indent=2)
    if args.json_out:
        Path(args.json_out).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    markdown = render_plan_markdown(plan)
    if args.summary_out:
        Path(args.summary_out).write_text(markdown, encoding="utf-8")
    print(markdown, file=sys.stderr)
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    """`apply` 子命令的实现。

    Args:
        args: 命令行参数。

    Returns:
        进程退出码(判不出来或有命令失败 → 1;否则 0)。
    """
    plan = _load_json(args.plan)
    commands = build_gh_commands(plan, args.repo)
    failures = run_gh_commands(commands, dry_run=args.dry_run)
    for failure in failures:
        print(f"::error::{failure}", file=sys.stderr)
    for reason in plan.get("undecidable") or []:
        print(f"::error::L4 判定器判不出来(已按 fail-closed 不开单):{reason}", file=sys.stderr)
    return 1 if failures or plan.get("undecidable") else 0


def _cmd_ci_red_summary(args: argparse.Namespace) -> int:
    """`ci-red-summary` 子命令的实现:给 `main-health.yml` 复用同一解析器。

    Args:
        args: 命令行参数。

    Returns:
        进程退出码(0 = 正常;2 = 输入读不出来)。
    """
    try:
        runs = _load_json(args.runs)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"l4_intake: 读不了 runs 快照 —— {exc}", file=sys.stderr)
        return 2
    try:
        print(render_ci_red_summary(runs))
    except ValueError as exc:
        print(f"l4_intake: {exc}", file=sys.stderr)
        return 2
    return 0


def _cmd_from_npm_audit(args: argparse.Namespace) -> int:
    """`from-npm-audit` 子命令:把 `npm audit --json` 规整成告警记录。

    Args:
        args: 命令行参数。

    Returns:
        进程退出码(0 = 正常;2 = 输入读不出来 —— 与判定器 `plan` 的 0 不同,
        因为这一步的输入坏掉意味着「判不出来」)。
    """
    try:
        report = _load_json(args.input)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"l4_intake: 读不了 npm audit 报告 —— {exc}", file=sys.stderr)
        return 2
    if isinstance(report, dict) and "vulnerabilities" not in report:
        print(
            f"l4_intake: npm audit 报告里没有 vulnerabilities 字段(键:{sorted(report)[:6]})",
            file=sys.stderr,
        )
        return 2
    records = normalize_npm_audit(report, manifest=args.manifest)
    payload = json.dumps(records, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    print(f"l4_intake: 从 npm audit 规整出 {len(records)} 条公告记录", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。

    Returns:
        配好三个子命令的 `ArgumentParser`。
    """
    parser = argparse.ArgumentParser(description="L4 需求自动入队判定器")
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan", help="判定并输出计划(离线)")
    plan.add_argument("--runs", required=True, help="默认分支 push runs 的 JSON 快照(- = stdin)")
    plan.add_argument("--alerts", required=True, help="Dependabot 告警的 JSON 快照")
    plan.add_argument("--existing", default="", help="已有 l4-auto issue 的 JSON 快照")
    plan.add_argument("--root", default=".", help="仓库根目录")
    plan.add_argument(
        "--max-per-day",
        type=int,
        default=int(os.environ.get("L4_MAX_PER_DAY") or "5"),
        help="每日新建上限(默认 5;0 = 今天一张都不新建)",
    )
    plan.add_argument(
        "--min-severity",
        default=os.environ.get("L4_MIN_SEVERITY") or "high",
        help="依赖告警的严重度阈值(默认 high)",
    )
    plan.add_argument("--today", default=None, help="覆盖「今天」的日期(自测用)")
    plan.add_argument("--json-out", default="", help="计划写这里(默认 stdout)")
    plan.add_argument("--summary-out", default="", help="job summary 写这里")
    plan.add_argument(
        "--enabled",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="总闸(L4_INTAKE=on/off)",
    )
    plan.set_defaults(func=_cmd_plan)

    apply_cmd = sub.add_parser("apply", help="按计划执行 gh 命令")
    apply_cmd.add_argument("--plan", required=True, help="plan 子命令产出的 JSON")
    apply_cmd.add_argument("--repo", required=True, help="owner/name")
    apply_cmd.add_argument("--dry-run", action="store_true")
    apply_cmd.set_defaults(func=_cmd_apply)

    summary = sub.add_parser("ci-red-summary", help="输出默认分支红轨的 Markdown 列表")
    summary.add_argument("--runs", required=True, help="runs 快照(- = stdin)")
    summary.set_defaults(func=_cmd_ci_red_summary)

    npm = sub.add_parser(
        "from-npm-audit", help="把 `npm audit --json` 规整成判定器认识的告警记录"
    )
    npm.add_argument("--input", required=True, help="npm audit --json 的输出(- = stdin)")
    npm.add_argument("--manifest", default="web/package.json", help="清单路径(映射到栈)")
    npm.add_argument("--out", default="", help="写这里(默认 stdout)")
    npm.set_defaults(func=_cmd_from_npm_audit)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """命令行入口。

    Args:
        argv: 参数列表;`None` 表示用 `sys.argv[1:]`。

    Returns:
        进程退出码。
    """
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
