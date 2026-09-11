from rest_framework.throttling import SimpleRateThrottle


class ReportThrottle(SimpleRateThrottle):
    """按用户限流举报;额度在 settings.DEFAULT_THROTTLE_RATES["report"]。"""

    scope = "report"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
