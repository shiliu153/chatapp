"""腾讯云 IM userSig 的生成与解码。

设计要点:
    腾讯用的是自家的 base64 变体,整体流程为:
    JSON(``TLS.ver`` / ``identifier`` / ``sdkappid`` / ``expire`` / ``time`` / ``sig``)
    → ``json.dumps`` → ``zlib.compress`` → 标准 base64 → 把 ``+`` ``/`` ``=``
    分别替换成 ``*`` ``-`` ``_``。

注意事项:
    ``TLS.sig`` 字段本身用的是**标准** base64 的 HMAC-SHA256 摘要,不要跟着一起替换;
    替换与还原只作用于最外层容器。
"""

import base64
import hashlib
import hmac
import json
import time
import zlib

from django.conf import settings


def _b64_variant(raw: bytes) -> str:
    """把字节串编码成腾讯的 base64 变体。

    Args:
        raw: 待编码的字节串。

    Returns:
        把 ``+`` / ``/`` / ``=`` 分别替换为 ``*`` / ``-`` / ``_`` 后的字符串。
    """
    return base64.b64encode(raw).decode().replace("+", "*").replace("/", "-").replace("=", "_")


def _b64_variant_decode(text: str) -> bytes:
    """把腾讯的 base64 变体还原成字节串。

    Args:
        text: base64 变体字符串。

    Returns:
        解码后的字节串。
    """
    return base64.b64decode(text.replace("*", "+").replace("-", "/").replace("_", "="))


def _hmac_sha256(identifier: str, sdkappid: int, curr_time: int, expire: int, key: str) -> str:
    """计算 userSig 的签名摘要。

    摘要内容按腾讯规定拼接:``identifier`` / ``sdkappid`` / ``time`` / ``expire``
    四行 ``TLS.*`` 文本,顺序不可变。

    Args:
        identifier: IM 账号。
        sdkappid: 应用的 SDKAppID。
        curr_time: 签发时间戳(秒)。
        expire: 有效期(秒)。
        key: 应用的密钥 ``IM_SECRETKEY``。

    Returns:
        标准 base64 编码的 HMAC-SHA256 摘要。
    """
    content = (
        f"TLS.identifier:{identifier}\n"
        f"TLS.sdkappid:{sdkappid}\n"
        f"TLS.time:{curr_time}\n"
        f"TLS.expire:{expire}\n"
    )
    digest = hmac.new(key.encode(), content.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def gen_user_sig(identifier: str, expire: int | None = None, now: int | None = None) -> str:
    """为指定 IM 账号签发 userSig。

    Args:
        identifier: IM 账号。
        expire: 有效期(秒);``None`` 表示取 ``settings.IM_SIG_EXPIRE``。
        now: 签发时间戳(秒);``None`` 表示取当前时间。测试可注入以获得稳定输出。

    Returns:
        base64 变体编码的 userSig 字符串。
    """
    sdkappid = int(settings.IM_SDKAPPID)
    expire = expire or settings.IM_SIG_EXPIRE
    curr_time = now or int(time.time())
    sig_doc = {
        "TLS.ver": "2.0",
        "TLS.identifier": identifier,
        "TLS.sdkappid": sdkappid,
        "TLS.expire": expire,
        "TLS.time": curr_time,
    }
    sig_doc["TLS.sig"] = _hmac_sha256(identifier, sdkappid, curr_time, expire, settings.IM_SECRETKEY)
    return _b64_variant(zlib.compress(json.dumps(sig_doc).encode("utf-8")))


def decode_user_sig(sig: str) -> dict:
    """调试用:把 userSig 还原成明文,方便在日志/测试里核对内容与有效期。

    Args:
        sig: ``gen_user_sig`` 生成的 userSig 字符串。

    Returns:
        含 ``TLS.identifier`` / ``TLS.expire`` / ``TLS.time`` 等字段的字典。
    """
    return json.loads(zlib.decompress(_b64_variant_decode(sig)).decode("utf-8"))
