"""腾讯云 IM userSig 生成。

坑点:腾讯用自家 base64 变体 —— 整体流程是
JSON(ver/identifier/sdkappid/expire/time/sig) → json.dumps → zlib.compress
→ 标准 base64 → 把 + / = 分别替换成 * - _。
注意 sig 字段本身用的是**标准** base64 的 HMAC-SHA256,不要一起替换。
"""

import base64
import hashlib
import hmac
import json
import time
import zlib

from django.conf import settings


def _b64_variant(raw: bytes) -> str:
    return base64.b64encode(raw).decode().replace("+", "*").replace("/", "-").replace("=", "_")


def _b64_variant_decode(text: str) -> bytes:
    return base64.b64decode(text.replace("*", "+").replace("-", "/").replace("_", "="))


def _hmac_sha256(identifier: str, sdkappid: int, curr_time: int, expire: int, key: str) -> str:
    content = (
        f"TLS.identifier:{identifier}\n"
        f"TLS.sdkappid:{sdkappid}\n"
        f"TLS.time:{curr_time}\n"
        f"TLS.expire:{expire}\n"
    )
    digest = hmac.new(key.encode(), content.encode(), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def gen_user_sig(identifier: str, expire: int | None = None, now: int | None = None) -> str:
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
    """调试用:把 userSig 还原成明文,方便在日志/测试里核对内容与有效期。"""
    return json.loads(zlib.decompress(_b64_variant_decode(sig)).decode("utf-8"))
