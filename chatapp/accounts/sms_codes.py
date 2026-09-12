"""验证码状态机:HMAC 存储 + Redis Lua 原子校验。

一个脚本内完成「锁检查 → 取码比对 → 失败计数 → 成功标记消费」,
并发 verify 只有一个能"首次消费",其余走重放分支(幂等窗口)。
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
    return get_redis_connection("default")


def _get_script():
    global _script
    if _script is None:
        _script = _client().register_script(_SCRIPT_SOURCE)   # EVALSHA,失败自动回退 EVAL
    return _script


def _keys(phone: str):
    return f"sms:code:{phone}", f"sms:lock:{phone}"


def digest(code: str) -> str:
    return hmac.new(settings.SECRET_KEY.encode(), code.encode(), hashlib.sha256).hexdigest()


def store(phone: str, code: str) -> None:
    client = _client()
    key, _ = _keys(phone)
    client.hset(key, mapping={"h": digest(code), "n": 0, "c": 0})
    client.expire(key, settings.SMS_CODE_TTL)


def delete(phone: str) -> None:
    key, _ = _keys(phone)
    _client().delete(key)


def verify(phone: str, code: str) -> CodeResult:
    key, lock_key = _keys(phone)
    raw = _get_script()(
        keys=[key, lock_key],
        args=[digest(code), settings.SMS_MAX_ATTEMPTS,
              settings.SMS_LOCK_TTL, settings.SMS_REPLAY_TTL],
    )
    return CodeResult[_RESULTS[int(raw)]]
