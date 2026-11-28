#!/usr/bin/env python3
"""superagent worker 健康检查:出网、入队三连、僵尸 assignment、轮询游标新鲜度、CI 红轨。

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

判定本身是只读的。**重启是另一件事,默认不做**:只有显式打开 `SUPERAGENT_AUTOREHEAL=1`
(默认 `0` = 关)且第四项判成停摆时,才去问「安全自愈」那四道闸 —— 有 `running` / `pending`
的 assignment、有 worktree 没提交、距上次自愈不足最小间隔、或者压根确认不了干净与否,
任何一条命中就**只告警、绝不重启**。闸的顺序写在 `maybe_autoreheal` 里,是安全契约,别优化掉。
取证与根因见 `docs/ops/superagent.md` §15 与 PR 正文。

第五项(2026-11-16 并入):**默认分支的 CI 红轨**。此前这件事由 `.github/workflows/main-health.yml`
每天建一条 GitHub issue 来承载,而 issue 是「待办」不是「告警」:没人订阅就没人看见,还要人
手动关。现在改成与 worker 巡检同一个出口(邮件),判据仍然复用同一份实现
(`scripts/lib/ci_red.py`,L4 与巡检都从它取),不再各写一份。
代价是已知偏差:**WSL 关机期间没人报红轨**,
与「worker 也不在」是同一段时间,开机后第一轮(`OnBootSec`)会立刻补报。

第六项(2026-11-17 并入,输出里紧跟在「出网 / 出口节点」之后):**WSL 继承到的
`http(s)_proxy` 是不是指向一个死端口**。mirrored 网络模式下 WSL 的 `autoProxy`(默认开)会把
Windows 的系统代理导进**它派生的每一个进程**的环境里 —— 包括 `wsl -e bash -c '…'` 起的
非登录 shell(2026-11-17 实测 `echo $https_proxy` → `http://127.0.0.1:7897`)。Clash 开着时
一切正常,Clash 一关,那些命令就**静默挂住**:没有报错、没有退出码,看起来像卡死。这单的价值
就是把这种「潜伏态」变成可见:继承值非空且**不是 worker 自己 export 的那个**(判据与盲区写在
`check_proxy_inherit` 的 docstring 里),就对它的 `host:port` 建一次 TCP 连接 —— 通 = 绿但文案
写明潜伏态,不通 = 红并指向 `.wslconfig` 的 `autoProxy=false`。
根治动作在 Windows 侧(`.wslconfig` + `wsl --shutdown`),巡检只负责让它可见。

退出码
------
0 = 全部正常;1 = 有异常(该发告警);2 = 判不出来(同样该发告警,但绝不能当成正常)。

用法
----
    python3 healthcheck.py                      # 人类可读摘要
    python3 healthcheck.py --json               # 机器可读
    python3 healthcheck.py --issue 285 --issue 280
    python3 healthcheck.py --skip-egress        # 离线/自测(连带跳过第六项)
    python3 healthcheck.py --skip-proxy-inherit # 只跳过第六项
    python3 healthcheck.py --skip-cursor        # 不查游标(完全离线)
    python3 healthcheck.py --notifications-file n.json   # 用本地 JSON 冒充未读通知
    python3 healthcheck.py --autoreheal 1       # 打开安全自愈(默认 0 = 关)
    python3 healthcheck.py --ci-red 1 --runs-file runs.json   # 打开 CI 红轨(默认关)
"""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Tuple

# `python3 scripts/superagent_health.py` 时 sys.path[0] 是 scripts/,而
# `python3 -m unittest scripts.test_superagent_health` 时仓库根已在 sys.path 里。
# 显式补一次,让 `from scripts...` 在两种调用方式下都成立
# (与 `scripts/lib/__init__.py` 里写下的约定是同一段样板)。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# CI 红轨的判定口径在 `scripts/lib/ci_red.py`(**唯一一份**,L4 自动入队也用它)。
# 但巡检器是**自包含安装**的:`install.sh` 把它与 `ci_red.py` 并排拷到
# `/root/.dsh/healthcheck/`,那时仓库不在 `sys.path` 里,`from scripts...` 必然失败 ——
# 2026-11-17 实测过这一版:整轮巡检 `ModuleNotFoundError`,只剩一条空告警发出去。
# 所以仓库布局与安装布局各一条导入路径,两种都能跑。
try:  # 仓库内 / unittest
    from scripts.lib import ci_red
except ImportError:  # 安装布局:与 superagent_health.py 同级
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import ci_red  # type: ignore[no-redef]

DEFAULT_DB = "/root/.dsh/state/superagent/orchestrator.sqlite"
DEFAULT_WORK = "/root/.dsh/state/superagent/work"
DEFAULT_PROXY = "http://127.0.0.1:7890"
DEFAULT_PROXY_CONFIG = "/root/.dsh/proxy/config.yaml"
DEFAULT_TOKEN = "/root/.dsh/github-mcp-token.txt"
# 仓库 slug 写一份字面量而不是 import `scripts.lib.repo`:同样是安装布局的问题
# (那个包在 `/root/.dsh/healthcheck/` 里不存在)。它可被 `--repo` / `SUPERAGENT_HEALTH_REPO`
# 覆盖,而 lib 那边防的是「四个发版脚本各抄一份」,与本文件的用途不重叠。
DEFAULT_REPO = "shiliu153/chatapp"
DEFAULT_BRANCH = "main"
EGRESS_URL = "https://api.github.com/rate_limit"

#: worker 自己的出口口径,逐字抄 `/root/start-superagent.sh` 的 `no_proxy`:**模型网关走直连,
#: 其余(含 GitHub 各域)走 mihomo**。巡检里的 `gh` 调用必须与它同口径,否则量到的是
#: 「巡检这台的网」而不是 worker 的网 —— 直连断了巡检全绿(盲区),机场抽风巡检报红而 worker
#: 其实没事(2026-11-25 16:15 / 16:30 各误报过一次)。口径漂移由
#: `test_worker_no_proxy_covers_github_hosts` 兜住。
#:
#: 2026-11-28 口径翻转:GitHub 那一组域**不再**划进直连(WSL 内直连 443 已不通),
#: 与其余外网同路走 mihomo。回滚 = 把五个 GitHub 域加回来,且必须同改
#: `scripts/superagent-start/start-superagent.sh`(门禁会红)。
WORKER_NO_PROXY = (
    "localhost,127.0.0.1,::1,"
    "wb.shiliu153.me"
)
NOTIFICATIONS_PATH = "notifications?all=false&per_page=50"
CI_RUNS_PATH = "repos/{repo}/actions/runs?branch={branch}&event=push&per_page=100"
DEFAULT_CURSOR_STALE_MINUTES = 10
GH_CLI_CANDIDATES = ("/root/.dsh/bin/gh-agent", "/root/.local/bin/gh-agent")
DEFAULT_AUTOREHEAL_MIN_MINUTES = 20
DEFAULT_AUTOREHEAL_STATE_DIR = "/root/.dsh/state/superagent-health"
DEFAULT_RESTART_SCRIPT = "/root/start-superagent.sh"
AUTOREHEAL_LOG = "autoreheal.log"
AUTOREHEAL_STAMP = "last-autoreheal"
TRUTHY = ("1", "on", "true", "yes", "y")

OK = "ok"
BAD = "bad"

CURSOR_CHECK = "游标新鲜度"
AUTOREHEAL_CHECK = "安全自愈"
CI_RED_CHECK = "CI 红轨"
PROXY_INHERIT_CHECK = "WSL 继承代理"
# 只看这四个变量:curl / git / npm / gh 认的就是它们(小写是事实标准,大写是历史写法,
# Windows 侧导进来的两套都有)。`ALL_PROXY` 故意不看 —— 本机没有任何组件导出它,
# 而镜像进来时它通常跟着 http(s)_proxy 一起,少一个变量不改变结论。
INHERIT_PROXY_VARS = ("https_proxy", "HTTPS_PROXY", "http_proxy", "HTTP_PROXY")
# 代理 URL 没写端口时的默认值(与 curl 的口径一致)。socks 系列同样支持,虽然本机用不到。
PROXY_DEFAULT_PORTS = {
    "http": 80,
    "https": 443,
    "socks": 1080,
    "socks4": 1080,
    "socks5": 1080,
    "socks5h": 1080,
}


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


@contextlib.contextmanager
def _proxy_bypass_disabled() -> Iterator[None]:
    """临时摘掉 ``no_proxy``,让显式指定的代理真的被用上。

    参数说明:
        无。

    返回参数:
        不返回;退出上下文时把 ``no_proxy`` / ``NO_PROXY`` 原样放回去。

    使用示例:
        >>> with _proxy_bypass_disabled():
        ...     check_egress("http://127.0.0.1:7890", None)

    备注信息:
        ``urllib.request.ProxyHandler.proxy_open`` 在发请求前会问 ``proxy_bypass(host)``,
        而它读的正是环境里的 ``no_proxy``。**2026-11-28 起 worker 的 no_proxy 已经不含
        GitHub 各域**(那一组改走 mihomo),所以「经代理探 api.github.com」现在本来就量到代理;
        本函数留着当保险 —— 万一哪天 ``no_proxy`` 又把 GitHub 划回直连,这道摘除保证探针
        仍然量的是代理那条腿,而不是静默退化成直连(2026-11-28 复现过:巡检自测
        ``test_dead_proxy_reports_bad_without_raising`` 对着死端口 ``127.0.0.1:9`` 仍判绿)。
        只摘 ``no_proxy`` 就够了:``http_proxy`` 决定「用哪个代理」,``no_proxy`` 决定
        「哪些不走代理」,后者才是这里要绕开的。
    """
    saved = {
        name: os.environ.pop(name)
        for name in ("no_proxy", "NO_PROXY")
        if name in os.environ
    }
    try:
        yield
    finally:
        os.environ.update(saved)


def _probe(
    url: str, token: Optional[str], timeout: float, proxy: Optional[str]
) -> Tuple[Optional[int], Optional[str], float]:
    """发一次 GET,把「拿到什么状态码 / 为什么失败 / 用了多久」摊平返回。

    参数说明:
        url: 要访问的地址。
        token: GitHub token;给了就带上,避免匿名限流把「通」误判成「不通」。
        timeout: 单次超时秒数。
        proxy: 代理 URL;``None`` 表示**强制直连**(不看代理,也不理 ``http_proxy``)。

    返回参数:
        ``(状态码, 失败说明, 耗时秒)``。失败说明为 ``None`` 表示请求跑完了
        (状态码仍可能不是 2xx);耗时在失败时为 ``0.0``。

    使用示例:
        >>> _probe(EGRESS_URL, None, 5, DEFAULT_PROXY)
        (200, None, 0.412)

    备注信息:
        直连那一支用 ``ProxyHandler({})``:传 ``None`` 是「让 urllib 自己去读环境变量」,
        那不是直连,而是「读到一个什么是什么」—— 巡检最不能犯的错就是量错对象。
    """
    if proxy:
        opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )
    else:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, headers={"User-Agent": "superagent-health"})
    if token:
        request.add_header("Authorization", "Bearer " + token)
    started = datetime.now(timezone.utc)
    try:
        with _proxy_bypass_disabled() if proxy else contextlib.nullcontext():
            with opener.open(request, timeout=timeout) as resp:
                status = resp.status
    except urllib.error.HTTPError as exc:
        return exc.code, f"HTTP {exc.code}:链路通但接口报错", 0.0
    except Exception as exc:  # noqa: BLE001 - 任何异常都是「出网不通」
        return None, f"{type(exc).__name__}: {exc}", 0.0
    return status, None, (datetime.now(timezone.utc) - started).total_seconds()


def check_egress(
    proxy: str, token: Optional[str], timeout: float = 15.0, url: str = EGRESS_URL
) -> Check:
    """经**代理**访问一次 GitHub API:量的是 mihomo 那条腿。

    参数说明:
        proxy: 出口代理 URL(如 ``http://127.0.0.1:7890``)。
        token: GitHub token;给了就带上,避免匿名限流误判。
        timeout: 单次超时秒数。
        url: 探针地址,默认 :data:`EGRESS_URL`;自测用本机监听套接字换掉它。

    返回参数:
        一条检查结果:``ok`` 表示经代理真的拿到 2xx。

    使用示例:
        >>> check_egress("http://127.0.0.1:7890", None).state
        'ok'

    备注信息:
        探针主机是 ``api.github.com``。2026-11-28 起 worker 的 ``no_proxy`` 不再把 GitHub
        划进直连,所以这一项量到的**就是** worker 真正走的代理那条腿(``_proxy_bypass_disabled``
        仍然兜着:万一 no_proxy 又被改回直连,它保证这里量的还是代理)。直连那条腿由
        :func:`check_egress_direct` 单独量,但**已不进巡检报告** —— 它不是 worker 的路径。
    """
    status, error, elapsed = _probe(url, token, timeout, proxy)
    name = "出网(经代理 api.github.com)"
    if error:
        return Check(name, BAD, error)
    if status is None or not 200 <= status < 300:
        return Check(name, BAD, f"HTTP {status}")
    return Check(name, OK, f"HTTP {status} · {elapsed:.1f}s")


def check_egress_direct(
    token: Optional[str], timeout: float = 15.0, url: str = EGRESS_URL
) -> Check:
    """**不经任何代理**访问一次 GitHub API:量的是直连那条腿。

    参数说明:
        token: GitHub token;给了就带上,避免匿名限流误判。
        timeout: 单次超时秒数。
        url: 探针地址,默认 :data:`EGRESS_URL`;自测用本机监听套接字换掉它。

    返回参数:
        一条检查结果:``ok`` 表示直连真的拿到 2xx。

    使用示例:
        >>> check_egress_direct(None).state
        'ok'

    备注信息:
        **2026-11-28 起这条腿已不进巡检报告**(不进 :func:`run_checks`):worker 的出口口径
        改成「GitHub 也走 mihomo」之后,直连不是 worker 的路径,把它当必检项等于拿一条
        没人走的路报红 —— 而本机直连现在确实不通,那会变成永久假红,人只会把巡检关掉。
        函数保留,供人工排障时回答「直连那条路回来了没有」(历史上它比机场快一倍,
        真回来了就值得切回去,见 `docs/ops/superagent.md` §12.1)。
    """
    status, error, elapsed = _probe(url, token, timeout, None)
    name = "出网(直连 api.github.com)"
    if error:
        return Check(name, BAD, error)
    if status is None or not 200 <= status < 300:
        return Check(name, BAD, f"HTTP {status}")
    return Check(name, OK, f"HTTP {status} · {elapsed:.1f}s")


def worker_gh_env(proxy: str) -> Dict[str, str]:
    """按 worker 的出口口径构造 ``gh`` 子进程的环境。

    参数说明:
        proxy: 出口代理 URL;非 GitHub 域走它。

    返回参数:
        可直接传给 ``subprocess.run(env=...)`` 的完整环境字典。

    使用示例:
        >>> env = worker_gh_env(DEFAULT_PROXY); env["no_proxy"] == WORKER_NO_PROXY
        True

    备注信息:
        巡检原来是「代理变量设成 mihomo、``no_proxy`` 原样继承」,而继承来的 ``no_proxy``
        取决于巡检怎么被拉起(systemd / 交互 shell / CI 各不相同),于是同一个脚本在不同
        调用方式下量到的网不一样。现在两处 ``gh`` 调用统一走这里:``no_proxy`` 显式写成
        worker 的那一份(:data:`WORKER_NO_PROXY`),代理变量显式指向 mihomo。
    """
    env = dict(os.environ)
    env.update(
        {"HTTPS_PROXY": proxy, "HTTP_PROXY": proxy, "https_proxy": proxy, "http_proxy": proxy}
    )
    env.update({"NO_PROXY": WORKER_NO_PROXY, "no_proxy": WORKER_NO_PROXY})
    return env


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


def parse_proxy_target(value: str) -> Optional[Tuple[str, int]]:
    """把代理变量里的值解析成 `(主机, 端口)`,看不懂就返回 None。

    Args:
        value: `https_proxy` / `HTTPS_PROXY` 里的原始字符串,如 `http://127.0.0.1:7897`。

    Returns:
        `(host, port)`;值是空的、缺主机名、端口不是数字时返回 None。

    三种写法都认:`http://host:port`(标准)、`host:port`(curl 也接受这种裸写法,Windows
    那边导过来的值有可能是它)、`socks5://host:port`。没写端口时按 scheme 的默认端口补
    (`http` → 80、`https` → 443、socks 系列 → 1080),与 curl 一致 —— 拿 80 去探一次
    总比「解析失败所以跳过」安全:解析失败等于把这一项判成正常。
    """
    raw = (value or "").strip()
    if not raw:
        return None
    if "://" not in raw:
        raw = "http://" + raw
    try:
        parts = urllib.parse.urlsplit(raw)
        host = parts.hostname
        port = parts.port
    except ValueError:  # 非法端口(如 `http://127.0.0.1:db`)在 .port 上抛 ValueError
        return None
    if not host:
        return None
    if port is None:
        port = PROXY_DEFAULT_PORTS.get((parts.scheme or "http").lower())
    if not port:
        return None
    return host, int(port)


def _is_loopback_host(host: str) -> bool:
    """判断主机名是不是回环地址(127.0.0.0/8、::1、localhost)。

    Args:
        host: 主机名或 IP 字面量。

    Returns:
        是否算回环。

    只用于告警文案里区分「继承来的是回环地址(autoProxy 的典型形态,端口一关就死)」还是
    「继承来的是别的地址」—— **不参与判定**,判定只认连通探针。
    """
    lowered = host.strip().strip("[]").lower()
    if lowered == "localhost" or lowered.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(lowered).is_loopback
    except ValueError:
        return False


def probe_tcp(host: str, port: int, timeout: float = 3.0) -> Tuple[bool, str]:
    """对 `host:port` 做一次真实 TCP 连通探针(不联网、不走代理、只建连)。

    Args:
        host: 目标主机(通常是 `127.0.0.1`)。
        port: 目标端口。
        timeout: 单次连接超时秒数(默认 3 秒,见巡检口径)。

    Returns:
        `(是否连通, 一句话旁证)`:连通给耗时、不通给异常类名。

    为什么不做 HTTP 请求:`https_proxy` 指向的是一个**代理端口**,对它发 HTTP 请求既可能
    被当成 CONNECT 目标(回 400)也可能被当成普通请求(回 403),两种都不代表端口死了。
    「能建 TCP 连接」才是「这个端口上真有东西在听」的判据。
    """
    started = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, f"{time.monotonic() - started:.2f}s"
    except OSError as exc:  # 含 socket.timeout / ConnectionRefusedError / 名字解析失败
        return False, type(exc).__name__


def _norm_proxy(value: str) -> str:
    """把代理值归一成「能比对」的形状(去空白、去尾斜杠、小写)。

    Args:
        value: 原始代理值。

    Returns:
        归一后的字符串。
    """
    return (value or "").strip().rstrip("/").lower()


def check_proxy_inherit(
    environ: Mapping[str, str],
    own_proxy: str,
    timeout: float = 3.0,
    probe: Optional[Callable[[str, int, float], Tuple[bool, str]]] = None,
) -> Check:
    """第六项:WSL **继承到的** `http(s)_proxy` 是不是指向一个死端口。

    Args:
        environ: 环境变量视图(`os.environ` 或自测注入的字典)。
        own_proxy: worker **自己** export 的代理(`start-superagent.sh` 的出口,即 `--proxy`)。
        timeout: 探针超时秒数(默认 3 秒)。
        probe: 探针实现(自测注入用),`None` = 用 `probe_tcp`。

    Returns:
        一条检查结果:继承值连不上 → `bad`;没继承 / 连得上 / 只有自 export → `ok`。

    **判定口径(这是本项的契约,别按直觉改)**:

    1. 只看**进程环境里的** `https_proxy` / `HTTPS_PROXY` / `http_proxy` / `HTTP_PROXY`。
       这就是「WSL 继承到的值」唯一可观测的形态:WSL(mirrored 模式,`autoProxy` 默认开)
       会把 Windows 的系统代理塞进**它派生的每一个进程**的环境里,`wsl -e bash -c '…'`
       起的非登录 shell 一样带(2026-11-17 实测:`http://127.0.0.1:7897`)。
       登录 shell 里 `/etc/profile.d/00-wsl-proxy.sh` 还会自己导一份,那条路的探针目标
       是宿主网关的 7897,不通常常不生效,但它导出来的也会落进同一个变量,口径不变。
    2. **先排除 worker 自 export 的那个值**:`start-superagent.sh` 无条件
       `export http(s)_proxy=$PROXY`(默认 mihomo `127.0.0.1:7890`),worker 会话里这四个
       变量本来就有值。所以「变量非空」不等于「被继承」,必须与该值(归一后)相等即跳过 ——
       否则巡检在**一切正常**时天天报红,那比没有这一项更糟。
       已知盲区:如果 Windows 系统代理**恰好**也是同一个地址(镜像模式下两边共用 127.0.0.1
       时理论上可能),会被当成自 export 而漏报。那种情况探针本来就是通的,漏报的代价仅是
       少一句「潜伏态」提示,不会造成假红。
    3. **判定只认连通探针**:非空且不是自 export 的值 → 对它的 `host:port` 建一次 TCP 连接
       (默认 3 秒超时)。不通 = 红,通 = 绿但文案写明「潜伏态」(代理一关就挂)。
       量级上的取舍:此刻能连说明「Clash 正开着」,故障是潜伏的,**不该报红**;
       但也不能沉默 —— 沉默正是这单要修的东西(见 `docs/ops/superagent.md` §15)。
    4. 值不是可解析的代理地址时也报红:那种值对 curl/git 来说同样是错的,而且不会自己好。
    """
    probe = probe or probe_tcp
    inherited: List[Tuple[str, str]] = []
    for var in INHERIT_PROXY_VARS:
        raw = (environ.get(var) or "").strip()
        if not raw or _norm_proxy(raw) == _norm_proxy(own_proxy):
            continue
        if all(raw != seen for _var, seen in inherited):
            inherited.append((var, raw))
    own_note = f";已排除自 export 的 {own_proxy}" if own_proxy else ""
    if not inherited:
        return Check(
            PROXY_INHERIT_CHECK,
            OK,
            f"未继承 http(s)_proxy(空值或只有 worker 自 export 的 {own_proxy or '(无)'})",
        )

    alive: List[str] = []
    for var, raw in inherited:
        target = parse_proxy_target(raw)
        if target is None:
            return Check(
                PROXY_INHERIT_CHECK,
                BAD,
                f"{var}={raw} 不是可解析的代理地址 · 继承来的值对 curl/git 一样是错的,"
                f"`wsl -e bash -c` 的联网命令会直接失败 → 先 unset,再按 .wslconfig "
                f"加 autoProxy=false 后 wsl --shutdown 根治{own_note}",
            )
        host, port = target
        connected, note = probe(host, port, timeout)
        where = "回环地址" if _is_loopback_host(host) else "非回环地址"
        if not connected:
            return Check(
                PROXY_INHERIT_CHECK,
                BAD,
                f"{var}={raw} 连不上({note},{where}) · WSL 继承到的代理指向死端口"
                f"(mirrored 模式的 autoProxy 把 Windows 系统代理导进了 WSL),"
                f"`wsl -e bash -c` 的联网命令会静默挂住 → .wslconfig 加 autoProxy=false "
                f"后 wsl --shutdown{own_note}",
            )
        alive.append(f"{var}={raw} 可连({note},{where})")
    return Check(
        PROXY_INHERIT_CHECK,
        OK,
        " · ".join(alive)
        + f" · 潜伏态:代理一关,`wsl -e bash -c` 的联网命令就静默挂住 → .wslconfig 加 "
        f"autoProxy=false 后 wsl --shutdown{own_note}",
    )


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
    env = worker_gh_env(proxy)
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


def fetch_ci_runs(
    gh_cli: Optional[str],
    proxy: str,
    repo: str = DEFAULT_REPO,
    branch: str = DEFAULT_BRANCH,
    timeout: float = 25.0,
) -> Tuple[Any, Optional[str]]:
    """调 `gh api .../actions/runs` 取默认分支的 push run 快照(第五项的事实源)。

    Args:
        gh_cli: GitHub CLI 路径;None 表示自动探测。
        proxy: 出口代理 URL;国内直连 GitHub 不通,必须走它。
        repo: `owner/name`,默认本仓库。
        branch: 默认分支名(2026-11-11 改过名,写死会静默失效,所以可配)。
        timeout: 子进程超时秒数。

    Returns:
        `(runs 快照, 失败原因)`。取不到时不抛异常 —— 由调用方报成「判不出来」。

    为什么要跟 `fetch_notifications` 一样走 `gh api`:token 与代理配置都在 gh 那边,
    systemd 里再抄一份凭据只是多一处会漂移的东西。
    """
    binary = find_gh_cli(gh_cli)
    if not binary:
        return None, "找不到 GitHub CLI(gh / gh-agent)"
    path = CI_RUNS_PATH.format(repo=repo, branch=branch)
    env = worker_gh_env(proxy)
    try:
        done = subprocess.run(
            [binary, "api", path], capture_output=True, text=True, timeout=timeout, env=env
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    if done.returncode != 0:
        reason = (done.stderr or done.stdout or "").strip().splitlines()
        return None, f"{binary} api actions/runs 退出码 {done.returncode}:{reason[-1] if reason else '(无输出)'}"
    try:
        return json.loads(done.stdout or "{}"), None
    except ValueError as exc:
        return None, f"runs 响应不是 JSON:{exc}"


def load_runs_file(path: str) -> Tuple[Any, Optional[str]]:
    """读本地 JSON 冒充 runs 快照(自测与反证用,完全不联网)。

    Args:
        path: 快照文件路径。

    Returns:
        `(runs 快照, 失败原因)`。
    """
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle), None
    except (OSError, ValueError) as exc:
        return None, f"读不到 runs 快照 {path}:{exc}"


def ci_red_checks(loader: Callable[[], Tuple[Any, Optional[str]]]) -> Tuple[List[Check], Optional[str]]:
    """第五项巡检:默认分支上有没有 workflow 的最新一次 push run 是红的。

    Args:
        loader: 取 runs 快照的函数,返回 `(快照, 失败原因)`。

    Returns:
        `(检查结果列表, 判不出来的原因)`。全绿时给一条 `ok`;有红轨时**每条红轨一个
        Check**,名字里带 workflow 名 —— 这样 `run.sh` 的指纹(检查名+状态)才能区分
        「web 红了」与「imserver 红了」,新红一条不会因为旧红还在而被去重吞掉。

    判据复用 `scripts/lib/ci_red.py::red_runs`(与 L4 自动入队同一份实现):
    `cancelled` / `timed_out` / `startup_failure` 这些「没跑绿」都算红,只认 `failure`
    会把五种红静默当绿。这里**不**自己写第二份判定。
    """
    payload, error = loader()
    if error:
        return (
            [Check(CI_RED_CHECK, BAD, f"取不到默认分支的 run 快照:{error}")],
            f"{CI_RED_CHECK}:取不到 run 快照({error})",
        )
    try:
        red = ci_red.red_runs(payload)
        latest = ci_red.latest_runs_by_workflow(payload)
    except ValueError as exc:
        return (
            [Check(CI_RED_CHECK, BAD, f"run 快照形状不对:{exc}")],
            f"{CI_RED_CHECK}:run 快照形状不对({exc})",
        )
    if not red:
        return [Check(CI_RED_CHECK, OK, f"{len(latest)} 条 workflow 的最新 push run 均绿")], None

    checks: List[Check] = []
    for run in red:
        name = str(run.get("name") or "(无名 workflow)")
        sha = "".join(ch for ch in str(run.get("head_sha") or "") if ch.isalnum())[:7]
        checks.append(
            Check(
                f"{CI_RED_CHECK} {name}",
                BAD,
                f"结论 {run.get('conclusion')} · {sha or '(无 sha)'} · {run.get('html_url') or '(无链接)'}",
            )
        )
    return checks, None


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


def active_assignments(conn: sqlite3.Connection) -> List[str]:
    """列出状态还是 `running` / `pending` 的 assignment —— 它们是「重启会杀掉的活」。

    Args:
        conn: orchestrator 状态库连接。

    Returns:
        每项形如 `ce1d46c9(running) @ '工单标题'`;没有活跃 assignment 时返回空列表。

    这里**不按时间过滤**(与 `zombie_assignments` 不同):僵尸判据是「卡了多久」,而自愈的判据是
    「有没有会话在跑」—— 一个刚开 8 分钟的正常会话同样是活,重启一样会把它打断。
    """
    out: List[str] = []
    for _ticket_id, data in load_tickets(conn):
        for assignment in data.get("assignments") or []:
            state = assignment.get("state")
            if state in ("running", "pending"):
                out.append(f"{str(assignment.get('id'))[:8]}({state}) @ {data.get('title')!r}")
    return out


def dirty_worktrees(workdir: str) -> Tuple[List[str], Optional[str]]:
    """看 `work/` 下每个 worktree 有没有未提交改动(`git status --porcelain` 非空)。

    Args:
        workdir: orchestrator 的 work/ 目录(每个子目录是一个 worktree)。

    Returns:
        `(有改动的目录名列表, 判不出来的原因)`。原因非空表示**确认不了干净**,
        调用方必须按「不许重启」处理(fail-closed):判不出来的干净等于不干净。

    `work/` 不存在 = 没有 worktree = 没有活,按干净处理;`git status` 失败(不是 git 目录、
    git 缺失、超时)一律算判不出来,而不是猜「大概没改动」。
    """
    try:
        names = sorted(
            name for name in os.listdir(workdir) if os.path.isdir(os.path.join(workdir, name))
        )
    except FileNotFoundError:
        return [], None
    except OSError as exc:
        return [], f"读不到 {workdir}:{type(exc).__name__}: {exc}"
    dirty: List[str] = []
    for name in names:
        path = os.path.join(workdir, name)
        try:
            done = subprocess.run(
                ["git", "-C", path, "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return [], f"跑不了 git status({path}):{type(exc).__name__}: {exc}"
        if done.returncode != 0:
            tail = (done.stderr or done.stdout or "").strip().splitlines()
            return [], f"git status 失败({path},退出码 {done.returncode}):{tail[-1] if tail else '(无输出)'}"
        if done.stdout.strip():
            dirty.append(name)
    return dirty, None


def read_last_autoreheal(state_dir: str) -> Optional[datetime]:
    """读上一次自动自愈**尝试**的时间(防抖用)。

    Args:
        state_dir: 运行时状态目录(`/root/.dsh/state/superagent-health`)。

    Returns:
        上一次尝试的时间;文件不存在或读不出来返回 None(= 从未自愈过)。

    失败也记时间:重启命令自己挂掉时进程通常仍停摆,不记就会每 15 分钟锤一次。
    """
    try:
        with open(os.path.join(state_dir, AUTOREHEAL_STAMP), "r", encoding="utf-8") as handle:
            raw = handle.read().strip()
    except OSError:
        return None
    return _parse_ts(raw)


def _write_last_autoreheal(state_dir: str, now: datetime) -> Optional[str]:
    """把「刚刚尝试过自愈」的时刻写进状态目录(成败都写)。

    Args:
        state_dir: 运行时状态目录。
        now: 尝试时间。

    Returns:
        写入失败的原因;成功返回 None。

    写不进去不是致命错误,但必须让告警看得见:防抖失效意味着下一轮可能又重启一次。
    """
    try:
        os.makedirs(state_dir, exist_ok=True)
        with open(os.path.join(state_dir, AUTOREHEAL_STAMP), "w", encoding="utf-8") as handle:
            handle.write(_iso(now) + "\n")
    except OSError as exc:
        return f"写不了 {os.path.join(state_dir, AUTOREHEAL_STAMP)}:{type(exc).__name__}: {exc}"
    return None


def append_autoreheal_log(state_dir: str, line: str) -> Optional[str]:
    """把一次自愈尝试追加进 `autoreheal.log`(时间 / 触发原因 / 前后游标 / 退出码)。

    Args:
        state_dir: 运行时状态目录。
        line: 已经渲染好的一行(不带换行)。

    Returns:
        写入失败的原因;成功返回 None。

    为什么单独一个日志文件而不只靠告警:告警有 6 小时去重(同一种异常只发一次),
    而「今天自愈了几次、每次结果如何」是判断要不要继续开这个开关的依据,必须一笔一笔留住。
    """
    path = os.path.join(state_dir, AUTOREHEAL_LOG)
    try:
        os.makedirs(state_dir, exist_ok=True)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:
        return f"写不了 {path}:{type(exc).__name__}: {exc}"
    return None


def default_restart(script: str = DEFAULT_RESTART_SCRIPT, timeout: float = 180.0) -> Tuple[int, str]:
    """默认的重启实现:`bash <script> restart` —— 全脚本里唯一会动到 orchestrator 进程的地方。

    Args:
        script: 启动脚本路径(默认 `/root/start-superagent.sh`)。
        timeout: 子进程超时秒数;超时按失败(退出码 124)处理。

    Returns:
        `(退出码, 输出尾部)`;**不抛异常**:重启失败要比重启本身更好定位。

    自测里**绝不许**走到这里(那会杀掉正在跑的会话,包括跑测试的自己),所以
    `maybe_autoreheal` 的回调是参数注入的,只有生产路径才用这个默认实现。
    """
    try:
        done = subprocess.run(
            ["bash", script, "restart"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return 124, f"bash {script} restart 超时(>{timeout:.0f}s)"
    except OSError as exc:
        return 127, f"{type(exc).__name__}: {exc}"
    output = ((done.stdout or "") + (done.stderr or "")).strip().replace("\n", " ")
    return done.returncode, output[-300:]


def maybe_autoreheal(
    conn: sqlite3.Connection,
    workdir: str,
    now: datetime,
    min_minutes: int,
    state_dir: str,
    cursor_detail: str,
    restart: Callable[[], Tuple[int, str]],
) -> Check:
    """安全自愈:四道闸全过才重启,任何一条不过都只告警(**顺序是安全契约,不许调整**)。

    调用前提:第四项「游标新鲜度」已经判成 `bad`(有未读通知且比游标新)。闸门顺序:

    1. 状态库里**没有** `state ∈ {running, pending}` 的 assignment —— 重启会杀掉正在跑的会话;
    2. `work/` 下每个 worktree 都没有未提交改动(`git status --porcelain` 为空)—— 有改动说明
       有人的活还没落地,重启会让他白干;确认不了干净也按「有改动」处理(fail-closed);
    3. 距上一次自愈尝试 ≥ `min_minutes`(默认 20 分钟)防抖 —— 否则巡检每 15 分钟就会重启一次;
    4. 以上全过,才调用注入的 `restart` 回调。

    Args:
        conn: orchestrator 状态库连接(只读)。
        workdir: orchestrator 的 work/ 目录。
        now: 当前时间(测试注入)。
        min_minutes: 两次自愈尝试之间的最小间隔(分钟)。
        state_dir: 运行时状态目录(防抖时间戳与 `autoreheal.log` 都落在这里)。
        cursor_detail: 第四项检查的说明原文,写进日志当「触发原因」。
        restart: 无参回调,返回 `(退出码, 输出尾部)`。自测注入假回调,生产用 `default_restart`。

    Returns:
        一条 `Check`:成功 = `ok` 且正文含「已自动重启」;回调失败 = `bad` 且带失败原因
        (调用方保证游标那项仍是 `bad`,所以退出码依旧是 1);任一闸不过 = `ok` 且写明不重启的原因。
    """
    cursors_before = read_cursors(conn)
    newest_before = max((moment for _key, moment in cursors_before), default=None)

    def _cursor_note() -> str:
        """渲染日志里的「重启前游标」,读不到就写「(读不到)」。"""
        if newest_before is None:
            return "(读不到游标)"
        lag = (now - newest_before).total_seconds() / 60.0
        return f"{_iso(newest_before)}(落后 {lag:.0f} 分钟)"

    # ① 有会话在跑 —— 一律不重启。
    active = active_assignments(conn)
    if active:
        more = f" 等 {len(active)} 个" if len(active) > 3 else ""
        return Check(
            AUTOREHEAL_CHECK,
            OK,
            f"不重启:有 {len(active)} 个 running/pending 的 assignment({'; '.join(active[:3])}{more})"
            f" —— 重启会杀掉正在跑的会话",
        )

    # ② worktree 必须全部干净;确认不了 = 不干净。
    dirty, error = dirty_worktrees(workdir)
    if error:
        return Check(AUTOREHEAL_CHECK, OK, f"不重启:确认不了 worktree 干净({error})")
    if dirty:
        more = f" 等 {len(dirty)} 个" if len(dirty) > 3 else ""
        return Check(
            AUTOREHEAL_CHECK,
            OK,
            f"不重启:{len(dirty)} 个 worktree 有未提交改动({', '.join(dirty[:3])}{more})"
            f" —— 那是还没落地的活",
        )

    # ③ 防抖:距上一次自愈尝试不足阈值就不重复重启。
    last = read_last_autoreheal(state_dir)
    if last is not None:
        waited = (now - last).total_seconds() / 60.0
        if waited < min_minutes:
            return Check(
                AUTOREHEAL_CHECK,
                OK,
                f"不重启:距上次自愈 {waited:.0f} 分钟(阈值 {min_minutes} 分钟)",
            )

    # ④ 四道闸全过:记时间戳 → 立刻重启 → 落日志。写时间戳必须**在重启之前**,
    #    否则重启把这一轮打断,下一轮就会毫无防抖地再来一次。
    stamp_error = _write_last_autoreheal(state_dir, now)
    returncode, output = restart()
    cursors_after = read_cursors(conn)
    newest_after = max((moment for _key, moment in cursors_after), default=None)
    after_note = _iso(newest_after) if newest_after is not None else "(读不到游标)"
    verdict = "ok" if returncode == 0 else "failed"
    log_error = append_autoreheal_log(
        state_dir,
        " ".join(
            [
                _iso(now),
                f"result={verdict}",
                f"rc={returncode}",
                f"trigger={CURSOR_CHECK}",
                f"cursor_before={_cursor_note()}",
                f"cursor_after={after_note}",
                f"reason={cursor_detail}",
                f"output={output or '(无输出)'}",
            ]
        ),
    )
    problems = [item for item in (stamp_error, log_error) if item]
    tail = f" · 注意:{'; '.join(problems)}" if problems else ""
    if returncode == 0:
        return Check(
            AUTOREHEAL_CHECK,
            OK,
            f"已自动重启(退出码 0) · 重启前游标 {_cursor_note()} → 重启后 {after_note}"
            f" · 日志 {os.path.join(state_dir, AUTOREHEAL_LOG)}{tail}",
        )
    return Check(
        AUTOREHEAL_CHECK,
        BAD,
        f"已尝试自动重启但失败(退出码 {returncode}):{output or '(无输出)'} · 按未自愈处理{tail}",
    )


def build_report(
    args: argparse.Namespace,
    now: Optional[datetime] = None,
    restart: Optional[Callable[[], Tuple[int, str]]] = None,
) -> Report:
    """跑完整一轮巡检。

    Args:
        args: 已解析的命令行参数。
        now: 当前时间(测试注入用),默认取 UTC now。
        restart: 自愈用的重启回调;None 表示用默认实现(`bash <script> restart`)。
            自测必须注入假回调 —— 真的调一次会杀掉正在跑的会话(包括跑测试的自己)。

    Returns:
        巡检结果。`SUPERAGENT_AUTOREHEAL` 关着(默认)时结果与加自愈之前**完全一致**:
        不读状态文件、不算闸门、也不多出一条检查。
    """
    report = Report()
    now = now or datetime.now(timezone.utc)
    token = _read_token(args.token_path)

    if not args.skip_egress:
        report.add(check_egress(args.proxy, token))
        # 直连那条腿**不进报告**(2026-11-28):GitHub 已改走 mihomo,直连不是 worker 的路径,
        # 而本机直连确实不通 —— 当必检项就是永久假红。要查它用手工排障:
        # `python -c "from scripts import superagent_health as h; print(h.check_egress_direct(None))"`。
        report.add(check_proxy_selector(args.proxy_config))
        # 第六项跟这两项同一组(都是「代理 / 出网」),所以复用 `--skip-egress` 一起跳过 ——
        # 离线自测与「不想看网络那几项」的场合只要一个开关;要单独关它用 `--skip-proxy-inherit`。
        if not args.skip_proxy_inherit:
            report.add(
                check_proxy_inherit(os.environ, args.proxy, args.proxy_inherit_timeout)
            )

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
            elif check.state != OK and _autoreheal_enabled(args):
                # 只有第四项**确实判成停摆**(不是「判不出来」)才谈自愈,而且开关默认关。
                report.add(
                    maybe_autoreheal(
                        conn,
                        args.workdir,
                        now,
                        args.autoreheal_min_minutes,
                        args.autoreheal_state_dir,
                        check.detail,
                        restart or _default_restart_callback(args),
                    )
                )
        for check in check_worktrees(conn, args.workdir):
            report.add(check)

    if _ci_red_enabled(args) and not args.skip_ci_red:
        checks, unknown = ci_red_checks(_ci_red_loader(args))
        for check in checks:
            report.add(check)
        if unknown:
            report.unknown.append(unknown)
    return report


def _ci_red_loader(args: argparse.Namespace) -> Callable[[], Tuple[Any, Optional[str]]]:
    """按命令行参数给出「取 runs 快照」的函数(文件注入优先,否则走 gh)。

    Args:
        args: 已解析的命令行参数。

    Returns:
        一个无参函数,返回 `(runs 快照, 失败原因)`。文件注入让自测与反证完全离线。

    为什么放在 `with conn:` 之外:这一项要联网(经代理调 GitHub),而状态库连接只在
    「读本地状态」的那几项里需要。混在一起会让一次网络超时把状态库连接晾在那儿。
    """
    if args.runs_file:
        path = args.runs_file
        return lambda: load_runs_file(path)
    return lambda: fetch_ci_runs(args.gh_cli, args.proxy, args.repo, args.ci_branch)


def _ci_red_enabled(args: argparse.Namespace) -> bool:
    """CI 红轨那一项的总闸:只有显式写成 `1/on/true/yes` 才算开(默认关)。

    Args:
        args: 已解析的命令行参数(默认值取自 `SUPERAGENT_HEALTH_CI_RED`)。

    Returns:
        是否本轮检查 CI 红轨。

    与 `SUPERAGENT_AUTOREHEAL` / `L4_INTAKE` 同一口径:**机制上线不等于开始执行**。
    默认关的理由是这一项要联网(经代理调 GitHub),先让它在人盯着的时候跑几轮,
    确认判据与指纹都对,再交给 timer。
    """
    return _truthy(args.ci_red)


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


def _truthy(value: Any) -> bool:
    """把 `1/on/true/yes/y` 这类写法认成「开」,其余(含None空串)一律是「关」。

    Args:
        value: 命令行或环境变量里的原始值。

    Returns:
        是否算打开。

    只认白名单而不是「非空即真」:`SUPERAGENT_AUTOREHEAL=off` / `=0` / `=false` 都必须**关**,
    否则运维按文档写 `off` 反而把重启打开,那是最糟的一种误读。
    """
    if value is None:
        return False
    return str(value).strip().lower() in TRUTHY


def _autoreheal_enabled(args: argparse.Namespace) -> bool:
    """自愈总闸:只有显式写成 `1/on/true/yes` 才算开(默认关)。

    Args:
        args: 已解析的命令行参数(默认值取自 `SUPERAGENT_AUTOREHEAL`)。

    Returns:
        是否允许本轮执行自愈。

    与 L4 的 `L4_INTAKE` 同一口径:**机制上线不等于开始执行**,开不开由人显式决定。
    """
    return _truthy(args.autoreheal)


def _default_restart_callback(args: argparse.Namespace) -> Callable[[], Tuple[int, str]]:
    """把默认重启实现绑到当前的 `--restart-script`,给 `maybe_autoreheal` 当回调。

    Args:
        args: 已解析的命令行参数。

    Returns:
        无参回调,返回 `(退出码, 输出尾部)`。
    """
    return lambda: default_restart(args.restart_script)


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
    parser.add_argument(
        "--skip-proxy-inherit",
        action="store_true",
        help="只跳过第六项(WSL 继承到的 http(s)_proxy 指向死端口);探针是纯本地 TCP 建连",
    )
    parser.add_argument(
        "--proxy-inherit-timeout",
        type=float,
        default=3.0,
        help="第六项对继承到的代理做一次 TCP 探针的超时秒数(默认 3)",
    )
    parser.add_argument("--skip-enqueue", action="store_true", help="跳过入队三连")
    parser.add_argument(
        "--ci-red",
        default=os.environ.get("SUPERAGENT_HEALTH_CI_RED"),
        help="CI 红轨总闸:1/on = 开,其它(含默认的空值)= 关。默认关 —— 机制上线不等于开始执行",
    )
    parser.add_argument(
        "--ci-branch",
        default=os.environ.get("SUPERAGENT_CI_BRANCH", DEFAULT_BRANCH),
        help=f"查红轨用的分支(默认 {DEFAULT_BRANCH};改名后必须同步,否则静默查空)",
    )
    parser.add_argument(
        "--repo",
        default=os.environ.get("SUPERAGENT_HEALTH_REPO", DEFAULT_REPO),
        help="查红轨用的仓库(owner/name,默认本仓库)",
    )
    parser.add_argument(
        "--runs-file",
        default=None,
        help="用本地 JSON 冒充 runs 快照(自测 / 反证,不联网)",
    )
    parser.add_argument("--skip-ci-red", action="store_true", help="即使总闸开着也跳过 CI 红轨")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    parser.add_argument(
        "--autoreheal",
        default=os.environ.get("SUPERAGENT_AUTOREHEAL"),
        help="安全自愈总闸:1/on = 开,其它(含默认的空值)= 关。默认关 —— 机制上线不等于开始执行",
    )
    parser.add_argument(
        "--autoreheal-min-minutes",
        type=int,
        default=_env_int("SUPERAGENT_AUTOREHEAL_MIN_MINUTES", DEFAULT_AUTOREHEAL_MIN_MINUTES),
        help="两次自愈尝试之间的最小间隔(分钟,默认 20;防抖,避免巡检每轮都重启)",
    )
    parser.add_argument(
        "--autoreheal-state-dir",
        default=os.environ.get("SUPERAGENT_HEALTH_STATE", DEFAULT_AUTOREHEAL_STATE_DIR),
        help="自愈的状态目录:防抖时间戳与 autoreheal.log 都写在这里",
    )
    parser.add_argument(
        "--restart-script",
        default=os.environ.get("SUPERAGENT_RESTART_SCRIPT", DEFAULT_RESTART_SCRIPT),
        help="默认重启回调执行的脚本(自测一律注入假回调,不会走到这里)",
    )
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
