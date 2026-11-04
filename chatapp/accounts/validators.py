"""手机号格式的唯一判定口径。

为什么单独放一个模块:手机号同时被三处校验 —— App/Web 的登录接口
(``accounts.serializers``)、审核台的准入名单表单(``ops.forms``)、准入名单的
管理命令。口径必须只有一份,否则「能加进名单但登录报格式错」这种事迟早发生。

判定规则 = 中国大陆手机号:1 开头、第二位 3–9、共 11 位数字;
脱敏(``138****8000``)也放在这里,日志与审核台提示共用同一份。
"""

import re

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


def is_valid_phone(value: str) -> bool:
    """判断一个字符串是否符合手机号格式(不含去空白,调用方自己 strip)。

    Args:
        value: 待校验的手机号。

    Returns:
        符合规则为 ``True``。
    """
    return bool(PHONE_RE.match(value))


def mask_phone(phone: str) -> str:
    """把手机号脱敏成 ``138****8000``,日志与审核台提示里不再出现完整号码。

    Args:
        phone: 原始手机号。

    Returns:
        脱敏后的手机号;长度不足 7 位时原样返回。
    """
    if len(phone) < 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"
