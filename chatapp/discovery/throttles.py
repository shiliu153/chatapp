"""滑卡接口的限流。

额度见 ``settings.DEFAULT_THROTTLE_RATES["swipe"]``(300/小时)——
正常手速远达不到,主要用于挡住脚本刷卡。撤销单独占一个 scope(``swipe_undo``):
它不该和「正常滑卡」抢同一份额度,否则划得多的人会先被撤销卡住。
"""

from rest_framework.throttling import SimpleRateThrottle

from config.throttling import UserScopedThrottle


class CandidateThrottle(UserScopedThrottle):
    """按用户限流候选池;额度见 ``settings.DEFAULT_THROTTLE_RATES["candidates"]``。"""

    scope = "candidates"


class SwipeThrottle(SimpleRateThrottle):
    """按用户限流滑卡;额度在 settings.DEFAULT_THROTTLE_RATES["swipe"]。"""

    scope = "swipe"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该用户在 ``swipe`` 作用域下的缓存键。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}


class SwipeUndoThrottle(UserScopedThrottle):
    """按用户限流撤销滑卡;额度见 ``settings.DEFAULT_THROTTLE_RATES["swipe_undo"]``。

    撤销本身只删一行,但它会「让卡片复活」,配合重新滑卡可以无限刷候选池 ——
    所以单独给一份额度,挡住「撤销—重滑」循环。
    """

    scope = "swipe_undo"


class VisitsThrottle(UserScopedThrottle):
    """按用户限流访客列表;额度见 ``settings.DEFAULT_THROTTLE_RATES["visits"]``。

    ``visits`` 每次要跑 Swipe/Photo/Block 三个子查询,单账号高频调用即可持续打库(M-3)。
    """

    scope = "visits"


class VisitsCountThrottle(UserScopedThrottle):
    """按用户限流访客人数;额度见 ``settings.DEFAULT_THROTTLE_RATES["visits_count"]``。

    计数接口比列表更便宜,额度给到列表的两倍,足够入口角标刷新。
    """

    scope = "visits_count"
