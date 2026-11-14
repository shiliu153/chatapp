"""把压测结果 JSON 汇总成 Markdown 表,并与基线对比判断是否回归。

用法:
    python3 perf/report.py perf/results/*.json                 # 只出表
    python3 perf/report.py perf/results/*.json --baseline perf/baseline.json
    python3 perf/report.py perf/results/*.json --baseline perf/baseline.json --fail-on-regression

回归判定(任一即失败):
    - RPS 比基线低 20% 以上;
    - p99 比基线高 20% 以上;
    - 错误率 > 基线 + 1 个百分点。

文件信息:
    文件名称          perf/report.py
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
import sys
from pathlib import Path


def load_points(paths: list[str]) -> list[dict]:
    """读取结果文件,展开成「一个文件一行」的点。

    参数说明:
        paths: 结果 JSON 路径列表。

    返回参数:
        结果点列表(保留原始结构,附带来源文件名)。

    使用示例:
        ``load_points(paths)``

    备注信息:
        无特殊约束。
    """
    points = []
    for raw in paths:
        path = Path(raw)
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["_file"] = path.name
        points.append(payload)
    return points


def baseline_key(point: dict) -> tuple:
    """基线匹配键:场景 + 并发(+ 每连接条数)。

    参数说明:
        point: 结果点。

    返回参数:
        可哈希的匹配键。

    使用示例:
        ``baseline_key(point)``

    备注信息:
        无特殊约束。
    """
    params = point.get("params", {})
    return (point.get("scenario"), params.get("conns"), params.get("count"))


def fmt(value, digits: int = 1, suffix: str = "") -> str:
    """格式化数字,空值显示 ``-``。

    参数说明:
        value: 原始值。
        digits: 小数位。
        suffix: 后缀(如 ``ms``)。

    返回参数:
        展示用字符串。

    使用示例:
        ``fmt(value, digits, suffix)``

    备注信息:
        无特殊约束。
    """
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}{suffix}"
    return f"{value}{suffix}"


def markdown_table(points: list[dict]) -> str:
    """生成结果表。

    参数说明:
        points: 结果点列表。

    返回参数:
        Markdown 表格文本。

    使用示例:
        ``markdown_table(points)``

    备注信息:
        无特殊约束。
    """
    lines = [
        "| 场景 | 并发 | RPS | p50 | p95 | p99 | 错误率 | load 峰值 | 文件 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for point in sorted(points, key=lambda p: (p.get("scenario", ""),
                                               p.get("params", {}).get("conns") or 0)):
        result = point.get("result", {})
        lat = result.get("lat_ms") or {}
        params = point.get("params", {})
        resources = point.get("resources", {})
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} | {} |".format(
            point.get("scenario"),
            params.get("conns"),
            fmt(result.get("rps")),
            fmt(lat.get("p50"), 1, "ms"),
            fmt(lat.get("p95"), 1, "ms"),
            fmt(lat.get("p99"), 1, "ms"),
            fmt((result.get("error_rate") or 0) * 100, 2, "%"),
            fmt(resources.get("load1_peak"), 2),
            point.get("_file"),
        ))
    return "\n".join(lines)


def compare(points: list[dict], baseline: dict) -> tuple[str, list[str]]:
    """与基线逐点对比。

    参数说明:
        points: 实测结果点。
        baseline: ``baseline.json`` 的内容。

    返回参数:
        (Markdown 对比表, 回归说明列表)。

    使用示例:
        ``compare(points, baseline)``

    备注信息:
        无特殊约束。
    """
    index = {}
    for entry in baseline.get("points", []):
        index[(entry.get("scenario"), entry.get("conns"), entry.get("count"))] = entry

    lines = [
        "| 场景 | 并发 | 基线 RPS | 实测 RPS | ΔRPS | 基线 p99 | 实测 p99 | Δp99 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    regressions = []
    for point in sorted(points, key=lambda p: (p.get("scenario", ""),
                                               p.get("params", {}).get("conns") or 0)):
        entry = index.get(baseline_key(point))
        if entry is None:
            continue
        result = point.get("result", {})
        lat = result.get("lat_ms") or {}
        base_rps = entry.get("rps")
        base_p99 = entry.get("p99_ms")
        rps = result.get("rps")
        p99 = lat.get("p99")
        delta_rps = ((rps - base_rps) / base_rps * 100) if (rps and base_rps) else None
        delta_p99 = ((p99 - base_p99) / base_p99 * 100) if (p99 and base_p99) else None
        lines.append("| {} | {} | {} | {} | {} | {} | {} | {} |".format(
            point.get("scenario"), point.get("params", {}).get("conns"),
            fmt(base_rps), fmt(rps),
            "-" if delta_rps is None else f"{delta_rps:+.1f}%",
            fmt(base_p99, 1, "ms"), fmt(p99, 1, "ms"),
            "-" if delta_p99 is None else f"{delta_p99:+.1f}%",
        ))
        if delta_rps is not None and delta_rps < -20:
            regressions.append(
                f"{point.get('scenario')} @ {point.get('params', {}).get('conns')} 并发:"
                f"RPS 下降 {abs(delta_rps):.1f}%(基线 {base_rps} → 实测 {rps})")
        if delta_p99 is not None and delta_p99 > 20:
            regressions.append(
                f"{point.get('scenario')} @ {point.get('params', {}).get('conns')} 并发:"
                f"p99 上升 {delta_p99:.1f}%(基线 {base_p99}ms → 实测 {p99}ms)")
        error_rate = result.get("error_rate") or 0
        if error_rate > (entry.get("error_rate") or 0) + 0.01:
            regressions.append(
                f"{point.get('scenario')} @ {point.get('params', {}).get('conns')} 并发:"
                f"错误率 {error_rate * 100:.2f}% 超过基线")
    return "\n".join(lines), regressions


def main() -> int:
    """解析参数并输出报告。

    参数说明:
        无。

    返回参数:
        0 正常;1 有回归(且传了 ``--fail-on-regression``);2 没有可读结果。

    使用示例:
        ``python3 perf/report.py perf/results/*.json --baseline perf/baseline.json --fail-on-regression``

    备注信息:
        无特殊约束。
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("results", nargs="+", help="结果 JSON 文件(支持通配)")
    parser.add_argument("--baseline", default="")
    parser.add_argument("--fail-on-regression", action="store_true")
    args = parser.parse_args()

    points = load_points(args.results)
    if not points:
        print("没有可读的结果文件", file=sys.stderr)
        return 2

    print("## 压测结果\n")
    print(markdown_table(points))

    if args.baseline:
        baseline = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        table, regressions = compare(points, baseline)
        print("\n## 与基线对比(" + baseline.get("machine", "") + ")\n")
        print(table)
        if regressions:
            print("\n### 回归\n")
            for item in regressions:
                print(f"- {item}")
            if args.fail_on_regression:
                return 1
        else:
            print("\n无回归(阈值:RPS −20% / p99 +20% / 错误率 +1pp)。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
