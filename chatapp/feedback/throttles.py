"""意见反馈接口的限流。"""

from rest_framework.throttling import SimpleRateThrottle


class FeedbackThrottle(SimpleRateThrottle):
    """按用户限流提交反馈;额度在 ``settings.DEFAULT_THROTTLE_RATES["feedback"]``。"""

    scope = "feedback"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        参数说明:
            request: DRF 请求对象。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            缓存键;未登录返回 ``None``(鉴权会先拦下)。

        使用示例:
            DRF 在每次限流检查时调用 ``throttle.get_cache_key(request, view)``,本类挂在
            ``POST /api/v1/feedback`` 上;用例见 ``feedback/tests.py`` 的 ``test_throttled``

        备注信息:
            键里的 ``ident`` 恒为 ``request.user.pk``,所以额度是按账号而不是按 IP 算的;
            未登录时返回 ``None``,父类随即放行 —— 未登录请求在权限检查阶段已返回 401。
        """
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}
