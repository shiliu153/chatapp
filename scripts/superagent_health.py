#!/usr/bin/env python3
"""superagent worker 健康检查:出网、入队三连、僵尸 assignment、轮询游标新鲜度。

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

第三种同类故障(2026-11-16,一天两次):**通知轮询的游标停摆**。`status` 全绿、出网正常、
限流也没打满,但 `kv` 里的 `github-cursor:*` 停在几小时前不再前进,派工评论根本没人读 ——
`thread` / `ticket` 全是空的,而面板与 `errors` 一个字都不报。判据必须是
**「有未读通知,但游标没动」**:

* 只看「游标落后多久」会天天误报 —— 闲置时段本来就没有新评论,游标当然不动;
* 所以先看游标是否落后阈值(`SUPERAGENT_CURSOR_STALE_MINUTES`,默认 10 分钟),
  **再**看 GitHub 通知里有没有「未读且 `updated_at` 晚于游标」的条目:
  有 → 有活要干却没干,判异常;没有 → 闲置,跳过。

判定本身是只读的:**本脚本绝不重启 orchestrator**(重启会杀掉正在跑的会话,那是另一场评审)。
取证与根因见 `docs/ops/superagent.md` §15 与 PR 正文。

退出码
------
0 = 全部正常;1 = 有异常(该发告警);2 = 判不出来(同样该发告警,但绝不能当成正常)。

用法
----
    python3 healthcheck.py                      # 人类可读摘要
    python3 healthcheck.py --json               # 机器可读
    python3 healthcheck.py --issue 285 --issue 280
    python3 healthcheck.py --skip-egress        # 离线/自测
    python3 healthcheck.py --skip-cursor        # 不查游标(完全离线)
    python3 healthcheck.py --notifications-file n.json   # 用本地 JSON 冒充未读通知
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

DEFAULT_DB = "/root/.dsh/state/superagent/orchestrator.sqlite"
DEFAULT_WORK = "/root/.dsh/state/superagent/work"
DEFAULT_PROXY = "http://127.0.0.1:7890"
DEFAULT_PROXY_CONFIG = "/root/.dsh/proxy/config.yaml"
DEFAULT_TOKEN = "/root/.dsh/github-mcp-token.txt"
EGRESS_URL = "https://api.github.com/rate_limit"
NOTIFICATIONS_PATH = "notifications?all=false&per_page=50"
DEFAULT_CURSOR_STALE_MINUTES = 10
GH_CLI_CANDIDATES = ("/root/.dsh/bin/gh-agent", "/root/.local/bin/gh-agent")

OK = "ok"
BAD = "bad"

CURSOR_CHECK = "游标新鲜度"


@dataclass
class Check:
    """一条检查结果。

    Attributes:
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

    Attributes:
        checks: 全部检查项。
        anomalies: 状态为 `bad` 的检查项名字列表。
        unknown: 判不出来时的原因(非空即退出码 2)。
    """

    checks: List[Check] = field(default_factory=list)
    anomalies: List[str] = field(default_factory=list)
    unknown: List[str] = field(default_factory=list)

    def add(self, check: Check) -> None:
        """追加一条检查,并自动把 `bad` 记进 anomalies。"""
        self.checks.append(check)
        if check.state != OK:
            self.anomalies.append(check.name)

    def exit_code(self) -> int:
        """按契约给出退出码:0 正常 / 1 有异常 / 2 判不出来。"""
        if self.unknown:
            return 2
        return 1 if self.anomalies else 0

    def to_dict(self) -> Dict[str, Any]:
        """转成可 JSON 序列化的字典。"""
        return {
            "checks": [asdict(check) for check in self.checks],
            "anomalies": self.anomalies,
            "unknown": self.unknown,
            "exit_code": self.exit_code(),
        }


def _parse_ts(text: Any) -> Optional[datetime]:
    """解析 orchestrator 里的 ISO 时间(`...Z`),失败返回 None。"""
    if not isinstance(text, str) or not text:
        return None
    raw = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _read_token(path: str) -> Optional[str]:
    """读 GitHub token(可缺省)。"""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            token = handle.read().strip()
    except OSError:
        return None
    return token or None


def check_egress(proxy: str, token: Optional[str], timeout: float = 15.0) -> Check:
    """经代理访问一次 GitHub API:这是 worker 全部外网能力的代表。

    Args:
        proxy: 出口代理 URL(如 `http://127.0.0.1:7890`)。
        token: GitHub token;给了就带上,避免匿名限流误判。
        timeout: 单次超时秒数。

    Returns:
        一条检查结果:`ok` 表示真的拿到 2xx。
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

    Args:
        config_path: mihomo 的 config.yaml(用来读 controller secret)。

    Returns:
        一条检查结果:选到 `HOST-FALLBACK` 时给 `ok` 但说明里写明「走兜底」。
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


def _iso(moment: datetime) -> str:
    """把时间渲染成 `2026-11-16T14:09Z` 这种一眼能对比的写法。

    Args:
        moment: 带时区的时间。

    Returns:
        ISO 字符串(精确到分钟,省略秒)。
    """
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def read_cursors(conn: sqlite3.Connection) -> List[Tuple[str, datetime]]:
    """读出全部轮询游标 `github-cursor:<issue>` 及其时间。

    Args:
        conn: orchestrator 状态库连接。

    Returns:
        `(键名, 时间)` 列表;值解析不出来的行直接跳过(不因为一行脏数据误判整轮)。

    库里 `value` 存的是 JSON 字符串(`"2026-11-16T14:09:04.715Z"`,带引号),
    也见过不带引号的写法,所以先试 JSON 再退回原文。
    """
    out: List[Tuple[str, datetime]] = []
    for key, value in conn.execute(
        "select key, value from kv where key like 'github-cursor:%'"
    ).fetchall():
        try:
            raw = json.loads(value)
        except (TypeError, ValueError):
            raw = value
        moment = _parse_ts(raw)
        if moment is not None:
            out.append((str(key), moment))
    return out


def read_poll_heartbeat(conn: sqlite3.Connection) -> Optional[datetime]:
    """读出通知轮询的心跳 `github-since`(每轮结束都会前进,与「有没有新评论」无关)。

    Args:
        conn: orchestrator 状态库连接。

    Returns:
        心跳时间;读不到返回 None。

    它**不参与判定**(判据是「游标 + 未读通知」),只作为告警里的旁证:
    心跳停在很久以前 ⇒ 轮询 loop 自己停了;心跳新鲜而游标不动 ⇒ 本来就是闲置。
    """
    row = conn.execute("select value from kv where key='github-since'").fetchone()
    if not row:
        return None
    try:
        raw = json.loads(row[0])
    except (TypeError, ValueError):
        raw = row[0]
    return _parse_ts(raw)


def parse_notifications(payload: Any) -> List[Dict[str, Any]]:
    """把 `/notifications` 响应(或等价的注入值)规整成只留巡检关心的几个字段。

    Args:
        payload: GitHub `/notifications` 的 JSON(列表);非列表一律当空。

    Returns:
        每项的 `{number, title, updated_at, repo}`;`unread` 明确为假的条目丢掉。

    GitHub 的 `unread` 与我们真正关心的「还没读到的评论」不是一回事(通知可以一直不读),
    所以这里只做一次粗筛,真正的判据是 `updated_at` 是否晚于游标(见 `check_cursor`)。
    """
    out: List[Dict[str, Any]] = []
    if not isinstance(payload, list):
        return out
    for item in payload:
        if not isinstance(item, dict):
            continue
        if item.get("unread") is False:
            continue
        subject = item.get("subject") or {}
        url = subject.get("url") or ""
        tail = url.rstrip("/").rsplit("/", 1)[-1] if isinstance(url, str) else ""
        out.append(
            {
                "number": tail if tail.isdigit() else "",
                "title": subject.get("title") or "",
                "updated_at": item.get("updated_at") or "",
                "repo": ((item.get("repository") or {}).get("full_name") or ""),
            }
        )
    return out


def load_notifications_file(path: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """从本地 JSON 文件读未读通知 —— 自测与「反证」用,完全不联网。

    Args:
        path: JSON 文件路径,内容形如 `/notifications` 的响应列表。

    Returns:
        `(通知列表, 失败原因)`;失败原因非空时列表为空。
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError) as exc:
        return [], f"读不了通知文件 {path}:{type(exc).__name__}: {exc}"
    return parse_notifications(payload), None


def find_gh_cli(explicit: Optional[str] = None) -> Optional[str]:
    """找到能用的 GitHub CLI(优先配置的 `GH_CLI`,再 PATH,再已知安装位置)。

    Args:
        explicit: 显式配置的路径(`GH_CLI` / `--gh-cli`)。

    Returns:
        可执行文件路径;一个都没有时返回 None。
    """
    if explicit:
        return explicit
    for name in ("gh", "gh-agent"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in GH_CLI_CANDIDATES:
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def fetch_notifications(
    gh_cli: Optional[str], proxy: str, timeout: float = 25.0
) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """调 `gh api notifications` 取未读通知(经 worker 用的同一个出口代理)。

    Args:
        gh_cli: GitHub CLI 路径;None 表示自动探测。
        proxy: 出口代理 URL;国内直连 GitHub 不通,必须走它。
        timeout: 子进程超时秒数。

    Returns:
        `(通知列表, 失败原因)`。取不到时**不抛异常** —— 巡检本身不能因为一次网络抖动崩掉,
        由调用方把「判不出来」显式报出去。

    为什么走 `gh api` 而不是 urllib + token:token 在 gh 的 `hosts.yml` 里,巡检跑在 systemd
    里再抄一份 token 只是多一处会漂移的凭据;`gh` 那边已经有凭据与代理配置。
    """
    binary = find_gh_cli(gh_cli)
    if not binary:
        return [], "找不到 GitHub CLI(gh / gh-agent)"
    env = dict(os.environ)
    env.update({"HTTPS_PROXY": proxy, "HTTP_PROXY": proxy, "https_proxy": proxy, "http_proxy": proxy})
    try:
        done = subprocess.run(
            [binary, "api", NOTIFICATIONS_PATH],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return [], f"{type(exc).__name__}: {exc}"
    if done.returncode != 0:
        reason = (done.stderr or done.stdout or "").strip().splitlines()
        return [], f"{binary} api notifications 退出码 {done.returncode}:{reason[-1] if reason else '(无输出)'}"
    try:
        payload = json.loads(done.stdout or "[]")
    except ValueError as exc:
        return [], f"通知响应不是 JSON:{exc}"
    return parse_notifications(payload), None


def _describe_notification(item: Dict[str, Any]) -> str:
    """把一条通知渲染成告警里的一小段(编号 + 标题,标题截断)。

    Args:
        item: `parse_notifications` 规整过的一条。

    Returns:
        形如 `#405 [工单] flow: 巡检加「轮询游标新鲜度」…`。
    """
    title = (item.get("title") or "(无标题)").replace("\n", " ").strip()
    if len(title) > 40:
        title = title[:40] + "…"
    number = item.get("number") or ""
    return f"#{number} {title}" if number else title


def check_cursor(
    conn: sqlite3.Connection,
    now: datetime,
    stale_minutes: int,
    loader: Callable[[], Tuple[List[Dict[str, Any]], Optional[str]]],
) -> Tuple[Check, Optional[str]]:
    """第四项巡检:游标新鲜度 —— **有未读通知但游标没动**才算停摆。

    Args:
        conn: orchestrator 状态库连接。
        now: 当前时间(测试注入)。
        stale_minutes: 游标落后多少分钟才值得深究(默认 10)。
        loader: 取未读通知的函数,返回 `(通知列表, 失败原因)`。只在游标确实落后时才调用,
            于是「一切正常」的路径完全离线,也不消耗 GitHub 限流。

    Returns:
        `(检查结果, 判不出来的原因)`。原因非空表示通知取不到、判不了是否真有活要干。

    为什么不能用「游标落后」单独判:闲置时段(夜里、没派人)本来就没有新评论,`github-cursor:*`
    当然不动 —— 只判时间会天天误报,而误报会把告警训成噪音,那比没有告警更糟。
    """
    cursors = read_cursors(conn)
    if not cursors:
        return Check(CURSOR_CHECK, OK, "库里没有 github-cursor 记录(全新库?),跳过"), None
    newest_key, newest = max(cursors, key=lambda item: item[1])
    lag_min = (now - newest).total_seconds() / 60.0
    heartbeat = read_poll_heartbeat(conn)
    beat = f" · 轮询心跳 {_iso(heartbeat)}" if heartbeat else ""
    if lag_min < stale_minutes:
        return (
            Check(
                CURSOR_CHECK,
                OK,
                f"游标 {_iso(newest)}(落后 {lag_min:.0f} 分钟,阈值 {stale_minutes}){beat}",
            ),
            None,
        )

    head = (
        f"游标停在 {_iso(newest)}(落后 {lag_min:.0f} 分钟,阈值 {stale_minutes};"
        f"最新一条是 {newest_key}){beat}"
    )
    notifications, error = loader()
    if error:
        # 判不出来也绝不能算正常:游标已经落后,只是我们不知道有没有活要干。
        return (
            Check(CURSOR_CHECK, BAD, f"{head} · 取不到未读通知:{error}"),
            f"{CURSOR_CHECK}:取不到未读通知({error})",
        )

    pending: List[Dict[str, Any]] = []
    for item in notifications:
        updated = _parse_ts(item.get("updated_at"))
        # 解析不出时间时按「有活」处理:宁可多报一次,也别把一个真停摆吞掉。
        if updated is None or updated > newest:
            pending.append(item)
    if not pending:
        return (
            Check(
                CURSOR_CHECK,
                OK,
                f"{head} · 没有比游标更新的未读通知(闲置时段游标不动是正常的)",
            ),
            None,
        )
    titles = " | ".join(_describe_notification(item) for item in pending[:3])
    more = f" 等 {len(pending)} 条" if len(pending) > 3 else ""
    return (
        Check(
            CURSOR_CHECK,
            BAD,
            f"{head} · 有未读且比游标新 {len(pending)} 条:{titles}{more}",
        ),
        None,
    )


def open_db(path: str) -> sqlite3.Connection:
    """只读打开 orchestrator 状态库。

    Args:
        path: sqlite 文件路径。

    Returns:
        连接对象。

    Raises:
        sqlite3.Error: 打不开或不是预期库。
    """
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def load_tickets(conn: sqlite3.Connection) -> List[Tuple[str, Dict[str, Any]]]:
    """读出全部 ticket 并解析 JSON(坏行跳过,不让它打断整轮巡检)。

    Args:
        conn: orchestrator 状态库连接。

    Returns:
        `(ticket_id, 解析后的字典)` 列表。
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

    Args:
        data: 解析后的 ticket 字典。

    Returns:
        编号;取不到返回 None。

    这里刻意**不用** SQL 的 LIKE 匹配原始 JSON:同一份 JSON 紧凑/带空格的写法都出现过,
    按字符串匹配会静默漏行(自测就是这么抓到 `"number": 285` 带空格时判成 0 张单)。
    """
    scope = ((data.get("mandate") or {}).get("basis") or {}).get("scope") or {}
    number = scope.get("number")
    try:
        return int(number)
    except (TypeError, ValueError):
        return None


def check_enqueue(conn: sqlite3.Connection, issue: int) -> Check:
    """入队三连:thread / trigger_thread / ticket 三张表都要有该 issue 的记录。

    Args:
        conn: orchestrator 状态库连接。
        issue: GitHub issue 编号。

    Returns:
        一条检查结果;任何一张表缺记录都算异常(评论可能压根没进队列)。
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

    Args:
        conn: orchestrator 状态库连接。
        now: 当前时间(测试可注入)。
        threshold_minutes: 超过多少分钟没结束就算卡住。

    Returns:
        每个卡住的 assignment 一条 `bad` 检查(没有则返回空列表)。
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

    Args:
        conn: orchestrator 状态库连接。
        workdir: work/ 目录。

    Returns:
        目录数量超过活跃 assignment 时给一条 `ok` 但信息完整的检查。
    """
    try:
        dirs = sorted(name for name in os.listdir(workdir) if os.path.isdir(os.path.join(workdir, name)))
    except OSError:
        return [Check("worktrees", OK, "work/ 不存在或读不到")]
    return [Check("worktrees", OK, f"{len(dirs)} 个目录: {', '.join(dirs) or '(空)'}")]


def build_report(args: argparse.Namespace, now: Optional[datetime] = None) -> Report:
    """跑完整一轮巡检。

    Args:
        args: 已解析的命令行参数。
        now: 当前时间(测试注入用),默认取 UTC now。

    Returns:
        巡检结果。
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
        if not args.skip_cursor:
            check, unknown = check_cursor(
                conn, now, args.cursor_stale_minutes, _notification_loader(args)
            )
            report.add(check)
            if unknown:
                report.unknown.append(unknown)
        for check in check_worktrees(conn, args.workdir):
            report.add(check)
    return report


def _notification_loader(
    args: argparse.Namespace,
) -> Callable[[], Tuple[List[Dict[str, Any]], Optional[str]]]:
    """按命令行参数给出「取未读通知」的函数(文件注入优先,否则走 gh)。

    Args:
        args: 已解析的命令行参数。

    Returns:
        一个无参函数,返回 `(通知列表, 失败原因)`。文件注入让自测与反证完全离线。
    """
    if args.notifications_file:
        path = args.notifications_file
        return lambda: load_notifications_file(path)
    return lambda: fetch_notifications(args.gh_cli, args.proxy)


def _acknowledge(check: Check, ignore: List[str]) -> Check:
    """把人工确认作废的僵尸 assignment 从「异常」降级成「已确认」。

    Args:
        check: 一条检查结果(名字形如 `僵尸 assignment ce1d46c9`)。
        ignore: 已人工确认作废的 assignment id 前缀列表。

    Returns:
        命中则返回 `ok` 版本(说明里保留原始信息),否则原样返回。

    为什么需要它:DSH 没有「取消 assignment」的 CLI/API,一个被模型流打断的 assignment 会
    永远停在 `running`。留着不管就是每 6 小时一条告警,而删库改状态风险更大 ——
    所以给运营一个显式的确认口,而不是让告警被噪音化(那比没有告警更糟)。
    """
    if not ignore:
        return check
    for prefix in ignore:
        if prefix and prefix in check.name:
            return Check(check.name, OK, f"已人工确认作废({prefix}) · 原始:{check.detail}")
    return check


def render_text(report: Report) -> str:
    """把巡检结果渲染成给人看的几行。

    Args:
        report: 巡检结果。

    Returns:
        多行文本,最后一行是总体结论。
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


def _env_int(name: str, default: int) -> int:
    """读整数环境变量,坏值/空值退回默认(巡检不能因为一个手误的配置就崩)。

    Args:
        name: 环境变量名。
        default: 读不到或不是整数时用的默认值。

    Returns:
        整数阈值。
    """
    try:
        return int(str(os.environ.get(name, "")).strip())
    except (TypeError, ValueError):
        return default


def build_parser() -> argparse.ArgumentParser:
    """构造命令行解析器。"""
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
        "--cursor-stale-minutes",
        type=int,
        default=_env_int("SUPERAGENT_CURSOR_STALE_MINUTES", DEFAULT_CURSOR_STALE_MINUTES),
        help="游标落后多少分钟才值得深究(默认 10;设 0 = 任何游标都算落后,反证用)",
    )
    parser.add_argument(
        "--gh-cli",
        default=os.environ.get("GH_CLI") or None,
        help="取未读通知用的 GitHub CLI(默认依次试 GH_CLI / gh / gh-agent)",
    )
    parser.add_argument(
        "--notifications-file",
        default=None,
        help="用本地 JSON 冒充未读通知(自测 / 反证,不联网)",
    )
    parser.add_argument("--skip-cursor", action="store_true", help="跳过游标新鲜度检查")
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
    """入口:跑巡检、打印、按契约返回退出码。"""
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
