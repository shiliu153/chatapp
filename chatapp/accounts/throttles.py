from rest_framework.throttling import SimpleRateThrottle


class SmsSendThrottle(SimpleRateThrottle):
    """按 IP 限流发送验证码;额度在 settings.DEFAULT_THROTTLE_RATES["sms_send"]。"""

    scope = "sms_send"

    def get_cache_key(self, request, view):
        # SimpleRateThrottle 要求必须自己实现缓存键;这里按客户端 IP 计数
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
