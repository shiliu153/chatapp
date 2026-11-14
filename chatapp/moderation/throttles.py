"""举报接口的限流。

额度见 ``settings.DEFAULT_THROTTLE_RATES["report"]``(20/天)——
举报是低频且需要人工处理的操作,额度给得比较紧。

文件信息:
    文件名称          moderation/throttles.py
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

from config.throttling import UserScopedThrottle


class BlockThrottle(UserScopedThrottle):
    """按用户限流拉黑写操作;额度见 ``settings.DEFAULT_THROTTLE_RATES["blocks"]``。

    参数说明:
        无(继承 ``UserScopedThrottle``,不自定义 ``__init__``)。

    返回参数:
        限流器实例;DRF 按视图的 ``throttle_classes`` 实例化,``allow_request``
        返回 ``False`` 时接口回 429。

    使用示例:
        ``@throttle_classes([BlockThrottle])``

    备注信息:
        额度取 ``BLOCK_RATE``,默认 ``60/hour``,测试期整体放宽到 ``100000/hour``;
        与举报不同,拉黑不是一次性的低频动作(误拉黑要马上解开再拉回),所以配额按小时计。
    """

    scope = "blocks"

    def allow_request(self, request, view):
        """只对 POST 计数,看黑名单列表不限流。

        参数说明:
            request: 当前请求。
            view: 当前视图。

        返回参数:
            非 POST 时恒为 ``True``,否则走父类的额度判定。

        使用示例:
            ``throttle.allow_request(request, view)``

        备注信息:
            ``/api/v1/blocks`` 的 GET 读列表与 POST 新增拉黑同路径,不区分方法的话
            每刷一次黑名单都会消耗拉黑额度。
        """
        if request.method != "POST":
            return True
        return super().allow_request(request, view)


class ReportThrottle(SimpleRateThrottle):
    """按用户限流举报;额度在 settings.DEFAULT_THROTTLE_RATES["report"]。

    参数说明:
        无(继承 DRF ``SimpleRateThrottle``,不自定义 ``__init__``)。

    返回参数:
        限流器实例;``allow_request`` 返回 ``False`` 时举报接口回 429。

    使用示例:
        ``@throttle_classes([ReportThrottle])``

    备注信息:
        ``report`` 额度写死 ``20/day``,没有环境变量开关,测试期也不放宽 ——
        用例里改额度靠 ``patch.object(ReportThrottle, "rate", ...)``。
        直接继承 ``SimpleRateThrottle`` 而不是 ``UserScopedThrottle``,因此
        ``get_cache_key`` 必须自己实现,否则取不到用户维度。
    """

    scope = "report"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该用户在 ``report`` 作用域下的缓存键。

        使用示例:
            ``throttle.get_cache_key(request, view)``

        备注信息:
            键里只带 ``scope`` 与用户 id,不区分被举报人:换个目标继续刷同样被压住;
            未登录时 ``request.user.id`` 为 ``None``,而举报视图要求登录,故不受影响。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
