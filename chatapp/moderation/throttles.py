"""举报接口的限流。

额度见 ``settings.DEFAULT_THROTTLE_RATES["report"]``(20/天)——
举报是低频且需要人工处理的操作,额度给得比较紧。
"""

from rest_framework.throttling import SimpleRateThrottle


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
