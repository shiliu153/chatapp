"""客户端 IP 的解析:限流、后台 IP 白名单与登录锁定共用。

设计要点:
    1. **只信可信代理转发的头**:nginx 反代后 ``REMOTE_ADDR`` 恒为 127.0.0.1,
       这时才取 ``X-Real-IP``(优先)或 ``X-Forwarded-For`` 的最后一段;
    2. **直连时忽略这些头**:否则任何人伪造 ``X-Real-IP`` 就能绕过后台 IP 白名单
       与登录失败锁定(M-3);
    3. 可信名单来自 ``settings.TRUSTED_PROXY_IPS``(默认回环,支持 CIDR)。

关联文档:
    - 部署:docs/ops/nginx-security.md(反代必须覆盖 X-Real-IP / X-Forwarded-For)
    - 安全审计:docs/security/2026-10-28-api-security-audit-round2.md M-3
"""

import ipaddress

from django.conf import settings


def _networks():
    """解析 ``TRUSTED_PROXY_IPS`` 为网段列表。

    返回参数:
        ``ipaddress`` 网段对象列表;非法条目被忽略。

    使用示例:
        ``networks = _networks()``(见本模块 ``client_ip``)

    备注信息:
        每次调用重读 settings,改 ``TRUSTED_PROXY_IPS`` 后无需重启即可生效;
        配置项缺失时按 ``127.0.0.1,::1`` 兜底。
    """
    raw = getattr(settings, "TRUSTED_PROXY_IPS", "127.0.0.1,::1") or ""
    networks = []
    for item in raw.split(","):
        entry = item.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            continue
    return networks


def _is_trusted(remote: str, networks) -> bool:
    """判断直连对端是否在可信代理名单内。

    参数说明:
        remote: ``REMOTE_ADDR`` 原文。
        networks: ``ipaddress`` 网段列表。

    返回参数:
        命中任一同网段返回 ``True``;非法地址返回 ``False``。

    使用示例:
        ``_is_trusted(remote, _networks())``(见本模块 ``client_ip``)

    备注信息:
        IPv4-mapped IPv6(``::ffff:127.0.0.1``)先归一成 IPv4 再比对,
        所以名单只需写一份 IPv4。
    """
    try:
        address = ipaddress.ip_address(remote)
    except ValueError:
        return False
    # IPv4-mapped IPv6(::ffff:127.0.0.1)按 IPv4 处理,名单只写一份
    if address.version == 6 and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return any(address in network for network in networks)


def client_ip(request) -> str:
    """取请求的真实客户端 IP。

    参数说明:
        request: Django/DRF 请求对象;可为 ``None``。

    返回参数:
        IP 字符串;拿不到时返回空串。直连对端不可信时,永远返回 ``REMOTE_ADDR``。

    使用示例:
        ``ip=client_ip(request) or None``(见 ``ops/views.py`` 的登录审计记录);
        ``if allowed and client_ip(request) not in allowed:``(见 ``ops/middleware.py``)

    备注信息:
        只有直连对端命中 ``settings.TRUSTED_PROXY_IPS`` 才采信 ``X-Real-IP`` /
        ``X-Forwarded-For``;否则伪造该头即可绕过 IP 白名单与登录锁定。
    """
    if request is None:
        return ""
    meta = request.META
    remote = (meta.get("REMOTE_ADDR", "") or "").strip()
    if not remote:
        return ""
    if not _is_trusted(remote, _networks()):
        # 直连(或代理不在名单内):头一律不可信,只认 TCP 对端
        return remote
    real = meta.get("HTTP_X_REAL_IP", "").strip()
    if real:
        return real
    forwarded = meta.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return remote
