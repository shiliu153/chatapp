"""意见反馈接口的限流。"""

from rest_framework.throttling import SimpleRateThrottle


class FeedbackThrottle(SimpleRateThrottle):
    """按用户限流提交反馈;额度在 settings.DEFAULT_THROTTLE_RATES["feedback"]。"""

    scope = "feedback"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        Args:
            request: DRF 请求对象。
            view: 当前视图。

        Returns:
            缓存键;未登录返回 ``None``(鉴权会先拦下)。
        """
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}
