"""资料相关接口的限流。

目前只有在线状态查询需要限流:一个前台页面约每小时轮询 80 次,
额度见 ``settings.DEFAULT_THROTTLE_RATES["presence"]``。
"""

from rest_framework.throttling import SimpleRateThrottle


class PresenceThrottle(SimpleRateThrottle):
    """按用户限流在线状态查询;额度在 settings.DEFAULT_THROTTLE_RATES["presence"]。"""

    scope = "presence"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        与短信接口按 IP 限流不同:在线状态是登录后才会调用的接口,
        按用户计数比按 IP 更准确(同一出口 IP 可能有多台设备)。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该用户在 ``presence`` 作用域下的缓存键。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
