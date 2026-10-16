"""登录接口的入参序列化与校验。

设计要点:
    ``SmsVerifySerializer`` 继承 ``PhoneSerializer``,因此校验验证码的接口同样会先
    走一遍手机号规范化(去空白 + 格式校验),两个接口的号码口径保持一致。
"""

import re

from rest_framework import serializers

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


class PhoneSerializer(serializers.Serializer):
    """只接收一个手机号的入参。"""

    phone = serializers.CharField(max_length=20)

    def validate_phone(self, value):
        """去除首尾空白并校验手机号格式。

        Args:
            value: 客户端提交的手机号。

        Returns:
            去空白后的手机号。

        Raises:
            serializers.ValidationError: 不符合中国大陆手机号格式
                (1 开头、第二位 3-9、共 11 位数字)。
        """
        value = value.strip()
        if not PHONE_RE.match(value):
            raise serializers.ValidationError("手机号格式不正确")
        return value


class SmsVerifySerializer(PhoneSerializer):
    """手机号 + 6 位验证码的入参。"""

    code = serializers.CharField(min_length=6, max_length=6)
