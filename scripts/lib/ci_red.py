#!/usr/bin/env python3
"""CI 红轨的判定口径(唯一一份实现,给 L4 自动入队与 worker 巡检共用)。

为什么单独抽出来
----------------
2026-11-16 之前这段判据住在 ``scripts/l4_intake.py`` 里,只有 L4 与 ``main-health.yml`` 用。
把「默认分支红轨」并进 worker 巡检之后出现了第二个调用方,而巡检器是**自包含安装**的
(``install.sh`` 把它拷到 ``/root/.dsh/healthcheck/``,仓库不在 ``sys.path`` 里)——
直接 ``from scripts import l4_intake`` 会在安装布局下抛 ``ModuleNotFoundError``,
整轮巡检变成「判不出来」(2026-11-17 实测,空告警已经发出去了)。

所以把判据拆成本模块:**只依赖标准库、不 import 仓库里任何别的东西**,于是
``install.sh`` 可以把它与巡检器并排拷贝,两种布局都能用:

    # 仓库内 / unittest
    from scripts.lib import ci_red
    # 安装布局(与 superagent_health.py 同级)
    import ci_red

``l4_intake.py`` 仍然对外暴露 ``red_runs`` / ``is_red_run`` / ``latest_runs_by_workflow``
(转手 re-export),所以既有的调用方与用例一行都不用改;``scripts/test_lib.py`` 会断言
两边是**同一个对象**,防止有人再抄一份。

设计要点:
    1. 「红」= 结论落在 :data:`RED_CONCLUSIONS` 里,不是「等于 failure」——
       ``cancelled`` / ``timed_out`` / ``startup_failure`` 都是没跑绿;
    2. 只认**每条 workflow 的最新一次** run:红了又被人手动重跑成绿就不算红;
    3. 形状不对一律抛 ``ValueError``,由调用方 fail-closed(宁可报「判不出来」)。

注意事项:
    - 本模块**不许**新增对 ``scripts/`` 里其它模块的依赖 —— 那会让安装布局重新坏掉。
"""

from __future__ import annotations

from typing import Any, List

#: 这些结论视为「红」。命名对齐 `scripts/deploy_gate.py::OK_CONCLUSIONS` ——
#: 那边定义什么算通过,这边定义什么算失败,看的是同一个 GitHub `conclusion` 字段。
#:
#: 为什么不写 `== "failure"`:`cancelled`(并发组被顶 / 手动取消 / 整轮被取消)、
#: `timed_out`、`startup_failure`(workflow 文件本身解析失败,run 根本没起来)、
#: `action_required`(要人工批准才跑)、`stale`(排队太久被 GitHub 判废)全都是
#: **没跑绿**。只认 `failure` 等于把这五种红静默当绿 —— 2026-11-13 #283/#285 修的就是这个。
#: `success` / `skipped` / `neutral` 不判红(`skipped` 在 `ci-scope.sh` 的「按改动面跑」
#: 里是正常结果,与 required check 语义一致);`conclusion is None` 也不判红 ——
#: 那是**还在跑**,等下一轮快照。
RED_CONCLUSIONS = frozenset(
    {"failure", "cancelled", "timed_out", "startup_failure", "action_required", "stale"}
)


def is_red_run(run: dict) -> bool:
    """判断一条 run 是不是「红」——口径唯一入口。

    Args:
        run: 一条 Actions run 记录。

    Returns:
        结论落在 :data:`RED_CONCLUSIONS` 里为 `True`;`success` / `skipped` /
        `neutral` 与 `conclusion is None`(仍在跑)一律 `False`。
    """
    return run.get("conclusion") in RED_CONCLUSIONS


def latest_runs_by_workflow(runs: Any) -> List[dict]:
    """取出「每条 workflow 的最新一次 run」。

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

    判据是 :data:`RED_CONCLUSIONS`(红集合),不是「等于 `failure`」。

    Args:
        runs: `gh api .../actions/runs` 的响应。

    Returns:
        红 run 的字典列表,按 workflow 名字典序。

    Raises:
        ValueError: 形状不对。
    """
    red = [run for run in latest_runs_by_workflow(runs) if is_red_run(run)]
    return sorted(red, key=lambda run: str(run.get("name")))
