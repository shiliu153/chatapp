"""手机号格式的唯一判定口径。

为什么单独放一个模块:手机号同时被三处校验 —— App/Web 的登录接口
(``accounts.serializers``)、审核台的准入名单表单(``ops.forms``)、准入名单的
管理命令。口径必须只有一份,否则「能加进名单但登录报格式错」这种事迟早发生。

判定规则 = 中国大陆手机号:1 开头、第二位 3–9、共 11 位数字;
脱敏(``138****8000``)也放在这里,日志与审核台提示共用同一份。

文件信息:
    文件名称          accounts/validators.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import re

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


def is_valid_phone(value: str) -> bool:
    """判断一个字符串是否符合手机号格式(不含去空白,调用方自己 strip)。

    参数说明:
        value: 待校验的手机号字符串。

    返回参数:
        符合规则为 ``True``,否则 ``False``。

    使用示例:
        ``is_valid_phone("13800138000")``

    备注信息:
        正则只认中国大陆手机号:1 开头、第二位 3–9、共 11 位数字;
        前后带空格按不合法返回 ``False``(本函数不做 strip);传入 ``None``
        或非字符串时 ``re.match`` 抛 ``TypeError``,调用方需先保证类型。
    """
    return bool(PHONE_RE.match(value))


def mask_phone(phone: str) -> str:
    """把手机号脱敏成 ``138****8000``,日志与审核台提示里不再出现完整号码。

    参数说明:
        phone: 原始手机号字符串。

    返回参数:
        脱敏后的手机号;长度不足 7 位时原样返回。

    使用示例:
        ``mask_phone("13800138000")``

    备注信息:
        只做字符串切片,不校验格式 —— 非法号码也能脱敏,便于日志里统一打码;
        空串返回空串,不抛异常。
    """
    if len(phone) < 7:
        return phone
    return f"{phone[:3]}****{phone[-4:]}"
