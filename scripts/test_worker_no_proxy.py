"""worker 出口口径 ``no_proxy`` 的一致性自测:启动脚本与巡检必须是同一份。

为什么要有这一条
----------------
worker 的出口口径是「**只有模型网关走直连,其余(含 GitHub 各域)走 mihomo**」,这份清单同时被两处消费:

* ``scripts/superagent-start/start-superagent.sh`` —— 真正 ``export no_proxy`` 给 worker 的地方;
* ``scripts/superagent_health.py::WORKER_NO_PROXY`` —— 巡检里 ``gh`` 子进程用的同一份口径。

此前它们**只有口头约定**。2026-11-28 实测到一个真实漂移:运行时
``/root/start-superagent.sh`` 有那五个 GitHub 域,而**仓库模板里没有** —— 也就是说任何人跑一次
``scripts/superagent-start/install.sh``(它把仓库模板 ``install`` 到 ``/root/``)都会把
「GitHub 走直连」这条口径**静默冲掉**,worker 的全部 GitHub 流量被压到机场上;机场一抽风,
轮询与 ``git`` 一起断,而巡检当时只看代理那条腿,看不出是这一层的事(观测盲区正是
PR #518 修掉的那条)。

2026-11-28 口径翻转(同日):WSL 内直连 ``github.com:443`` 已不通(git fetch 报
``Failed to connect ... port 443``,129s 超时;同一时刻经 mihomo 一次就过),于是
**GitHub 各域也从 no_proxy 里摘掉**,与其余外网同路。本文件因此同时钉两件事:

1. 两份清单的 GitHub 组必须相等(改一处必须改两处);
2. GitHub 各域**必须不在**清单里 —— 有人把它们加回去(即回滚口径)却只改一处时,
   第 1 条会红;两处一起加回时,第 2 条会红并提示这是一次**有意的口径翻转**,
   得连同 ``docs/ops/superagent.md`` §12 与门禁 reason 一起改。

用法
----
::

    python -m unittest scripts.test_worker_no_proxy -v      # 全量
    python scripts/test_worker_no_proxy.py                  # 同上(直接跑)
"""

from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts import superagent_health as healthcheck  # noqa: E402

#: 启动脚本(模板)的路径。
START_SCRIPT = ROOT / "scripts" / "superagent-start" / "start-superagent.sh"

#: **必须不出现在两份清单里**的 GitHub 域(2026-11-28 起它们与其余外网同路走代理)。
#: worker 的轮询、``gh``、``git fetch``、release 附件下载全在这五个域上 ——
#: 把它们划进直连,一旦直连不通就是「全部 GitHub 流量断在一条死路上」。
FORBIDDEN_GITHUB_HOSTS = (
    "api.github.com",
    "github.com",
    "codeload.github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
)

#: 两份清单都必须有的「非 GitHub」项 —— 它们各自防一类事故,见启动脚本里的注释。
REQUIRED_BASE_HOSTS = ("127.0.0.1", "localhost", "wb.shiliu153.me")


def parse_start_script_no_proxy(text: str) -> list:
    """从启动脚本正文里抽出 ``export no_proxy="…"`` 的那一串主机。

    参数说明:
        text: ``start-superagent.sh`` 的全文。

    返回参数:
        主机字符串列表(已去掉 ``${HOSTIP:-x.x.x.x}`` 这类动态占位与空项);抽不到时返回空列表。

    使用示例:
        >>> parse_start_script_no_proxy('export no_proxy="a,b,.local"')
        ['a', 'b', '.local']

    备注信息:
        ``HOSTIP`` 是 NAT 网段里由 WSL 分配的宿主网关,**不是常量**(重启后可能变),所以比对时
        把它剔掉;它是否在清单里由启动脚本自己保证(少了解析不出宿主兜底那一跳)。
    """
    match = re.search(r'^\s*export\s+no_proxy="([^"]*)"', text, re.M)
    if not match:
        return []
    hosts = []
    for item in match.group(1).split(","):
        host = item.strip()
        if not host or "${" in host or host.startswith("$"):
            continue
        hosts.append(host)
    return hosts


def github_hosts_of(hosts) -> list:
    """挑出清单里所有 GitHub 相关域,排好序后返回。

    参数说明:
        hosts: 主机列表(见 :func:`parse_start_script_no_proxy`)。

    返回参数:
        ``github.com`` 及其子域,按字典序。

    使用示例:
        >>> github_hosts_of(["a.example.com", "api.github.com"])
        ['api.github.com']

    备注信息:
        只比 GitHub 这一组而不是整串:两边各有自己的合法差异(启动脚本有 ``${HOSTIP}`` 与
        ``.local``、巡检那边只写固定域),拿整串相等去判会天天红。
    """
    return sorted(
        host for host in hosts if host == "github.com" or host.endswith(".github.com")
    )


class NoProxyConsistencyTests(unittest.TestCase):
    """两份清单必须逐项对上:GitHub 那一组相等,基础项都在。"""

    def setUp(self) -> None:
        """读一次启动脚本,供各用例共用。"""
        self.script_hosts = parse_start_script_no_proxy(START_SCRIPT.read_text(encoding="utf-8"))
        self.health_hosts = [h.strip() for h in healthcheck.WORKER_NO_PROXY.split(",") if h.strip()]

    def test_start_script_has_no_proxy_line(self) -> None:
        """启动脚本里必须能解析出 ``export no_proxy``——解析不到就是被删了或改了写法。"""
        self.assertTrue(self.script_hosts, f"在 {START_SCRIPT} 里没找到 export no_proxy=\"…\"")

    def test_github_hosts_are_identical(self) -> None:
        """GitHub 那一组两份必须**完全相等**(方向都判:少一个 / 多一个都是漂移)。"""
        self.assertEqual(
            github_hosts_of(self.script_hosts),
            github_hosts_of(self.health_hosts),
            "启动脚本与 superagent_health.WORKER_NO_PROXY 的 GitHub 域不一致;"
            "改一处必须改两处(见本文件模块 docstring 里 2026-11-28 的那次漂移)",
        )

    def test_github_hosts_go_through_proxy(self) -> None:
        """五个 GitHub 域**都必须不在**两份清单里(2026-11-28 口径:与其余外网同路走代理)。

        备注信息:
            这条不是「越少越好」的风格要求,而是判据:WSL 内直连 443 不通,把 GitHub 划进
            ``no_proxy`` 等于让 worker 的轮询与 ``git`` 全部绕开代理去撞墙。
            真要回滚(某天直连恢复且更快),得连着 ``docs/ops/superagent.md`` §12、
            门禁 reason 与启动脚本注释一起改 —— 让这次翻转仍然是一次**显式决定**。
        """
        for host in FORBIDDEN_GITHUB_HOSTS:
            with self.subTest(host=host):
                self.assertNotIn(host, self.script_hosts, f"启动脚本的 no_proxy 又把 {host} 划成直连了")
                self.assertNotIn(host, self.health_hosts, f"WORKER_NO_PROXY 又把 {host} 划成直连了")

    def test_required_base_hosts_present(self) -> None:
        """本地回环与模型网关两项必须在两份里都有——它们各自防一类事故。"""
        for host in REQUIRED_BASE_HOSTS:
            with self.subTest(host=host):
                self.assertIn(host, self.script_hosts, f"启动脚本的 no_proxy 缺 {host}")
                self.assertIn(host, self.health_hosts, f"WORKER_NO_PROXY 缺 {host}")

    def test_parser_ignores_dynamic_hostip(self) -> None:
        """``${HOSTIP:-172.26.240.1}`` 这种动态项不该进比对结果(它不是常量)。"""
        text = 'export no_proxy="a.example.com,${HOSTIP:-172.26.240.1},.local"'
        hosts = parse_start_script_no_proxy(text)
        self.assertEqual(hosts, ["a.example.com", ".local"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
