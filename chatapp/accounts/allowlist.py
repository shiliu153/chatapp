"""准入名单的读侧:一份带短 TTL 的**自证签名**快照 + 写路径的显式失效。

为什么要有这一层(而不是在 ``services.ensure_phone_allowed`` 里直接查库):
    白名单闸门在「发码」与「校验」两个入口各跑一次,每次请求都查一次
    ``accounts.PhoneAllowlist`` 没必要。这里把整张表读成两个集合(启用 / 停用)
    缓存在 Django cache 里,一次请求零查询。

为什么快照要带签名(R4-A1):
    名单缓存本身就是一条准入绕过通道 —— 能改 Redis 的人把某个号码塞进启用集合,
    就能越过白名单直接登录。缓存序列化已由 ``config/settings.py`` 切成 JSON(pickle
    反序列化面已关闭),但「攻击者仍能写 JSON」这件事没变,所以缓存值必须自证。
    值形如 ``{"active": [...], "disabled": [...], "sig": "<hex>"}``,``sig`` 是用
    ``SECRET_KEY`` 派生的 key 做的 HMAC-SHA256;读侧结构不对、类型不对或签名不符,
    一律 ``logger.warning`` 后**当作未命中**去查库回填,绝不放行未签名内容 ——
    伪造者没有 ``SECRET_KEY`` 就造不出可用的快照。

「立刻生效」靠什么保证:
    不靠 TTL,靠写路径调用 :func:`invalidate` —— ``/ops/`` 的加号/停用与
    种子导入命令都会显式清缓存。TTL 只是兜底(手改数据库、多进程缓存不同步时)。

注意事项:
    缓存不可用(Redis 抖动)时**不能**因此放行或拒绝:这里退化为直接查库,
    准入判断永远以数据库为准。宁可慢一次,不可漏一个人。
"""

import hashlib
import hmac
import logging

from django.conf import settings
from django.core.cache import cache

from .models import PhoneAllowlist

logger = logging.getLogger(__name__)

# 快照缓存键;写路径一律用 invalidate() 清,不要自己去拼这个键。
ALLOWLIST_CACHE_KEY = "sms:allowlist:snapshot"


def _signing_key() -> bytes:
    """从 ``SECRET_KEY`` 派生出快照专用的 HMAC key。

    不直接把 ``SECRET_KEY`` 当 HMAC key:派生一次让「名单签名」与其它用途的密钥
    互不牵连,``SECRET_KEY`` 轮换时签名自然跟着变。

    Returns:
        32 字节摘要,仅用于本模块的 HMAC-SHA256。
    """
    return hashlib.sha256(f"allowlist:{settings.SECRET_KEY}".encode()).digest()


def _payload(active, disabled) -> bytes:
    """把两个集合拼成唯一的签名载荷。

    每条记录前置组别标记(``a:`` / ``d:``),再用 ``\\x00`` 拼接。加标记是为了
    消除「active 末尾 + disabled 开头」的歧义:只按 ``\\x00`` 拼接时,
    ``active=["1"], disabled=["23"]`` 与 ``active=["1","23"], disabled=[]``
    会算出同一个载荷,同一个签名就能同时罩住两种不同的名单。手机号里不含
    ``\\x00``,所以分隔符本身不会与数据混淆。

    Args:
        active: 启用号码的可迭代对象。
        disabled: 停用号码的可迭代对象。

    Returns:
        待签名的 UTF-8 字节串。
    """
    parts = [f"a:{phone}" for phone in sorted(active)]
    parts += [f"d:{phone}" for phone in sorted(disabled)]
    return "\x00".join(parts).encode()


def _sign(active, disabled) -> str:
    """算出快照签名。

    Args:
        active: 启用号码的可迭代对象。
        disabled: 停用号码的可迭代对象。

    Returns:
        HMAC-SHA256 的十六进制摘要(小写,64 字符)。
    """
    return hmac.new(_signing_key(), _payload(active, disabled), hashlib.sha256).hexdigest()


def _verify_snapshot(cached):
    """校验缓存里读出来的快照,通过才还原成两个 ``frozenset``。

    Args:
        cached: ``cache.get`` 的返回值,理想形态是带 ``sig`` 的 dict。

    Returns:
        通过校验则返回 ``(active, disabled)`` 两个 ``frozenset``;结构不对、
        类型不对或签名不符一律返回 ``None``(调用方按未命中处理,即查库回填)。
    """
    if not isinstance(cached, dict):
        logger.warning("[白名单] 快照结构异常(非 dict),视为未命中 type=%s",
                       type(cached).__name__)
        return None
    active = cached.get("active")
    disabled = cached.get("disabled")
    signature = cached.get("sig")
    if (not isinstance(active, list) or not isinstance(disabled, list)
            or not isinstance(signature, str)):
        logger.warning("[白名单] 快照结构异常(字段缺失或类型不对),视为未命中")
        return None
    if not all(isinstance(phone, str) for phone in active + disabled):
        logger.warning("[白名单] 快照结构异常(号码不是字符串),视为未命中")
        return None
    try:
        matches = hmac.compare_digest(_sign(active, disabled), signature)
    except TypeError:      # sig 里混进非 ASCII 字符时 compare_digest 会抛,一样按未命中
        matches = False
    if not matches:
        logger.warning("[白名单] 快照签名不符,视为未命中(疑似缓存被改)")
        return None
    return frozenset(active), frozenset(disabled)


def _query_snapshot():
    """直接查库,把名单拆成「启用集合」与「停用集合」。

    Returns:
        ``(active, disabled)`` 两个 ``frozenset``;表为空时都是空集。
    """
    active = set()
    disabled = set()
    for phone, is_active in PhoneAllowlist.objects.values_list("phone", "is_active"):
        (active if is_active else disabled).add(phone)
    return frozenset(active), frozenset(disabled)


def snapshot():
    """取名单快照(优先读缓存,未命中或验签失败则查库并回填)。

    Returns:
        ``(active, disabled)`` 两个 ``frozenset``。

    Raises:
        django.db.Error: 缓存未命中且数据库不可读时向上抛 —— 发码链路本就依赖
            Redis 与数据库,这里不做「出错就放行」的兜底。
    """
    try:
        cached = cache.get(ALLOWLIST_CACHE_KEY)
    except Exception:      # 缓存后端故障不影响准入判断,退化为查库
        logger.warning("[白名单] 快照缓存读取失败,改为直查数据库", exc_info=True)
        cached = None
    restored = _verify_snapshot(cached) if cached is not None else None
    if restored is not None:
        return restored
    result = _query_snapshot()
    payload = {
        "active": sorted(result[0]),
        "disabled": sorted(result[1]),
        "sig": _sign(result[0], result[1]),
    }
    try:
        cache.set(ALLOWLIST_CACHE_KEY, payload, settings.SMS_ALLOWLIST_CACHE_TTL)
    except Exception:      # 写缓存失败只影响下一次请求的性能,不影响正确性
        logger.warning("[白名单] 快照缓存写入失败", exc_info=True)
    return result


def invalidate():
    """清掉名单快照,让下一次判定立刻按最新数据库内容走。

    所有写名单的路径(``/ops/`` 加号、启停、种子导入命令)都必须调用。
    """
    try:
        cache.delete(ALLOWLIST_CACHE_KEY)
    except Exception:      # 清不掉只能靠 TTL 兜底,但要留下痕迹
        logger.warning("[白名单] 快照缓存清除失败,将依赖 TTL 兜底", exc_info=True)
