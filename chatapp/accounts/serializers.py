import re

from rest_framework import serializers

PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


class PhoneSerializer(serializers.Serializer):
    phone = serializers.CharField(max_length=20)

    def validate_phone(self, value):
        value = value.strip()
        if not PHONE_RE.match(value):
            raise serializers.ValidationError("手机号格式不正确")
        return value


class SmsVerifySerializer(PhoneSerializer):
    code = serializers.CharField(min_length=6, max_length=6)
