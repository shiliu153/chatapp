"""IM token 的签发与校验(HS256,与 C++ 服务端共享密钥)。

payload 里两个与多端在线相关的 claim:``sv`` 是**该端**的会话版本,``ct`` 是端类型
(``app`` / ``web``)。imserver 按 ``(uid, ct)`` 查端会话行比对 ``sv``,因此一个 App +
一个网页可以同时在线,同类端第二次登录才会把前一个顶掉。

文件信息:
    文件名称          im/token.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import time
import uuid

import jwt
from django.conf import settings


def mint_im_token(user_id: int, ttl: int, session_version: int = 0,
                  client_type: str = "app") -> str:
    """签发一个 IM token。

    参数说明:
        user_id: 账号 id,payload 里落成 ``uid`` 与 ``sub=u{user_id}``。
        ttl: 有效期(秒),与 ``iat`` 相加得到 ``exp``。
        session_version: 签发时**该端**的会话版本;imserver 用它拒绝被顶下线的旧 token(H3)。
        client_type: ``app`` 或 ``web``;imserver 按它查端会话行。

    返回参数:
        HS256 JWT 字符串(payload 含 ``sub`` / ``uid`` / ``iat`` / ``exp`` /
        ``jti`` / ``sv`` / ``ct``)。

    使用示例:
        ``token = mint_im_token(42, 7200, 3, "web")``

    备注信息:
        密钥取 ``settings.IM_SELF_SECRET``,与 C++ imserver 共享同一份;``jti`` 用随机
        uuid 保证同一秒内签发的多个 token 互不相同。``session_version`` 会强制转 ``int``,
        传入 ``None`` 会抛 ``TypeError``,调用方需保证取到真实版本。
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

    参数说明:
        token: 待校验的 JWT 字符串。

    返回参数:
        校验通过时返回 claims 字典,否则返回 ``None``。

    使用示例:
        ``claims = verify_im_token(raw_token)``

    备注信息:
        签名或有效期不合规时 ``jwt.decode`` 抛 ``PyJWTError``(含过期、算法不符),
        一律吞掉并返回 ``None``,不向调用方抛异常。``sub`` 必须等于 ``u{uid}`` 才算通过,
        防止伪造 ``sub`` 与 ``uid`` 不一致的令牌。
    """
    try:
        claims = jwt.decode(token, settings.IM_SELF_SECRET, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if claims.get("sub") != f"u{claims.get('uid')}":
        return None
    return claims
