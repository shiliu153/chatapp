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

        参数说明:
            request: 当前请求。
            view: 当前视图。

        返回参数:
            非 POST 时恒为 ``True``,否则走父类的额度判定。

        使用示例:
            视图上挂 ``@throttle_classes([BlockThrottle])``(见 ``moderation/views.py`` 的 ``blocks``),
            由 DRF 逐请求调用;超限用例见 ``moderation/tests.py`` 的 ``BlockApiTests.test_block_write_throttled``

        备注信息:
            额度见 ``settings.DEFAULT_THROTTLE_RATES["blocks"]``(默认 60/小时,``BLOCK_RATE`` 可覆盖);
            父类返回 ``False`` 时
            由 DRF 的 ``check_throttles`` 抛 ``Throttled``(429)。GET 列表不计数,否则反复刷黑名单
            页会把自己的写额度耗尽。
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

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该用户在 ``report`` 作用域下的缓存键。

        使用示例:
            ``cache_key = self.get_cache_key(request, view)``(由 ``SimpleRateThrottle.allow_request``
            内部调用;本类挂在 ``moderation/views.py`` 的 ``create_report`` 上)

        备注信息:
            不复用父类的 ``get_ident`` 是因为它按 IP 计数,而举报额度要按账号算;
            ``self.cache_format`` 自带 ``scope`` 前缀,不同作用域互不覆盖。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
