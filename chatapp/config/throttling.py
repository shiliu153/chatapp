"""按登录用户计数的限流基类。

设计要点:
    新增的「按用户」限流只需要声明 ``scope``,缓存键与额度读取逻辑都在基类里;
    额度统一在 ``settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`` 中配置。

文件信息:
    文件名称          config/throttling.py
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


class UserScopedThrottle(SimpleRateThrottle):
    """按用户 id 生成限流键;子类只需声明 ``scope``。

    参数说明:
        无(继承 DRF ``SimpleRateThrottle``,不自定义 ``__init__``)。

    返回参数:
        限流器实例本身;DRF 按 ``DEFAULT_THROTTLE_CLASSES`` 或视图的
        ``throttle_classes`` 实例化它。

    使用示例:
        ``class ImSendThrottle(UserScopedThrottle): scope = "im_send"``

    备注信息:
        额度统一从 ``settings.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"][scope]`` 读取,
        子类漏配 scope 时 DRF 在首次取额度时抛 ``ImproperlyConfigured``。
    """

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该用户在 ``scope`` 作用域下的缓存键。

        使用示例:
            ``throttle.get_cache_key(request, view)``

        备注信息:
            键里只带 ``scope`` 与用户 id,同一用户在不同接口上的额度互不影响;
            未登录请求的 ``user.id`` 为 ``None``,因此本基类只用于已登录接口。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
