"""TOTP( RFC 6238 )的最小实现:运营后台的第二因子。

设计要点:
    1. 不引入第三方依赖:算法就是 HMAC-SHA1 + 时间步长,30 行足够,且便于审计;
    2. 密钥用 ``secrets`` 生成 20 字节再 base32(标准 authenticator App 可直接识别);
    3. 校验允许前后各一个时间步(±30 秒),容忍手机与服务器的小幅时钟漂移;
    4. 比较用 ``hmac.compare_digest``,避免时序侧信道。
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

    Returns:
        32 字符左右的 base32 字符串。
    """
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _decode(secret: str) -> bytes:
    """把 base32 密钥解成字节,自动补齐 padding。

    Args:
        secret: base32 字符串。

    Returns:
        原始密钥字节。

    Raises:
        ValueError: 密钥不是合法 base32。
    """
    padded = secret.upper() + "=" * (-len(secret) % 8)
    return base64.b32decode(padded, casefold=True)


def code_at(secret: str, moment: int | None = None, step: int = STEP_SECONDS) -> str:
    """计算某一时刻的 6 位验证码。

    Args:
        secret: base32 密钥。
        moment: Unix 秒;``None`` 表示当前时间。
        step: 时间步长(秒)。

    Returns:
        6 位数字字符串。
    """
    now = int(time.time() if moment is None else moment)
    counter = now // step
    digest = hmac.new(_decode(secret), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 10 ** DIGITS:0{DIGITS}d}"


def verify(secret: str, code: str, moment: int | None = None, window: int = 1) -> bool:
    """校验验证码,允许前后 ``window`` 个时间步。

    Args:
        secret: base32 密钥。
        code: 用户输入的 6 位数字。
        moment: Unix 秒;``None`` 表示当前时间。
        window: 允许的时间步偏差。

    Returns:
        是否匹配。
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

    Args:
        secret: base32 密钥。
        account: 账号标识(手机号)。
        issuer: 发行方名称。

    Returns:
        ``otpauth://totp/...`` 字符串。
    """
    label = quote(f"{issuer}:{account}", safe=":")
    return (f"otpauth://totp/{label}?secret={secret}"
            f"&issuer={quote(issuer)}&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}")
