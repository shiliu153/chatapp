"""滑卡接口的限流。

额度见 ``settings.DEFAULT_THROTTLE_RATES["swipe"]``(300/小时)——
正常手速远达不到,主要用于挡住脚本刷卡。撤销单独占一个 scope(``swipe_undo``):
它不该和「正常滑卡」抢同一份额度,否则划得多的人会先被撤销卡住。

文件信息:
    文件名称          discovery/throttles.py
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


class CandidateThrottle(UserScopedThrottle):
    """按用户限流候选池;额度见 ``settings.DEFAULT_THROTTLE_RATES["candidates"]``。

    参数说明:
        无;由 DRF 在视图的 ``throttle_classes`` 中按类实例化。

    返回参数:
        无返回值;``allow_request`` 返回 ``False`` 时 DRF 直接给 ``429``。

    使用示例:
        ``throttle_classes = [CandidateThrottle]``

    备注信息:
        限流键由父类 ``UserScopedThrottle`` 按用户 id 生成,要求请求已通过认证。
    """

    scope = "candidates"


class SwipeThrottle(SimpleRateThrottle):
    """按用户限流滑卡;额度在 settings.DEFAULT_THROTTLE_RATES["swipe"]。

    参数说明:
        无;由 DRF 在视图的 ``throttle_classes`` 中按类实例化。

    返回参数:
        无返回值;``allow_request`` 返回 ``False`` 时 DRF 直接给 ``429``。

    使用示例:
        ``throttle_classes = [SwipeThrottle]``

    备注信息:
        没有继承 ``UserScopedThrottle``,缓存键由本类的 :meth:`get_cache_key` 自行拼出。
    """

    scope = "swipe"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该用户在 ``swipe`` 作用域下的缓存键。

        使用示例:
            ``throttle.get_cache_key(request, view)``

        备注信息:
            ``ident`` 直接取 ``request.user.id``,匿名请求没有这个属性,视图必须已认证。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}


class SwipeUndoThrottle(UserScopedThrottle):
    """按用户限流撤销滑卡;额度见 ``settings.DEFAULT_THROTTLE_RATES["swipe_undo"]``。

    撤销本身只删一行,但它会「让卡片复活」,配合重新滑卡可以无限刷候选池 ——
    所以单独给一份额度,挡住「撤销—重滑」循环。

    参数说明:
        无;由 DRF 在视图的 ``throttle_classes`` 中按类实例化。

    返回参数:
        无返回值;``allow_request`` 返回 ``False`` 时 DRF 直接给 ``429``。

    使用示例:
        ``throttle_classes = [SwipeUndoThrottle]``

    备注信息:
        与 ``swipe`` 是两个独立的 scope,撤销额度用完不影响正常滑卡。
    """

    scope = "swipe_undo"


class VisitsThrottle(UserScopedThrottle):
    """按用户限流访客列表;额度见 ``settings.DEFAULT_THROTTLE_RATES["visits"]``。

    ``visits`` 每次要跑 Swipe/Photo/Block 三个子查询,单账号高频调用即可持续打库(M-3)。

    参数说明:
        无;由 DRF 在视图的 ``throttle_classes`` 中按类实例化。

    返回参数:
        无返回值;``allow_request`` 返回 ``False`` 时 DRF 直接给 ``429``。

    使用示例:
        ``throttle_classes = [VisitsThrottle]``

    备注信息:
        额度比 ``visits_count`` 更低,因为列表接口的库开销远大于计数接口。
    """

    scope = "visits"


class VisitsCountThrottle(UserScopedThrottle):
    """按用户限流访客人数;额度见 ``settings.DEFAULT_THROTTLE_RATES["visits_count"]``。

    计数接口比列表更便宜,额度给到列表的两倍,足够入口角标刷新。

    参数说明:
        无;由 DRF 在视图的 ``throttle_classes`` 中按类实例化。

    返回参数:
        无返回值;``allow_request`` 返回 ``False`` 时 DRF 直接给 ``429``。

    使用示例:
        ``throttle_classes = [VisitsCountThrottle]``

    备注信息:
        只用于访客人数角标;单独成 scope 是为了让角标刷新不消耗列表额度。
    """

    scope = "visits_count"
