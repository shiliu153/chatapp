"""滑卡接口的限流。

额度见 ``settings.DEFAULT_THROTTLE_RATES["swipe"]``(300/小时)——
正常手速远达不到,主要用于挡住脚本刷卡。
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
