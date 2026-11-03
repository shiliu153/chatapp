"""客户端错误上报的限流。

接口允许匿名,所以只能按 IP 计数;额度在
``settings.DEFAULT_THROTTLE_RATES["client_error"]``。
"""

from rest_framework.throttling import SimpleRateThrottle


class ClientErrorThrottle(SimpleRateThrottle):
    """按客户端 IP 限流错误上报;额度在 settings.DEFAULT_THROTTLE_RATES["client_error"]。"""

    scope = "client_error"

    def get_cache_key(self, request, view):
        """按客户端 IP 生成限流缓存键。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该 IP 在 ``client_error`` 作用域下的缓存键。
        """
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
