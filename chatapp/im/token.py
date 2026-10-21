"""IM token 的签发与校验(HS256,与 C++ 服务端共享密钥)。"""

import time
import uuid

import jwt
from django.conf import settings


def mint_im_token(user_id: int, ttl: int) -> str:
    """签发一个 IM token。

    Args:
        user_id: 账号 id。
        ttl: 有效期(秒)。

    Returns:
        HS256 JWT 字符串。
    """
    now = int(time.time())
    return jwt.encode(
        {
            "sub": f"u{user_id}",
            "uid": user_id,
            "iat": now,
            "exp": now + ttl,
            "jti": uuid.uuid4().hex,
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
