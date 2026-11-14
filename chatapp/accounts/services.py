"""短信验证码的生成、限流与校验。

验证码本身存在 Redis(见 ``sms_codes``);真实短信发送由调用方入队 Celery
任务完成,响应路径不做任何第三方网络调用。

封闭测试期(B-1 / K-1 / B-1c)多一道白名单闸门:**库内名单**
(``accounts.PhoneAllowlist``)内的号码才能收发验证码;``.env`` 的
``SMS_PHONE_WHITELIST`` 退化为「兜底种子」。名单与种子**都空**时按
``settings.SMS_ALLOWLIST_STRICT`` 决定放行还是拒绝:开发/测试放行(否则本地和
CI 全被拦),生产拒绝(漏配名单不能让闸门静默全开,R4 M-1)。判定逻辑只在本模块
实现一次,别处不要另写。

关联文档:
    - 接口契约:docs/api/auth.md
    - 运维入口:docs/ops/runbook.md「准入名单的日常运维」

文件信息:
    文件名称          accounts/services.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import logging
import secrets

from django.conf import settings
from django.core.cache import cache

from . import allowlist, sms_codes
from .exceptions import (
    PhoneNotAllowed,
    SmsCodeExpired,
    SmsCodeWrong,
    SmsLocked,
    SmsSendTooFrequent,
)
from .validators import mask_phone

logger = logging.getLogger(__name__)


def _sent_key(phone):
    """拼出该手机号最近一次发送的限流键。

    参数说明:
        phone: 客户端提交的手机号。

    返回参数:
        形如 ``sms:send:13900009000`` 的缓存键。

    使用示例:
        ``_sent_key("13900009000")``

    备注信息:
        键按号码而不是按 IP:同一号码换设备发码也要受重发间隔约束。
    """
    return f"sms:send:{phone}"


def _strict() -> bool:
    """判断「库与种子都空」时是拒绝还是放行。

    ``settings.SMS_ALLOWLIST_STRICT`` 为空(默认)时按环境自动:生产(``DEBUG`` 为假、
    且不是测试运行)走严格模式,其余放行。显式写 ``"0"`` 一律放行(封闭测试的逃生口),
    其它非空值(``"1"``、``"true"`` 等)一律严格 —— 判断口留在「显式关闭」这一侧。

    参数说明:
        无。

    返回参数:
        真表示严格模式:名单为空时拒绝所有号码。

    使用示例:
        ``_strict()``

    备注信息:
        判定口留在「显式关闭」这一侧:只有显式写 ``"0"`` 才放行,其余非空值一律严格。
    """
    raw = str(getattr(settings, "SMS_ALLOWLIST_STRICT", "") or "").strip()
    if raw == "":
        return not settings.DEBUG and not getattr(settings, "TESTING", False)
    return raw != "0"


def ensure_phone_allowed(phone: str) -> None:
    """白名单闸门:号码不在准入名单内则直接拒绝。

    判定顺序(逐条生效,命中即返回):
        1. **库内停用** → 拒(显式停用优先于 ``.env`` 种子,否则停不掉老号码);
        2. **库内启用** → 放行;
        3. **``.env`` 种子里有** → 放行(库里还没导入时的兜底);
        4. **库或种子非空** → 拒(说明名单机制已生效,只放名单内的人);
        5. **库与种子都空 + 严格模式**(见 :func:`_strict`)→ 拒(fail-closed:
           生产漏配名单时宁可谁都进不来,也不能任意号码用固定码登录);
        6. **库与种子都空 + 非严格** → 放行(只用于开发/测试)。

    校验放在发码与校验两个入口(而不是只放在校验),好处是:非白名单号码
    既拿不到验证码、也不会在 Redis 里留下限流占位,更不会触发短信任务。

    参数说明:
        phone: 客户端提交的手机号。

    返回参数:
        无返回值;放行时正常返回,拒绝时抛 ``PhoneNotAllowed``。

    使用示例:
        ``ensure_phone_allowed("13900009000")``

    备注信息:
        该号码不在准入名单内时抛 ``PhoneNotAllowed``(含「库内已停用」与严格模式下的
        空名单)。
    """
    active, disabled = allowlist.snapshot()
    if phone in disabled:
        logger.warning("[白名单] 拒绝已停用号码 phone=%s", mask_phone(phone))
        raise PhoneNotAllowed()
    if phone in active:
        return
    if phone in settings.SMS_PHONE_WHITELIST:
        return
    if active or disabled or settings.SMS_PHONE_WHITELIST:
        logger.warning("[白名单] 拒绝非受邀号码 phone=%s", mask_phone(phone))
        raise PhoneNotAllowed()
    if _strict():
        # 生产漏配名单 = 准入机制没生效。这里必须吵:error 级进日志/告警,
        # 并拒绝准入 —— 否则「按默认值部署」就是全号码可用固定码登录。
        logger.error("[白名单] 严格模式下名单为空,拒绝所有号码(先跑 allowlist_seed_import)")
        raise PhoneNotAllowed()
    # 非严格 = 库与种子都空的开发/测试默认态:放行,避免本地和 CI 全被拦


def issue_code(phone: str) -> str:
    """生成并存储验证码。

    短信入队由调用方负责(见 ``views.sms_send``);本函数只负责限流、
    生成、落库三步。验证码用 ``secrets`` 生成(CSPRNG);只有开发模式才把
    验证码写进日志 —— 接入真实短信商后日志里不能再出现明文码(H-3)。

    参数说明:
        phone: 手机号,同时作为发送间隔限流的键。

    返回参数:
        本次生成的 6 位验证码;开发模式下固定为 ``settings.SMS_DEV_CODE``。

    使用示例:
        ``code = issue_code("13900009000")``

    备注信息:
        距上次发送不足 ``SMS_RESEND_INTERVAL`` 秒时抛 ``SmsSendTooFrequent``;
        本函数只负责限流、生成、落库三步,短信入队由调用方负责。
    """
    if not cache.add(_sent_key(phone), 1, settings.SMS_RESEND_INTERVAL):
        raise SmsSendTooFrequent(wait=settings.SMS_RESEND_INTERVAL)
    code = (settings.SMS_DEV_CODE if settings.SMS_DEV_MODE
            else f"{secrets.randbelow(1_000_000):06d}")
    sms_codes.store(phone, code)
    if settings.SMS_DEV_MODE:
        logger.info("[开发模式] 验证码 phone=%s code=%s", mask_phone(phone), code)
    return code


def rollback_send(phone: str) -> None:
    """短信任务入队失败时回滚。

    删掉限流占位与验证码,让用户能立刻重试(见 ``views.sms_send`` 的异常分支)。

    参数说明:
        phone: 手机号。

    返回参数:
        无返回值。

    使用示例:
        ``rollback_send("13900009000")``

    备注信息:
        删掉限流占位与验证码,让用户能立刻重试(见 ``views.sms_send`` 的异常分支);
        两项都不存在时也照常返回,幂等。
    """
    cache.delete(_sent_key(phone))
    sms_codes.delete(phone)


def check_code(phone: str, code: str) -> None:
    """校验验证码,成功即通过。

    含 60 秒重放窗口内的重复校验:窗口内重复提交同一个码仍算成功。

    参数说明:
        phone: 手机号。
        code: 用户提交的 6 位验证码。

    返回参数:
        无返回值;校验通过即正常返回。

    使用示例:
        ``check_code("13900009000", "123456")``

    备注信息:
        验证码已过期或不存在抛 ``SmsCodeExpired``;验证码错误抛 ``SmsCodeWrong``;
        连错次数超限抛 ``SmsLocked``。
    """
    result = sms_codes.verify(phone, code)
    if result is sms_codes.CodeResult.EXPIRED:
        raise SmsCodeExpired()
    if result is sms_codes.CodeResult.WRONG:
        raise SmsCodeWrong()
    if result in (sms_codes.CodeResult.LOCKED, sms_codes.CodeResult.JUST_LOCKED):
        raise SmsLocked(wait=settings.SMS_LOCK_TTL)
