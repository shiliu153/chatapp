"""按登录用户计数的限流基类。

设计要点:
    新增的「按用户」限流只需要声明 ``scope``,缓存键与额度读取逻辑都在基类里;
    额度统一在 ``settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`` 中配置。
"""

from rest_framework.throttling import SimpleRateThrottle


class UserScopedThrottle(SimpleRateThrottle):
    """按用户 id 生成限流键;子类只需声明 ``scope``。"""

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该用户在 ``scope`` 作用域下的缓存键。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
