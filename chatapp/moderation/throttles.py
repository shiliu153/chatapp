"""举报与拉黑接口的限流。

每个类只声明 ``scope``,额度统一在 ``settings.DEFAULT_THROTTLE_RATES`` 里配置:
举报 20/天(低频且需要人工处理,额度给得比较紧);拉黑与解除拉黑各 60/小时
(关系变更会连带 IM 黑名单同步与配对查库,单账号无节制调用等于写入放大器)。
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


class UnblockThrottle(UserScopedThrottle):
    """按用户限流解除拉黑;额度见 ``settings.DEFAULT_THROTTLE_RATES["unblock"]``。

    该视图只有 DELETE 一种方法,因此不需要像 ``BlockThrottle`` 那样按方法分支放行。
    """

    scope = "unblock"


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
