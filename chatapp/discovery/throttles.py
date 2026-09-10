from rest_framework.throttling import SimpleRateThrottle


class SwipeThrottle(SimpleRateThrottle):
    """按用户限流滑卡;额度在 settings.DEFAULT_THROTTLE_RATES["swipe"]。"""

    scope = "swipe"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
