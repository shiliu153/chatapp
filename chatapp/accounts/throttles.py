"""短信接口的限流:发码与校验各自按客户端 IP 计数。

设计要点:
    额度配在 ``settings.DEFAULT_THROTTLE_RATES``,且 ``DEBUG`` 下会放宽 ——
    两台模拟器共享宿主机的 ``127.0.0.1``,不放宽会互相把对方限流掉。
"""

from rest_framework.throttling import SimpleRateThrottle


class SmsSendThrottle(SimpleRateThrottle):
    """按 IP 限流发送验证码;额度在 settings.DEFAULT_THROTTLE_RATES["sms_send"]。"""

    scope = "sms_send"

    def get_cache_key(self, request, view):
        """按客户端 IP 生成限流缓存键。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该 IP 在 ``sms_send`` 作用域下的缓存键。
        """
        # SimpleRateThrottle 要求必须自己实现缓存键;这里按客户端 IP 计数
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class SmsVerifyThrottle(SimpleRateThrottle):
    """按 IP 限流校验验证码(防扫号);额度在 settings.DEFAULT_THROTTLE_RATES["sms_verify"]。"""

    scope = "sms_verify"

    def get_cache_key(self, request, view):
        """按客户端 IP 生成限流缓存键。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该 IP 在 ``sms_verify`` 作用域下的缓存键。
        """
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class ProbeThrottle(SimpleRateThrottle):
    """按 IP 限流探针;额度在 settings.DEFAULT_THROTTLE_RATES["probe"](L1)。"""

    scope = "probe"

    def get_cache_key(self, request, view):
        """按客户端 IP 生成限流缓存键。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该 IP 在 ``probe`` 作用域下的缓存键。
        """
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LogoutThrottle(SimpleRateThrottle):
    """按 IP 限流注销;额度在 settings.DEFAULT_THROTTLE_RATES["logout"](L-5)。

    注销本身是幂等的,但它是匿名接口且会写 token 黑名单表,必须限流防止被刷。
    """

    scope = "logout"

    def get_cache_key(self, request, view):
        """按客户端 IP 生成限流缓存键。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该 IP 在 ``logout`` 作用域下的缓存键。
        """
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
