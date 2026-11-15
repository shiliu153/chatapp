"""客户端错误上报的限流。

接口允许匿名,所以只能按 IP 计数;额度在
``settings.DEFAULT_THROTTLE_RATES["client_error"]``。
"""

from rest_framework.throttling import SimpleRateThrottle


class ClientErrorThrottle(SimpleRateThrottle):
    """按客户端 IP 限流错误上报;额度在 ``settings.DEFAULT_THROTTLE_RATES["client_error"]``。"""

    scope = "client_error"

    def get_cache_key(self, request, view):
        """按客户端 IP 生成限流缓存键。

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该 IP 在 ``client_error`` 作用域下的缓存键。

        使用示例:
            DRF 在每次限流检查时调用 ``throttle.get_cache_key(request, view)``,本类挂在
            ``POST /api/v1/client-errors`` 上;真实请求形态见 ``telemetry/tests.py`` 的
            ``self.client.post(URL, {"platform": "web", "message": "boom"}, format="json")``

        备注信息:
            键里的 ``ident`` 取自 ``self.get_ident(request)``(客户端 IP):接口允许匿名,
            没有 user 可作 ident,只能按 IP 计数。额度读
            ``settings.DEFAULT_THROTTLE_RATES["client_error"]``。
        """
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
