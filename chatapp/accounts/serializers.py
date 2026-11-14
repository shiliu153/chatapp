"""登录接口的入参序列化与校验。

设计要点:
    ``SmsVerifySerializer`` 继承 ``PhoneSerializer``,因此校验验证码的接口同样会先
    走一遍手机号规范化(去空白 + 格式校验),两个接口的号码口径保持一致;
    格式规则本身在 ``accounts.validators``(审核台名单表单用的是同一份)。

文件信息:
    文件名称          accounts/serializers.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from rest_framework import serializers

from .validators import PHONE_RE


class PhoneSerializer(serializers.Serializer):
    """只接收一个手机号的入参。

    参数说明:
        **kwargs: 透传给 ``serializers.Serializer`` 的初始化参数
            (``data``、``context`` 等)。

    返回参数:
        序列化器实例;校验通过后 ``validated_data`` 里是去空白后的手机号。

    使用示例:
        ``PhoneSerializer(data={"phone": " 13900009000 "}).is_valid(raise_exception=True)``

    备注信息:
        只做入参校验,不落库;号码格式规则见 ``accounts.validators.PHONE_RE``。
    """

    phone = serializers.CharField(max_length=20)

    def validate_phone(self, value):
        """去除首尾空白并校验手机号格式。

        参数说明:
            value: 客户端提交的手机号。

        返回参数:
            去空白后的手机号。

        使用示例:
            ``serializer.validate_phone(" 13900009000 ")``

        备注信息:
            不符合中国大陆手机号格式(1 开头、第二位 3-9、共 11 位数字)时抛
            ``serializers.ValidationError``。
        """
        value = value.strip()
        if not PHONE_RE.match(value):
            raise serializers.ValidationError("手机号格式不正确")
        return value


class SmsVerifySerializer(PhoneSerializer):
    """手机号 + 6 位验证码的入参。

    参数说明:
        **kwargs: 透传给 ``serializers.Serializer`` 的初始化参数
            (``data``、``context`` 等)。

    返回参数:
        序列化器实例;``validated_data`` 里是 ``phone``(已规范化)与 ``code``。

    使用示例:
        ``SmsVerifySerializer(data={"phone": "13900009000", "code": "123456"})``

    备注信息:
        ``phone`` 的规范化与格式校验继承自 ``PhoneSerializer``,两个接口口径一致;
        ``code`` 只校验长度 6 位,内容正确性由 ``accounts.services.check_code`` 判定。
    """

    code = serializers.CharField(min_length=6, max_length=6)
