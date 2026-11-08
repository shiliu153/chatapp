"""IM token 的签发与校验(HS256,与 C++ 服务端共享密钥)。

payload 里两个与多端在线相关的 claim:``sv`` 是**该端**的会话版本,``ct`` 是端类型
(``app`` / ``web``)。imserver 按 ``(uid, ct)`` 查端会话行比对 ``sv``,因此一个 App +
一个网页可以同时在线,同类端第二次登录才会把前一个顶掉。
"""

import time
import uuid

import jwt
from django.conf import settings


def mint_im_token(user_id: int, ttl: int, session_version: int = 0,
                  client_type: str = "app") -> str:
    """签发一个 IM token。

    Args:
        user_id: 账号 id。
        ttl: 有效期(秒)。
        session_version: 签发时**该端**的会话版本;imserver 用它拒绝被顶下线的旧 token(H3)。
        client_type: ``app`` 或 ``web``;imserver 按它查端会话行。

    Returns:
        HS256 JWT 字符串(payload 含 ``sv`` 与 ``ct``)。
    """
    now = int(time.time())
    return jwt.encode(
        {
            "sub": f"u{user_id}",
            "uid": user_id,
            "iat": now,
            "exp": now + ttl,
            "jti": uuid.uuid4().hex,
            "sv": int(session_version),
            "ct": client_type,
        },
        settings.IM_SELF_SECRET,
        algorithm="HS256",
    )


def verify_im_token(token: str) -> dict | None:
    """校验 IM token。

    Args:
        token: 待校验的 JWT。

    Returns:
        校验通过时返回 claims 字典,否则返回 ``None``。
    """
    try:
        claims = jwt.decode(token, settings.IM_SELF_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if claims.get("sub") != f"u{claims.get('uid')}":
        return None
    return claims
