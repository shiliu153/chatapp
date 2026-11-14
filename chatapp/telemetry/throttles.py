"""客户端错误上报的限流。

接口允许匿名,所以只能按 IP 计数;额度在
``settings.DEFAULT_THROTTLE_RATES["client_error"]``。

文件信息:
    文件名称          telemetry/throttles.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from rest_framework.throttling import SimpleRateThrottle


class ClientErrorThrottle(SimpleRateThrottle):
    """按客户端 IP 限流错误上报;额度在 settings.DEFAULT_THROTTLE_RATES["client_error"]。

    参数说明:
        无。DRF 通过 ``throttle_classes`` 自行实例化,不传构造参数。

    返回参数:
        ``ClientErrorThrottle`` 实例;超额时 DRF 抛 ``Throttled``,接口回 429。

    使用示例:
        ``@throttle_classes([ClientErrorThrottle])``

    备注信息:
        接口允许匿名,认证用户与匿名用户统一按 IP 计数,不按账号区分。
    """

    scope = "client_error"

    def get_cache_key(self, request, view):
        """按客户端 IP 生成限流缓存键。

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该 IP 在 ``client_error`` 作用域下的缓存键。

        使用示例:
            ``self.get_cache_key(request, view)``

        备注信息:
            ``get_ident`` 的取值受 ``NUM_PROXIES`` 与代理头影响,生产必须与反向代理层数一致。
        """
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
