"""TOTP( RFC 6238 )的最小实现:运营后台的第二因子。

设计要点:
    1. 不引入第三方依赖:算法就是 HMAC-SHA1 + 时间步长,30 行足够,且便于审计;
    2. 密钥用 ``secrets`` 生成 20 字节再 base32(标准 authenticator App 可直接识别);
    3. 校验允许前后各一个时间步(±30 秒),容忍手机与服务器的小幅时钟漂移;
    4. 比较用 ``hmac.compare_digest``,避免时序侧信道。

文件信息:
    文件名称          accounts/totp.py
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

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

STEP_SECONDS = 30
DIGITS = 6


def generate_secret() -> str:
    """生成一个新的 base32 TOTP 密钥(不带 ``=`` 填充)。

    参数说明:
        无。

    返回参数:
        32 字符左右的 base32 字符串。

    使用示例:
        ``generate_secret()``

    备注信息:
        随机源是 ``secrets.token_bytes(20)``,20 字节符合 RFC 4226 对 HMAC-SHA1
        密钥长度的建议;去掉 ``=`` 填充便于 authenticator App 手工录入,
        ``_decode`` 会按需补回来。
    """
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _decode(secret: str) -> bytes:
    """把 base32 密钥解成字节,自动补齐 padding。

    参数说明:
        secret: base32 字符串。

    返回参数:
        原始密钥字节。

    使用示例:
        ``_decode("JBSWY3DPEHPK3PXP")``

    备注信息:
        先 ``upper`` 再按 8 的倍数补 ``=``,``b32decode(casefold=True)`` 大小写
        不敏感;密钥不是合法 base32 时抛 ``ValueError``,调用方需自行兜住。
    """
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded, casefold=True)


def code_at(secret: str, moment: int | None = None, step: int = STEP_SECONDS) -> str:
    """计算某一时刻的 6 位验证码。

    参数说明:
        secret: base32 密钥。
        moment: Unix 秒;``None`` 表示当前时间。
        step: 时间步长(秒)。

    返回参数:
        6 位数字字符串。

    使用示例:
        ``code_at(secret, 1700000000)``

    备注信息:
        计数器 = ``moment // step``,按 RFC 4226 动态截断:取摘要末字节低 4 位作
        偏移,读 4 字节并掩掉最高位,再对 ``10 ** DIGITS`` 取模左补零。
    """
    now = int(time.time() if moment is None else moment)
    counter = now // step
    digest = hmac.new(_decode(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 10 ** DIGITS:0{DIGITS}d}"


def verify(secret: str, code: str, moment: int | None = None, window: int = 1) -> bool:
    """校验验证码,允许前后 ``window`` 个时间步。

    参数说明:
        secret: base32 密钥。
        code: 用户输入的 6 位数字。
        moment: Unix 秒;``None`` 表示当前时间。
        window: 允许的时间步偏差。

    返回参数:
        是否匹配。

    使用示例:
        ``verify(secret, "123456")``

    备注信息:
        依次比对 ``moment + offset * STEP_SECONDS`` 的码,任一命中即返回 ``True``;
        空密钥、长度不是 6 位、含非数字字符一律直接返回 ``False``,不抛异常。
        比较用 ``hmac.compare_digest`` 避免时序侧信道。
    """
    candidate = (code or "").strip()
    if not secret or len(candidate) != DIGITS or not candidate.isdigit():
        return False
    now = int(time.time() if moment is None else moment)
    for offset in range(-window, window + 1):
        expected = code_at(secret, now + offset * STEP_SECONDS)
        if hmac.compare_digest(expected, candidate):
            return True
    return False


def provisioning_uri(secret: str, account: str, issuer: str = "chat_app") -> str:
    """生成 authenticator App 可识别的 ``otpauth://`` 地址。

    参数说明:
        secret: base32 密钥。
        account: 账号标识(手机号)。
        issuer: 发行方名称。

    返回参数:
        ``otpauth://totp/...`` 字符串。

    使用示例:
        ``provisioning_uri(secret, "13800138000")``

    备注信息:
        label 与 issuer 都做 URL 编码;``algorithm`` / ``digits`` / ``period``
        直接取本模块常量,与 ``code_at`` 的实现同源,不会出现「扫进去的码对不上」。
    """
    label = quote(f"{issuer}:{account}", safe=":")
    return (f"otpauth://totp/{label}?secret={secret}"
            f"&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")
