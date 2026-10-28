"""举报接口的限流。

额度见 ``settings.DEFAULT_THROTTLE_RATES["report"]``(20/天)——
举报是低频且需要人工处理的操作,额度给得比较紧。
"""

from rest_framework.throttling import SimpleRateThrottle

from config.throttling import UserScopedThrottle


class BlockThrottle(UserScopedThrottle):
    """按用户限流拉黑写操作;额度见 ``settings.DEFAULT_THROTTLE_RATES["blocks"]``。"""

    scope = "blocks"

    def allow_request(self, request, view):
        """只对 POST 计数,看黑名单列表不限流。

        Args:
            request: 当前请求。
            view: 当前视图。

        Returns:
            非 POST 时恒为 ``True``,否则走父类的额度判定。
        """
        if request.method != "POST":
            return True
        return super().allow_request(request, view)


class ReportThrottle(SimpleRateThrottle):
    """按用户限流举报;额度在 settings.DEFAULT_THROTTLE_RATES["report"]。"""

    scope = "report"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该用户在 ``report`` 作用域下的缓存键。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
