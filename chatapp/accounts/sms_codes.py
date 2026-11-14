"""验证码状态机:HMAC 存储 + Redis Lua 原子校验。

设计要点:
    1. Redis 里只存验证码的 HMAC-SHA256 摘要(密钥取 ``SECRET_KEY``),不存明文;
    2. 「锁检查 → 取码比对 → 失败计数 → 成功标记消费」在同一个 Lua 脚本内完成,
       保证并发校验时只有一个请求能首次消费,其余走重放分支(幂等窗口)。

注意事项:
    脚本用 ``register_script`` 注册(优先 EVALSHA,脚本未缓存时自动回退 EVAL);
    修改 ``_SCRIPT_SOURCE`` 后无需手动清理 Redis 中的脚本缓存。

文件信息:
    文件名称          accounts/sms_codes.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
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

    参数说明:
        无。

    返回参数:
        django_redis 的连接对象，可用 ``hset`` / ``delete`` / ``register_script``。

    使用示例:
        ``client = _client()``

    备注信息:
        每次调用都走 django_redis 的连接池，不持有长连接，因此不需要调用方关闭。
        共用 ``default`` 别名意味着验证码与缓存、限流共享同一套淘汰与持久化配置。
    """
    return get_redis_connection("default")


def _get_script():
    """惰性注册并缓存 Lua 脚本对象。

    参数说明:
        无。

    返回参数:
        已注册的脚本对象;调用它即执行 EVALSHA(未缓存时自动回退 EVAL)。

    使用示例:
        ``raw = _get_script()(keys=[key, lock_key], args=[...])``

    备注信息:
        结果存在模块级 ``_script`` 里，第一次调用才注册；因此首次校验多一次
        ``SCRIPT LOAD`` 往返，之后都是 EVALSHA。进程未重启前不会重复注册，
        改了 ``_SCRIPT_SOURCE`` 需要重启进程才会生效。
    """
    global _script
    if _script is None:
        _script = _client().register_script(_SCRIPT_SOURCE)   # EVALSHA,失败自动回退 EVAL
    return _script


def _keys(phone: str):
    """拼出该手机号对应的验证码键与锁定键。

    参数说明:
        phone: 手机号。

    返回参数:
        ``(验证码键, 锁定键)`` 二元组，形如 ``("sms:code:<phone>", "sms:lock:<phone>")``。

    使用示例:
        ``key, lock_key = _keys("13800000000")``

    备注信息:
        两把键分开是刻意的：验证码键可被回滚删除，锁定键只在「连错超限」时由
        Lua 脚本写入，不受回滚影响。键名格式与 ``services`` 侧的发送间隔限流键不同，
        不要复用。
    """
    return f"sms:code:{phone}", f"sms:lock:{phone}"


def digest(code: str) -> str:
    """计算验证码的 HMAC-SHA256 摘要。

    参数说明:
        code: 6 位验证码明文。

    返回参数:
        十六进制摘要;Redis 中只存这个值。

    使用示例:
        ``h = digest("123456")``

    备注信息:
        密钥取 ``settings.SECRET_KEY``，因此换 ``SECRET_KEY`` 会让已下发的验证码
        全部无法通过校验（相当于全量作废）。摘要不可逆，日志里打印摘要不泄露明文。
    """
    return hmac.new(settings.SECRET_KEY.encode(), code.encode(), hashlib.sha256).hexdigest()


def store(phone: str, code: str) -> None:
    """写入验证码,并把失败计数清零。

    参数说明:
        phone: 手机号。
        code: 验证码明文,写入前会转成摘要。

    返回参数:
        无返回值。

    使用示例:
        ``store("13800000000", "123456")``

    备注信息:
        重发即覆盖：同一手机号的旧验证码同时作废，失败计数 ``n`` 与消费标记 ``c``
        一并归零。TTL 取 ``settings.SMS_CODE_TTL``，过期后校验返回 ``EXPIRED``。
        不清锁定键——正处于连错锁定期的号码，重发也不能绕过锁定。
    """
    client = _client()
    key, _ = _keys(phone)
    client.hset(key, mapping={"h": digest(code), "n": 0, "c": 0})
    client.expire(key, settings.SMS_CODE_TTL)


def delete(phone: str) -> None:
    """删除验证码键(用于短信入队失败时回滚)。

    参数说明:
        phone: 手机号。

    返回参数:
        无返回值；键不存在时静默成功。

    使用示例:
        ``delete("13800000000")``

    备注信息:
        只删验证码键,不动锁定键 —— 锁定是「连错次数超限」的结果,
        不该因为一次入队失败就被清掉。
    """
    key, _ = _keys(phone)
    _client().delete(key)


def verify(phone: str, code: str) -> CodeResult:
    """在 Redis 中原子校验验证码。

    参数说明:
        phone: 手机号。
        code: 用户提交的验证码明文。

    返回参数:
        状态机结果:``OK`` / ``EXPIRED`` / ``WRONG`` / ``JUST_LOCKED`` / ``LOCKED``。

    使用示例:
        ``result = verify("13800000000", "123456")``

    备注信息:
        锁检查、取码比对、失败计数、成功标记消费四步在同一个 Lua 脚本内完成，
        并发校验时只有一个请求能首次消费。
        连错达到 ``SMS_MAX_ATTEMPTS`` 次即写入锁定键（TTL ``SMS_LOCK_TTL``）并删码，
        本次返回 ``JUST_LOCKED``，锁定期内返回 ``LOCKED``。
        校验成功时把 ``c`` 置 1 并把 TTL 改成 ``SMS_REPLAY_TTL``（60 秒），窗口内
        重复提交同一个码仍返回 ``OK``，用于容忍客户端重试。
    """
    key, lock_key = _keys(phone)
    raw = _get_script()(
        keys=[key, lock_key],
        args=[digest(code), settings.SMS_MAX_ATTEMPTS,
              settings.SMS_LOCK_TTL, settings.SMS_REPLAY_TTL],
    )
    return CodeResult[_RESULTS[int(raw)]]
