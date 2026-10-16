"""验证码状态机:HMAC 存储 + Redis Lua 原子校验。

设计要点:
    1. Redis 里只存验证码的 HMAC-SHA256 摘要(密钥取 ``SECRET_KEY``),不存明文;
    2. 「锁检查 → 取码比对 → 失败计数 → 成功标记消费」在同一个 Lua 脚本内完成,
       保证并发校验时只有一个请求能首次消费,其余走重放分支(幂等窗口)。

注意事项:
    脚本用 ``register_script`` 注册(优先 EVALSHA,脚本未缓存时自动回退 EVAL);
    修改 ``_SCRIPT_SOURCE`` 后无需手动清理 Redis 中的脚本缓存。
"""

import hashlib
import hmac
from enum import Enum

from django.conf import settings
from django_redis import get_redis_connection

_SCRIPT_SOURCE = """
local code_key = KEYS[1]
local lock_key = KEYS[2]
if redis.call('EXISTS', lock_key) == 1 then
  return 4
end
if redis.call('EXISTS', code_key) == 0 then
  return 1
end
local saved = redis.call('HGET', code_key, 'h')
if saved ~= ARGV[1] then
  local n = redis.call('HINCRBY', code_key, 'n', 1)
  if n >= tonumber(ARGV[2]) then
    redis.call('SET', lock_key, '1', 'EX', tonumber(ARGV[3]))
    redis.call('DEL', code_key)
    return 3
  end
  return 2
end
redis.call('HSET', code_key, 'c', '1')
redis.call('EXPIRE', code_key, tonumber(ARGV[4]))
return 0
"""

_RESULTS = {0: "OK", 1: "EXPIRED", 2: "WRONG", 3: "JUST_LOCKED", 4: "LOCKED"}

CodeResult = Enum("CodeResult", "OK EXPIRED WRONG JUST_LOCKED LOCKED")

_script = None


def _client():
    """取默认 Redis 连接(与缓存、限流共用同一个 DB)。

    Returns:
        django_redis 的连接对象。
    """
    return get_redis_connection("default")


def _get_script():
    """惰性注册并缓存 Lua 脚本对象。

    Returns:
        已注册的脚本对象;调用它即执行 EVALSHA(未缓存时自动回退 EVAL)。
    """
    global _script
    if _script is None:
        _script = _client().register_script(_SCRIPT_SOURCE)   # EVALSHA,失败自动回退 EVAL
    return _script


def _keys(phone: str):
    """拼出该手机号对应的验证码键与锁定键。

    Args:
        phone: 手机号。

    Returns:
        ``(验证码键, 锁定键)``。
    """
    return f"sms:code:{phone}", f"sms:lock:{phone}"


def digest(code: str) -> str:
    """计算验证码的 HMAC-SHA256 摘要。

    Args:
        code: 6 位验证码明文。

    Returns:
        十六进制摘要;Redis 中只存这个值。
    """
    return hmac.new(settings.SECRET_KEY.encode(), code.encode(), hashlib.sha256).hexdigest()


def store(phone: str, code: str) -> None:
    """写入验证码,并把失败计数清零。

    Args:
        phone: 手机号。
        code: 验证码明文,写入前会转成摘要。
    """
    client = _client()
    key, _ = _keys(phone)
    client.hset(key, mapping={"h": digest(code), "n": 0, "c": 0})
    client.expire(key, settings.SMS_CODE_TTL)


def delete(phone: str) -> None:
    """删除验证码键(用于短信入队失败时回滚)。

    只删验证码键,不动锁定键 —— 锁定是「连错次数超限」的结果,
    不该因为一次入队失败就被清掉。

    Args:
        phone: 手机号。
    """
    key, _ = _keys(phone)
    _client().delete(key)


def verify(phone: str, code: str) -> CodeResult:
    """在 Redis 中原子校验验证码。

    Args:
        phone: 手机号。
        code: 用户提交的验证码明文。

    Returns:
        状态机结果:``OK`` / ``EXPIRED`` / ``WRONG`` / ``JUST_LOCKED`` / ``LOCKED``。
    """
    key, lock_key = _keys(phone)
    raw = _get_script()(
        keys=[key, lock_key],
        args=[digest(code), settings.SMS_MAX_ATTEMPTS,
              settings.SMS_LOCK_TTL, settings.SMS_REPLAY_TTL],
    )
    return CodeResult[_RESULTS[int(raw)]]
