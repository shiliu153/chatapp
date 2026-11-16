"""私聊媒体与资料语音的限时签名 URL。

签名规则与 imserver 的 ``src/util/media_sign.cpp`` **逐字节一致**,任何一侧改算法
都必须先让两侧的共享测试向量变红:

    signing_string = path + "\\n" + str(exp)
    sig            = hmac_sha256(secret, signing_string).hexdigest()

设计要点:
    1. ``exp`` 按整点对齐(``now - now % 3600 + ttl``):同一小时内同一个媒体给出同一个
       URL,客户端与浏览器缓存不会因为「每次刷新历史都换 URL」而全部失效;
    2. 只签 ``SIGN_PATH_PREFIXES`` 里的前缀 —— 聊天图片/语音(``/media/chat/``)与资料
       语音自我介绍(``/media/voices/``,语音是声纹,属于身份特征);用户资料图与广场图
       仍是公开直出,不在此列。判据统一收到 ``is_signable_path`` 一处;
    3. 密钥为空时签名侧与验签侧分开处理:签名侧直接不签(``sign_query`` 返回空串、
       ``sign_url`` 原样返回),验签侧则**只在 ``DEBUG`` 下放行** —— 本地 ``runserver``
       没有 nginx 验签,不能把开发环境的图片全打成 403;生产 ``DEBUG`` 为假时缺密钥
       一律拒绝(fail-closed),由部署核对单保证配置。
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlsplit

from django.conf import settings

SIGN_PATH_PREFIXES = ("/media/chat/", "/media/voices/")
BUCKET_SECONDS = 3600


def is_signable_path(path: str) -> bool:
    """路径是否属于「可签名 / 可验签」的媒体白名单。

    参数说明:
        path: 规范化路径(``urlsplit(url).path``,不含 query),如
            ``/media/voices/2026/11/7-a1b2.m4a``;整条 URL 请先过 ``path_of``。

    返回参数:
        ``True`` = 可签名、可验签;``False`` = 不在白名单,签名与验签都应拒绝。

    使用示例:
        ``if not media_sign.is_signable_path(parts.path):``(见 ``im/views.py`` 的
        ``image_auth``)

    备注信息:
        白名单是常量 ``SIGN_PATH_PREFIXES``:``/media/chat/``(聊天图片与语音)与
        ``/media/voices/``(资料语音自我介绍)。资料图、广场图是公开内容,不在此列。
        纯字符串前缀匹配:只认 ``/media/chat/`` 这种带结尾斜杠的前缀,``/media/chatx``
        不会被误放进来。
    """
    return path.startswith(SIGN_PATH_PREFIXES)


def _secret() -> str:
    """当前生效的签名密钥;空串表示不签名。

    参数说明:
        无。

    返回参数:
        ``settings.IM_MEDIA_SIGN_SECRET``,未配置时为 ``""``。

    使用示例:
        ``key = _secret() if secret is None else secret``(见本模块 ``signature``)

    备注信息:
        只读配置,不做缓存;空串表示签名侧不签名。
    """
    return getattr(settings, "IM_MEDIA_SIGN_SECRET", "") or ""


def _ttl() -> int:
    """签名有效期(秒)。

    参数说明:
        无。

    返回参数:
        ``settings.IM_MEDIA_SIGN_TTL``,非法值回落到 3600。

    使用示例:
        ``expires = moment - moment % BUCKET_SECONDS + _ttl()``(见本模块 ``expires_at``)

    备注信息:
        非整数或空值不抛异常,回落到 3600。
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
        ``media_sign.expires_at(1761779999)``(见 ``im/tests.py`` 的 ``MediaSignTests.test_expiry_is_bucket_aligned``)

    备注信息:
        纯函数,时间可注入以便测试;``ttl`` 由 ``_ttl()`` 现读配置。
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
        ``query = sign_query(path_of(clean), now=now)``(见本模块 ``sign_url``)

    备注信息:
        只取 ``urlsplit`` 的 path;``http://host`` 这类没有路径的输入返回 ``/``。
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
        ``media_sign.signature("/media/chat/2026/10/12-abc.jpg", 1761782400, secret="test-media-secret")``
        (见 ``im/tests.py`` 的 ``MediaSignTests.test_shared_vector_matches_imserver``)

    备注信息:
        签名串是 ``path + "\n" + str(exp)``,算法与 imserver 的 ``src/util/media_sign.cpp``
        逐字节一致,两侧由共享测试向量互相锁定。
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
        ``query = sign_query(path_of(clean), now=now)``(见本模块 ``sign_url``)

    备注信息:
        未配置密钥时直接返回空串,由 ``sign_url`` 原样返回 URL。
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
        ``media_sign.sign_url(f"{base}{chat_image.file.url}")``(见 ``im/views.py`` 的 ``upload_image``)

    备注信息:
        已有 query 一律丢弃并替换成新的 ``e`` / ``s``;未配置密钥时只去 query,不补 ``?``。
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
        ``media_sign.verify(parts.path, query["e"][0], query["s"][0])``(见 ``im/views.py`` 的 ``image_auth``)

    备注信息:
        只放行 ``is_signable_path`` 认可的路径(``/media/chat/`` 与 ``/media/voices/``),
        其余一律拒绝;资料图、广场图不在白名单里。
        未配置密钥时返回 ``bool(settings.DEBUG)``:仅开发环境放行,生产缺密钥一律拒绝(fail-closed)。
        过期、``e`` 无法解析或签名不符都返回 ``False``,不抛异常。
    """
    if not is_signable_path(path):
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
