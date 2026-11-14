"""意见反馈接口的限流。

文件信息:
    文件名称          feedback/throttles.py
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


class FeedbackThrottle(SimpleRateThrottle):
    """按用户限流提交反馈;额度在 settings.DEFAULT_THROTTLE_RATES["feedback"]。

    参数说明:
        无。DRF 通过 ``throttle_classes`` 自行实例化,不传构造参数。

    返回参数:
        ``FeedbackThrottle`` 实例;超额时 DRF 抛 ``Throttled``,接口回 429。

    使用示例:
        ``@throttle_classes([FeedbackThrottle])``

    备注信息:
        计数落在 ``scope = "feedback"`` 的缓存键上,额度由 ``DEFAULT_THROTTLE_RATES`` 决定。
    """

    scope = "feedback"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        参数说明:
            request: DRF 请求对象。
            view: 当前视图;DRF 要求传入,此处不使用。

        返回参数:
            缓存键字符串;未登录返回 ``None``(鉴权会先拦下)。

        使用示例:
            ``self.get_cache_key(request, view)``

        备注信息:
            返回 ``None`` 时 DRF 不做限流,但未登录请求在鉴权阶段已被 401 拦下。
        """
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {"scope": self.scope, "ident": request.user.pk}
