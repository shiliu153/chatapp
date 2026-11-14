"""聊天图片的限时签名 URL。

签名规则与 imserver 的 ``src/util/media_sign.cpp`` **逐字节一致**,任何一侧改算法
都必须先让两侧的共享测试向量变红:

    signing_string = path + "\\n" + str(exp)
    sig            = hmac_sha256(secret, signing_string).hexdigest()

设计要点:
    1. ``exp`` 按整点对齐(``now - now % 3600 + ttl``):同一小时内同一张图给出同一个
       URL,客户端与浏览器缓存不会因为「每次刷新历史都换 URL」而全部失效;
    2. 只签 ``/media/chat/`` 下的路径 —— 用户照片、广场图片仍走公开直出,不在此列;
    3. 密钥为空时不签名、验签恒真:本地 ``runserver`` 没有 nginx 验签,不能把开发环境
       的图片全打成 403;生产由部署核对单保证配置。

文件信息:
    文件名称          im/media_sign.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlsplit

from django.conf import settings

SIGN_PATH_PREFIX = "/media/chat/"
BUCKET_SECONDS = 3600


def _secret() -> str:
    """当前生效的签名密钥;空串表示不签名。

    参数说明:
        无。

    返回参数:
        ``settings.IM_MEDIA_SIGN_SECRET``,未配置时为 ``""``。

    使用示例:
        ``_secret()``

    备注信息:
        生产(``DEBUG=False``)未配置该密钥时 ``config/settings.py`` 直接抛
        ``ImproperlyConfigured``,进程起不来;因此运行期读到空串只可能是开发或测试环境。
    """
    return getattr(settings, "IM_MEDIA_SIGN_SECRET", "") or ""


def _ttl() -> int:
    """签名有效期(秒)。

    参数说明:
        无。

    返回参数:
        ``settings.IM_MEDIA_SIGN_TTL``,非法值回落到 3600。

    使用示例:
        ``_ttl()``

    备注信息:
        默认 TTL 3600 秒;配置缺失、为 ``0`` 或非数字时一律回落 3600。
    """
    try:
        return int(getattr(settings, "IM_MEDIA_SIGN_TTL", 3600) or 3600)
    except (TypeError, ValueError):
        return 3600


def expires_at(now: int | None = None) -> int:
    """按整点对齐后的过期时间戳。

    对齐到整点是为了让同一小时内的历史消息复用同一个 URL(浏览器/客户端缓存
    不会每次刷新都失效)。但如果 ``ttl`` 小于一小时,直接对齐会得到「下一整点就
    过期」的极短有效期,因此至少保证还有 ``BUCKET_SECONDS`` 的余量。

    参数说明:
        now: 当前 Unix 秒;``None`` 表示取系统时间。

    返回参数:
        过期时间戳(秒)。

    使用示例:
        ``expires_at(1763000000)``

    备注信息:
        对齐式是 ``moment - moment % 3600 + ttl``;结果不足 ``moment + BUCKET_SECONDS`` 时
        再加一个 ``BUCKET_SECONDS``,所以返回值恒大于 ``now``,同一整点小时内同一路径拿到
        同一个 ``exp``。
    """
    moment = int(time.time() if now is None else now)
    expires = moment - moment % BUCKET_SECONDS + _ttl()
    if expires <= moment + BUCKET_SECONDS:
        expires += BUCKET_SECONDS
    return expires


def path_of(url: str) -> str:
    """从绝对 URL 或相对路径里取出不含 query 的路径。

    参数说明:
        url: 绝对 URL 或 ``/media/...`` 形式的路径。

    返回参数:
        路径部分,保证以 ``/`` 开头。

    使用示例:
        ``path_of("https://cdn.test/media/chat/a.jpg?e=1")``

    备注信息:
        用 ``urlsplit`` 只取 path,query 与 fragment 都被丢掉;路径为空时回落 ``"/"``。
    """
    return urlsplit(url).path or "/"


def signature(path: str, expires: int, secret: str | None = None) -> str:
    """计算签名(小写 hex)。

    参数说明:
        path: 规范化路径,如 ``/media/chat/2026/10/x.jpg``。
        expires: 过期时间戳。
        secret: 显式密钥;``None`` 表示取配置。

    返回参数:
        64 位小写十六进制签名。

    使用示例:
        ``signature("/media/chat/2026/10/x.jpg", 1763003600)``

    备注信息:
        签名串是 ``f"{path}\n{expires}"``,必须与 imserver 的 ``src/util/media_sign.cpp``
        逐字节一致,任何一侧改算法都要先让共享测试向量变红;``secret`` 显式传空串时按空
        密钥计算,等价于未配置。
    """
    key = _secret() if secret is None else secret
    message = f"{path}\n{expires}".encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def sign_query(path: str, *, now: int | None = None) -> str:
    """生成 ``e=..&s=..`` 查询串。

    参数说明:
        path: 规范化路径。
        now: 当前 Unix 秒;``None`` 表示取系统时间。

    返回参数:
        查询串;未配置密钥时返回空串。

    使用示例:
        ``sign_query("/media/chat/2026/10/x.jpg")``

    备注信息:
        返回 ``e=<exp>&s=<sig>`` 形式,字段顺序固定;未配置密钥时返回空串,调用方据此不加
        query(开发环境不签名)。
    """
    if not _secret():
        return ""
    expires = expires_at(now)
    return f"e={expires}&s={signature(path, expires)}"


def sign_url(url: str, *, now: int | None = None) -> str:
    """给 URL 加上签名 query;已有 query 会被替换。

    参数说明:
        url: 绝对 URL 或路径。
        now: 当前 Unix 秒;``None`` 表示取系统时间。

    返回参数:
        带签名的 URL;未配置密钥时返回去掉 query 的原 URL。

    使用示例:
        ``sign_url("https://cdn.test/media/chat/a.jpg")``

    备注信息:
        先按第一个 ``?`` 切掉原 query 再签名,已有签名直接被替换;未配置密钥时返回去掉
        query 的 URL,不会留下空的 ``?``。
    """
    clean = url.split("?", 1)[0]
    query = sign_query(path_of(clean), now=now)
    return f"{clean}?{query}" if query else clean


def verify(path: str, expires: str, signature_value: str, *, now: int | None = None) -> bool:
    """校验路径白名单、有效期与签名。

    参数说明:
        path: 请求的规范化路径(nginx 传来的 ``X-Original-URI`` 的 path 部分)。
        expires: 查询参数 ``e``。
        signature_value: 查询参数 ``s``。
        now: 当前 Unix 秒;``None`` 表示取系统时间。

    返回参数:
        是否放行;未配置密钥时仅 ``DEBUG`` 放行(生产 fail-closed)。

    使用示例:
        ``verify("/media/chat/a.jpg", "1763003600", signature_value)``

    备注信息:
        判定顺序是 路径白名单(``SIGN_PATH_PREFIX``) → 密钥 → 有效期 → 签名,任一步不过即
        ``False``;签名比较用 ``hmac.compare_digest`` 防时序侧信道;``s`` 传 ``None`` 时按
        空串比较。
    """
    if not path.startswith(SIGN_PATH_PREFIX):
        return False
    if not _secret():
        return bool(settings.DEBUG)
    try:
        moment_expires = int(expires)
    except (TypeError, ValueError):
        return False
    moment = int(time.time() if now is None else now)
    if moment_expires <= moment:
        return False
    return hmac.compare_digest(signature(path, moment_expires), signature_value or "")
