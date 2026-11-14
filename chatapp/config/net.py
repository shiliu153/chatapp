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

文件信息:
    文件名称          config/net.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import ipaddress

from django.conf import settings


def _networks():
    """解析 ``TRUSTED_PROXY_IPS`` 为网段列表。

    备注信息:
        逗号分隔,``strict=False`` 所以 ``127.0.0.1`` 这类单地址也能成网段;
        非法条目静默跳过,配置写错只会少认几个代理,不会让请求失败。
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

    备注信息:
        IPv4-mapped IPv6(``::ffff:127.0.0.1``)先折成 IPv4 再比,名单只写一份;
        非法地址返回 ``False``,即「不可信」,按严格方向兜底。
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
        ``client_ip(request)``

    备注信息:
        只有直连对端命中 ``settings.TRUSTED_PROXY_IPS`` 才采信 ``X-Real-IP``
        (优先)与 ``X-Forwarded-For``(取最后一段),直连时这两个头一律忽略,
        否则伪造请求头就能绕过后台 IP 白名单与登录失败锁定。
        ``request`` 为 ``None`` 或 ``REMOTE_ADDR`` 为空时返回空串,调用方需自行判断。
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
