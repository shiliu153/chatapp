#!/usr/bin/env python3
"""superagent worker 健康检查:出网、入队三连、僵尸 assignment。

为什么存在
----------
2026-11-13 实测到两种「外面看起来一切正常、其实早就不干活」的故障:

* mihomo 端口 7890 在听、面板每个健康位都是 `ready`,但它解析不到机场节点域名,
  出网 0% —— worker 的 git / 轮询全断;
* 模型流一次 `stream idle timeout` 之后 assignment 卡在 `running` 六小时,
  worktree 一个提交都没有,也不会有任何报错浮到面板上。

这两类都不是「红了」,而是「绿着但不动」,只能靠**外部周期性探测**发现。本脚本就是那个
探测:给 systemd timer 调用,不依赖任何交互式会话。机器关着的时候本来就轮不到它 ——
没有 worker 可查,恢复开机后 `OnBootSec` 会立刻补跑一轮。

退出码
------
0 = 全部正常;1 = 有异常(该发告警);2 = 判不出来(同样该发告警,但绝不能当成正常)。

用法
----
    python3 healthcheck.py                      # 人类可读摘要
    python3 healthcheck.py --json               # 机器可读
    python3 healthcheck.py --issue 285 --issue 280
    python3 healthcheck.py --skip-egress        # 离线/自测

文件信息:
    文件名称          scripts/superagent_health.py
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
import sqlite3
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_DB = "/root/.dsh/state/superagent/orchestrator.sqlite"
DEFAULT_WORK = "/root/.dsh/state/superagent/work"
DEFAULT_PROXY = "http://127.0.0.1:7890"
DEFAULT_PROXY_CONFIG = "/root/.dsh/proxy/config.yaml"
DEFAULT_TOKEN = "/root/.dsh/github-mcp-token.txt"
EGRESS_URL = "https://api.github.com/rate_limit"

OK = "ok"
BAD = "bad"


@dataclass
class Check:
    """一条检查结果。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``obj = Check(...)``

    备注信息:
        name: 检查项名字(告警里直接展示)。
        state: `ok` 或 `bad`。
        detail: 一句话说明,能带数字就带数字。
    """

    name: str
    state: str
    detail: str


@dataclass
class Report:
    """整轮巡检结果。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``obj = Report(...)``

    备注信息:
        checks: 全部检查项。
        anomalies: 状态为 `bad` 的检查项名字列表。
        unknown: 判不出来时的原因(非空即退出码 2)。
    """

    checks: List[Check] = field(default_factory=list)
    anomalies: List[str] = field(default_factory=list)
    unknown: List[str] = field(default_factory=list)

    def add(self, check: Check) -> None:
        """追加一条检查,并自动把 `bad` 记进 anomalies。

        参数说明:
            check: 一条检查结果(``Check``);``state`` 非 ok 的会计入 anomalies。

        返回参数:
            无返回值。

        使用示例:
            ``obj.add(check)``

        备注信息:
            无特殊约束。
        """
        self.checks.append(check)
        if check.state != OK:
            self.anomalies.append(check.name)

    def exit_code(self) -> int:
        """按契约给出退出码:0 正常 / 1 有异常 / 2 判不出来。

        参数说明:
            无。

        返回参数:
            ``int``。

        使用示例:
            ``obj.exit_code()``

        备注信息:
            无特殊约束。
        """
        if self.unknown:
            return 2
        return 1 if self.anomalies else 0

    def to_dict(self) -> Dict[str, Any]:
        """转成可 JSON 序列化的字典。

        参数说明:
            无。

        返回参数:
            ``Dict[str, Any]``。

        使用示例:
            ``obj.to_dict()``

        备注信息:
            无特殊约束。
        """
        return {
            "checks": [asdict(check) for check in self.checks],
            "anomalies": self.anomalies,
            "unknown": self.unknown,
            "exit_code": self.exit_code(),
        }


def _parse_ts(text: Any) -> Optional[datetime]:
    """解析 orchestrator 里的 ISO 时间(`...Z`),失败返回 None。

    备注信息:
        无特殊约束。
    """
    if not isinstance(text, str) or not text:
        return None
    raw = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _read_token(path: str) -> Optional[str]:
    """读 GitHub token(可缺省)。

    备注信息:
        无特殊约束。
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            token = handle.read().strip()
    except OSError:
        return None
    return token or None


def check_egress(proxy: str, token: Optional[str], timeout: float = 15.0) -> Check:
    """经代理访问一次 GitHub API:这是 worker 全部外网能力的代表。

    参数说明:
        proxy: 出口代理 URL(如 `http://127.0.0.1:7890`)。
        token: GitHub token;给了就带上,避免匿名限流误判。
        timeout: 单次超时秒数。

    返回参数:
        一条检查结果:`ok` 表示真的拿到 2xx。

    使用示例:
        ``check_egress(proxy, token, timeout)``

    备注信息:
        无特殊约束。
    """
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )
    request = urllib.request.Request(EGRESS_URL, headers={"User-Agent": "superagent-health"})
    if token:
        request.add_header("Authorization", "Bearer " + token)
    started = datetime.now(timezone.utc)
    try:
        with opener.open(request, timeout=timeout) as resp:
            status = resp.status
    except urllib.error.HTTPError as exc:
        return Check("出网(api.github.com)", BAD, f"HTTP {exc.code}:代理通但接口报错")
    except Exception as exc:  # noqa: BLE001 - 任何异常都是「出网不通」
        return Check("出网(api.github.com)", BAD, f"{type(exc).__name__}: {exc}")
    elapsed = (datetime.now(timezone.utc) - started).total_seconds()
    if not 200 <= status < 300:
        return Check("出网(api.github.com)", BAD, f"HTTP {status}")
    return Check("出网(api.github.com)", OK, f"HTTP {status} · {elapsed:.1f}s")


def check_proxy_selector(config_path: str) -> Check:
    """看 mihomo 当前出口节点是不是兜底节点(兜底=机场全挂,值得提醒但不阻塞)。

    参数说明:
        config_path: mihomo 的 config.yaml(用来读 controller secret)。

    返回参数:
        一条检查结果:选到 `HOST-FALLBACK` 时给 `ok` 但说明里写明「走兜底」。

    使用示例:
        ``check_proxy_selector(config_path)``

    备注信息:
        无特殊约束。
    """
    secret = None
    try:
        with open(config_path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("secret:"):
                    secret = line.split(":", 1)[1].strip().strip("\"'")
                    break
    except OSError:
        return Check("出口节点", OK, "读不到 proxy 配置,跳过")
    if not secret:
        return Check("出口节点", OK, "proxy 配置无 secret,跳过")
    url = "http://127.0.0.1:9091/proxies/%E8%8A%82%E7%82%B9%E9%80%89%E6%8B%A9"
    request = urllib.request.Request(url, headers={"Authorization": "Bearer " + secret})
    try:
        with urllib.request.urlopen(request, timeout=8) as resp:
            payload = json.load(resp)
    except Exception as exc:  # noqa: BLE001 - controller 挂了不算 worker 异常
        return Check("出口节点", OK, f"controller 不可用({type(exc).__name__}),跳过")
    now = payload.get("now") or "?"
    if now == "HOST-FALLBACK":
        return Check("出口节点", OK, "走宿主兜底(机场线路不可用)")
    return Check("出口节点", OK, now)


def open_db(path: str) -> sqlite3.Connection:
    """只读打开 orchestrator 状态库。

    参数说明:
        path: sqlite 文件路径。

    返回参数:
        连接对象。

    使用示例:
        ``open_db(path)``

    备注信息:
        sqlite3.Error: 打不开或不是预期库。
    """
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def load_tickets(conn: sqlite3.Connection) -> List[Tuple[str, Dict[str, Any]]]:
    """读出全部 ticket 并解析 JSON(坏行跳过,不让它打断整轮巡检)。

    参数说明:
        conn: orchestrator 状态库连接。

    返回参数:
        `(ticket_id, 解析后的字典)` 列表。

    使用示例:
        ``load_tickets(conn)``

    备注信息:
        无特殊约束。
    """
    out: List[Tuple[str, Dict[str, Any]]] = []
    for ticket_id, value in conn.execute("select id, value from ticket").fetchall():
        try:
            data = json.loads(value)
        except (TypeError, ValueError):
            continue
        if isinstance(data, dict):
            out.append((str(ticket_id), data))
    return out


def ticket_issue_number(data: Dict[str, Any]) -> Optional[int]:
    """从 ticket 里取它对应的 GitHub 编号(issue 或 PR)。

    参数说明:
        data: 解析后的 ticket 字典。

    返回参数:
        编号;取不到返回 None。 这里刻意**不用** SQL 的 LIKE 匹配原始 JSON:同一份 JSON 紧凑/带空格的写法都出现过, 按字符串匹配会静默漏行(自测就是这么抓到 `"number": 285` 带空格时判成 0 张单)。

    使用示例:
        ``ticket_issue_number(data)``

    备注信息:
        无特殊约束。
    """
    scope = ((data.get("mandate") or {}).get("basis") or {}).get("scope") or {}
    number = scope.get("number")
    try:
        return int(number)
    except (TypeError, ValueError):
        return None


def check_enqueue(conn: sqlite3.Connection, issue: int) -> Check:
    """入队三连:thread / trigger_thread / ticket 三张表都要有该 issue 的记录。

    参数说明:
        conn: orchestrator 状态库连接。
        issue: GitHub issue 编号。

    返回参数:
        一条检查结果;任何一张表缺记录都算异常(评论可能压根没进队列)。

    使用示例:
        ``check_enqueue(conn, issue)``

    备注信息:
        无特殊约束。
    """
    key = f"github:{issue}"
    thread = conn.execute("select count(*) from thread where key=?", (key,)).fetchone()[0]
    trigger = conn.execute(
        "select count(*) from trigger_thread where thread=?", (key,)
    ).fetchone()[0]
    ticket = sum(1 for _, data in load_tickets(conn) if ticket_issue_number(data) == issue)
    detail = f"thread={thread} trigger={trigger} ticket={ticket}"
    state = OK if (thread and trigger and ticket) else BAD
    return Check(f"入队三连 #{issue}", state, detail)


def zombie_assignments(
    conn: sqlite3.Connection, now: datetime, threshold_minutes: int
) -> List[Check]:
    """找出「卡住不动」的 assignment:状态还在跑/待跑,但已经超过阈值没结束。

    参数说明:
        conn: orchestrator 状态库连接。
        now: 当前时间(测试可注入)。
        threshold_minutes: 超过多少分钟没结束就算卡住。

    返回参数:
        每个卡住的 assignment 一条 `bad` 检查(没有则返回空列表)。

    使用示例:
        ``zombie_assignments(conn, now, threshold_minutes)``

    备注信息:
        无特殊约束。
    """
    checks: List[Check] = []
    for _ticket_id, data in load_tickets(conn):
        for assignment in data.get("assignments") or []:
            state = assignment.get("state")
            if state not in ("running", "pending"):
                continue
            started = _parse_ts(assignment.get("startedAt") or assignment.get("createdAt"))
            if started is None:
                continue
            age_min = (now - started).total_seconds() / 60.0
            if age_min < threshold_minutes:
                continue
            report = assignment.get("report") or {}
            last = (report.get("summary") or "")[:80].replace("\n", " ")
            checks.append(
                Check(
                    f"僵尸 assignment {str(assignment.get('id'))[:8]}",
                    BAD,
                    f"state={state} 已 {age_min/60:.1f}h · {data.get('title')!r} · 最后 report: {last or '(无)'}",
                )
            )
    return checks


def check_worktrees(conn: sqlite3.Connection, workdir: str) -> List[Check]:
    """列出 work/ 下没有对应活跃 assignment 的残留目录(只提示,不算异常)。

    参数说明:
        conn: orchestrator 状态库连接。
        workdir: work/ 目录。

    返回参数:
        目录数量超过活跃 assignment 时给一条 `ok` 但信息完整的检查。

    使用示例:
        ``check_worktrees(conn, workdir)``

    备注信息:
        无特殊约束。
    """
    try:
        dirs = sorted(name for name in os.listdir(workdir) if os.path.isdir(os.path.join(workdir, name)))
    except OSError:
        return [Check("worktrees", OK, "work/ 不存在或读不到")]
    return [Check("worktrees", OK, f"{len(dirs)} 个目录: {', '.join(dirs) or '(空)'}")]


def build_report(args: argparse.Namespace, now: Optional[datetime] = None) -> Report:
    """跑完整一轮巡检。

    参数说明:
        args: 已解析的命令行参数。
        now: 当前时间(测试注入用),默认取 UTC now。

    返回参数:
        巡检结果。

    使用示例:
        ``build_report(args, now)``

    备注信息:
        无特殊约束。
    """
    report = Report()
    now = now or datetime.now(timezone.utc)
    token = _read_token(args.token_path)

    if not args.skip_egress:
        report.add(check_egress(args.proxy, token))
        report.add(check_proxy_selector(args.proxy_config))

    try:
        conn = open_db(args.db)
    except sqlite3.Error as exc:
        report.unknown.append(f"打不开 orchestrator 状态库({args.db}):{exc}")
        return report

    with conn:
        if not args.skip_enqueue:
            for issue in args.issue:
                report.add(check_enqueue(conn, int(issue)))
        for check in zombie_assignments(conn, now, args.zombie_minutes):
            report.add(_acknowledge(check, args.ignore))
        for check in check_worktrees(conn, args.workdir):
            report.add(check)
    return report


def _acknowledge(check: Check, ignore: List[str]) -> Check:
    """把人工确认作废的僵尸 assignment 从「异常」降级成「已确认」。

    参数说明:
        check: 一条检查结果(名字形如 `僵尸 assignment ce1d46c9`)。
        ignore: 已人工确认作废的 assignment id 前缀列表。

    返回参数:
        命中则返回 `ok` 版本(说明里保留原始信息),否则原样返回。 为什么需要它:DSH 没有「取消 assignment」的 CLI/API,一个被模型流打断的 assignment 会 永远停在 `running`。留着不管就是每 6 小时一条告警,而删库改状态风险更大 —— 所以给运营一个显式的确认口,而不是让告警被噪音化(那比没有告警更糟)。

    使用示例:
        ``_acknowledge(check, ignore)``

    备注信息:
        无特殊约束。
    """
    if not ignore:
        return check
    for prefix in ignore:
        if prefix and prefix in check.name:
            return Check(check.name, OK, f"已人工确认作废({prefix}) · 原始:{check.detail}")
    return check


def render_text(report: Report) -> str:
    """把巡检结果渲染成给人看的几行。

    参数说明:
        report: 巡检结果。

    返回参数:
        多行文本,最后一行是总体结论。

    使用示例:
        ``render_text(report)``

    备注信息:
        无特殊约束。
    """
    lines = []
    for check in report.checks:
        mark = "✅" if check.state == OK else "❌"
        lines.append(f"{mark} {check.name}: {check.detail}")
    for reason in report.unknown:
        lines.append(f"❓ 判不出来: {reason}")
    if report.unknown:
        lines.append("结论:判不出来(按异常处理)")
    elif report.anomalies:
        lines.append(f"结论:异常 {len(report.anomalies)} 项 → {', '.join(report.anomalies)}")
    else:
        lines.append("结论:全部正常")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。

    参数说明:
        无。

    返回参数:
        ``argparse.ArgumentParser``。

    使用示例:
        ``build_parser()``

    备注信息:
        无特殊约束。
    """
    parser = argparse.ArgumentParser(description="superagent worker 健康检查")
    parser.add_argument("--db", default=os.environ.get("SUPERAGENT_DB", DEFAULT_DB))
    parser.add_argument("--workdir", default=os.environ.get("SUPERAGENT_WORK", DEFAULT_WORK))
    parser.add_argument("--proxy", default=os.environ.get("SUPERAGENT_PROXY", DEFAULT_PROXY))
    parser.add_argument(
        "--proxy-config", default=os.environ.get("SUPERAGENT_PROXY_CONFIG", DEFAULT_PROXY_CONFIG)
    )
    parser.add_argument("--token-path", default=os.environ.get("SUPERAGENT_TOKEN", DEFAULT_TOKEN))
    parser.add_argument(
        "--issue",
        action="append",
        type=int,
        default=[],
        help="要核对入队三连的 issue 编号(可重复)",
    )
    parser.add_argument("--zombie-minutes", type=int, default=45, help="assignment 卡住阈值(分钟)")
    parser.add_argument(
        "--ignore",
        action="append",
        default=(os.environ.get("SUPERAGENT_HEALTH_IGNORE_ZOMBIES") or "").split(),
        help="已人工确认作废的 assignment id 前缀(可重复;也读 env)。DSH 没有取消 assignment 的口子,"
        "被模型流打断的那些会永远停在 running,留在这里而不是让告警变成噪音",
    )
    parser.add_argument("--skip-egress", action="store_true", help="跳过联网检查(离线自测)")
    parser.add_argument("--skip-enqueue", action="store_true", help="跳过入队三连")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """入口:跑巡检、打印、按契约返回退出码。

    参数说明:
        argv: 命令行参数列表;``None`` 时取 ``sys.argv[1:]``。

    返回参数:
        ``int``。

    使用示例:
        ``python scripts/superagent_health.py --json --skip-egress``

    备注信息:
        无特殊约束。
    """
    args = build_parser().parse_args(argv)
    try:
        report = build_report(args)
    except Exception as exc:  # noqa: BLE001 - 判不出来必须显式返回 2
        print(f"healthcheck 自身出错:{type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_text(report))
    return report.exit_code()


if __name__ == "__main__":
    sys.exit(main())
