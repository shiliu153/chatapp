from rest_framework.throttling import SimpleRateThrottle


class PostCreateThrottle(SimpleRateThrottle):
    """按用户限流发布动态;额度在 settings.DEFAULT_THROTTLE_RATES["post_create"]。"""

    scope = "post_create"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)
