#!/usr/bin/env python3
"""把机场订阅渲染成 mihomo 可用的 config.yaml。

为什么要这一层,而不是把订阅内容直接丢给 mihomo:

1. **机场下发的配置对「一台无人值守的 WSL 服务器」是不安全的** ——
   它默认 `allow-lan: true` + `bind-address: '*'`,等于给局域网开了一个
   无需认证的开放代理。必须覆写成只听回环。
2. **端口会撞** —— 机场默认 `external-controller: 127.0.0.1:9090`,而
   Windows 侧的 Clash 客户端惯例也占 9090;WSL 的 localhostForwarding 会把
   WSL 端口映射到 Windows localhost,两者必然打架。这里改到 9091。
3. **测速目标不对齐** —— 机场的 `自动选择` 组测的是
   `http://cp.cloudflare.com`,而本项目真正的痛点是 GitHub 新建 TLS 连接
   被间歇重置(见 docs/ops/superagent.md §11)。测 cloudflare 选出来的
   "最快节点"和"能稳定拉 GitHub 的节点"是两件事,所以这里另外造一个
   `github` 组,直接拿 `https://api.github.com/rate_limit` 当测速 URL。

渲染失败时**绝不覆盖现有配置** —— 机场订阅偶尔会返回一页 HTML 错误页或
残缺的 YAML,把它写进 config.yaml 会让 mihomo 起不来,进而让整个 worker
断网。校验不过就退出非零,由调用方保留旧配置。

用法:
    python3 render-config.py --url-file <订阅URL文件> --out <输出路径> \\
        [--override override.yaml] [--secret-file <controller密钥文件>]

Args 见各函数 docstring。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import urllib.error
import urllib.request
from typing import Any

import yaml

# 订阅站按 User-Agent 决定返回格式:不带 UA 时返回 base64 通用订阅
# (trojan:// 一行一个节点),带 Clash 系 UA 才返回完整 YAML。这里要的是 YAML。
CLASH_UA = "clash-verge/v1.6.0"

# 拉订阅的超时。订阅站直连通常 200~400ms;给 20s 足够,再久就是真挂了。
FETCH_TIMEOUT = 20

# 校验门槛:低于这个节点数基本可以确定拿到的是错误页或残配置。
MIN_PROXIES = 10

# 机场会在 proxies 里塞几条"信息节点"(剩余流量/套餐到期/下次重置),
# 它们其实是同一台服务器的真 trojan 入口。放进 github 测速组只会污染测速
# 结果,按名字排除。
INFO_NODE_PATTERN = re.compile(r"流量|套餐|重置|到期")


def die(msg: str) -> None:
    """打印错误到 stderr 并以退出码 2 结束。

    Args:
        msg: 人类可读的错误原因。
    """
    print(f"render-config: {msg}", file=sys.stderr)
    raise SystemExit(2)


def read_text(path: str, what: str) -> str:
    """读取一个文本文件并去掉首尾空白。

    Args:
        path: 文件路径。
        what: 用于报错信息的人类可读描述(如「订阅 URL 文件」)。

    Returns:
        文件内容(已 strip)。
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError as exc:
        die(f"读不到{what} {path}:{exc}")


def fetch_subscription(url: str, proxy: str | None) -> str:
    """拉取订阅原文。

    先直连,失败再试宿主代理。顺序不能反:订阅站是国内可达的,
    走代理反而多一跳;而宿主代理在本机对 GitHub 的失败率高达 50%
    (实测见 docs/ops/superagent.md §12),不该让它挡在必经路径上。

    Args:
        url: 订阅地址(含 token,只在内存里用,不落盘)。
        proxy: 直连失败时使用的代理地址,如 ``http://172.26.240.1:7897``;
            为 None 则不重试。

    Returns:
        订阅原文(预期是 Clash YAML)。

    Raises:
        SystemExit: 两种方式都失败时由 die 结束。
    """
    req = urllib.request.Request(url, headers={"User-Agent": CLASH_UA})
    attempts: list[tuple[str, str | None]] = [("直连", None)]
    if proxy:
        attempts.append((f"经代理 {proxy}", proxy))

    errors: list[str] = []
    for label, proxy_url in attempts:
        try:
            if proxy_url:
                handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
                opener = urllib.request.build_opener(handler)
            else:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            with opener.open(req, timeout=FETCH_TIMEOUT) as resp:
                body = resp.read()
            text = body.decode("utf-8", errors="replace")
            if text.strip():
                print(f"render-config: 订阅已获取({label},{len(body)} 字节)", file=sys.stderr)
                return text
            errors.append(f"{label}: 空响应")
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            errors.append(f"{label}: {exc}")

    die("拉订阅失败 —— " + " / ".join(errors))


def validate(cfg: Any) -> dict[str, Any]:
    """校验订阅解析出来的配置够不够用。

    这一步是「坏订阅防线」:机场偶尔返回 HTML 错误页、或者返回一份只有
    几个节点的残缺配置。写进 config.yaml 后 mihomo 会起不来,worker 直接
    断网,而且现场看起来像「代理没开」,极难排查。宁可在渲染阶段就拒绝。

    Args:
        cfg: ``yaml.safe_load`` 的结果。

    Returns:
        通过校验的配置(原对象)。

    Raises:
        SystemExit: 任一硬性要求不满足时由 die 结束。
    """
    if not isinstance(cfg, dict):
        die("订阅不是 YAML 映射(可能是 HTML 错误页)")
    for key in ("proxies", "proxy-groups", "rules"):
        if not cfg.get(key):
            die(f"订阅缺少 {key}")

    proxies = cfg["proxies"]
    if not isinstance(proxies, list) or len(proxies) < MIN_PROXIES:
        die(f"节点数不足({len(proxies) if isinstance(proxies, list) else '非列表'} < {MIN_PROXIES})")
    for idx, node in enumerate(proxies):
        if not isinstance(node, dict):
            die(f"第 {idx} 个节点不是映射")
        for field in ("name", "type", "server", "port"):
            if field not in node:
                die(f"第 {idx} 个节点缺字段 {field}")
    return cfg


def pick_github_nodes(proxies: list[dict[str, Any]], spec: dict[str, Any]) -> list[str]:
    """挑出放进 GitHub 测速组的节点名。

    只挑专线(IEPL)。理由是实测:同一机场的中转/直连线路在 GitHub 上
    的失败率明显高于 IEPL,而 worker 每一轮轮询有 60~100 次 GitHub 读,
    单请求 15% 失败率就足以让整轮踩雷(§11)。节点名是订阅给的,
    订阅更新后名字会变,所以这里按模式匹配而不是写死。

    Args:
        proxies: 订阅里的节点列表。
        spec: ``override.yaml`` 的 ``github_group`` 段。

    Returns:
        节点名列表;挑不到时返回空列表(调用方据此决定是否跳过建组)。
    """
    include = re.compile(spec.get("include_pattern") or "IEPL")
    exclude = re.compile(spec.get("exclude_pattern") or INFO_NODE_PATTERN.pattern)
    limit = int(spec.get("max_nodes") or 12)

    picked: list[str] = []
    for node in proxies:
        name = str(node.get("name", ""))
        if not name or exclude.search(name) or not include.search(name):
            continue
        picked.append(name)
        if len(picked) >= limit:
            break
    return picked


def inject_github_group(cfg: dict[str, Any], spec: dict[str, Any]) -> bool:
    """注入 GitHub 专用测速组,并把它设为主组的默认出口。

    mihomo 的规则最后一条是 ``MATCH,节点选择``,而 ``节点选择`` 是 select 组、
    默认选中它 proxies 列表的第一个。所以只要把新组插到该列表首位,
    默认出口就换成了按 GitHub 实测选出来的节点 —— 不需要改 rules,
    也不影响「国际媒体」「电报代理」这些机场自带的分流组。

    Args:
        cfg: 已校验的配置(原地修改)。
        spec: ``override.yaml`` 的 ``github_group`` 段。

    Returns:
        True 表示建组并接管了默认出口;False 表示节点不够,保持原样。
    """
    group_name = spec.get("name") or "github"
    nodes = pick_github_nodes(cfg["proxies"], spec)
    if len(nodes) < 2:
        print(
            "render-config: 警告 —— 匹配到的 IEPL 节点不足 2 个,跳过 github 组,"
            "默认出口仍是机场的「自动选择」(测 cloudflare,不反映 GitHub 质量)",
            file=sys.stderr,
        )
        return False

    groups = cfg["proxy-groups"]
    github_group = {
        "name": group_name,
        "type": "url-test",
        "proxies": nodes,
        "url": spec.get("url") or "https://api.github.com/rate_limit",
        "interval": int(spec.get("interval") or 300),
        "tolerance": int(spec.get("tolerance") or 100),
        "lazy": False,
    }
    # 组引用允许前向,但放在最前面更便于人读 --help / 看配置。
    groups.insert(0, github_group)

    # 主组:优先机场约定的「节点选择」,否则退化为第一个组。
    main = next((g for g in groups if g.get("name") == "节点选择"), None)
    if main is None:
        main = next((g for g in groups if g is not github_group), None)
    if main is None:
        return False

    members = main.get("proxies")
    if not isinstance(members, list):
        return False
    if group_name in members:
        members.remove(group_name)
    members.insert(0, group_name)
    print(
        f"render-config: 已建组 {group_name}({len(nodes)} 个 IEPL 节点,"
        f"测速 {github_group['url']}),并设为「{main.get('name')}」默认出口",
        file=sys.stderr,
    )
    return True


def apply_override(cfg: dict[str, Any], override: dict[str, Any], secret: str | None) -> None:
    """把本地覆写应用到配置上(原地修改)。

    Args:
        cfg: 已校验的配置。
        override: ``override.yaml`` 的内容;其中 ``github_group`` 段是给
            :func:`inject_github_group` 用的,不作为配置键写出。
        secret: controller 的 Bearer 密钥;为 None 时不设(仅回环监听,
            不设也能用,但设了可以挡住本机其他进程误调)。
    """
    for key, value in override.items():
        if key == "github_group":
            continue
        cfg[key] = value

    if secret:
        cfg["secret"] = secret

    # 安全兜底:无论 override 怎么写,监听地址都不许离开回环。
    cfg["allow-lan"] = False
    cfg["bind-address"] = "127.0.0.1"


def main() -> None:
    """命令行入口:拉订阅 → 校验 → 注入 → 原子落盘。"""
    ap = argparse.ArgumentParser(description="把机场订阅渲染成 mihomo config.yaml")
    ap.add_argument("--url-file", help="含订阅 URL 的文件(仓库外,权限 600);--from-file 时可省")
    ap.add_argument("--out", required=True, help="输出 config.yaml 路径")
    ap.add_argument("--override", help="本地覆写 YAML")
    ap.add_argument("--secret-file", help="controller 密钥文件;不存在则不设 secret")
    ap.add_argument("--host-proxy", help="直连失败时使用的宿主代理")
    # 离线入口:自测(selftest.sh)和人工调试用,不碰网络。
    ap.add_argument("--from-file", help="不拉订阅,直接读这个本地文件当订阅原文")
    args = ap.parse_args()

    override: dict[str, Any] = {}
    if args.override:
        try:
            loaded = yaml.safe_load(read_text(args.override, "覆写文件"))
        except yaml.YAMLError as exc:
            die(f"覆写文件不是合法 YAML:{exc}")
        if not isinstance(loaded, dict):
            die("覆写文件必须是 YAML 映射")
        override = loaded

    secret = None
    if args.secret_file and os.path.exists(args.secret_file):
        secret = read_text(args.secret_file, "controller 密钥文件") or None

    if args.from_file:
        raw = read_text(args.from_file, "订阅原文文件")
        print(f"render-config: 从本地文件读订阅({len(raw)} 字节)", file=sys.stderr)
    else:
        if not args.url_file:
            die("要么给 --url-file,要么给 --from-file")
        url = read_text(args.url_file, "订阅 URL 文件")
        if not url.startswith(("http://", "https://")):
            die(f"订阅 URL 不是 http(s):{url[:32]}…")
        raw = fetch_subscription(url, args.host_proxy)

    try:
        parsed = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        die(f"订阅不是合法 YAML(可能是 HTML 错误页):{exc}")
    cfg = validate(parsed)
    spec = override.get("github_group") or {}
    inject_github_group(cfg, spec)
    apply_override(cfg, override, secret)

    # 原子落盘:先写同目录临时文件再 rename。中途失败不会留下半个
    # config.yaml —— mihomo 读到半个文件会直接退出。
    out_dir = os.path.dirname(os.path.abspath(args.out)) or "."
    fd, tmp = tempfile.mkstemp(dir=out_dir, prefix=".config-", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(
                cfg,
                fh,
                allow_unicode=True,
                sort_keys=False,
                default_flow_style=False,
                width=4096,
            )
        os.replace(tmp, args.out)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise

    nodes = len(cfg["proxies"])
    print(
        f"render-config: 已写出 {args.out}"
        f"(节点 {nodes},组 {len(cfg['proxy-groups'])},规则 {len(cfg['rules'])},"
        f"mixed-port {cfg.get('mixed-port')},controller {cfg.get('external-controller')})",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
