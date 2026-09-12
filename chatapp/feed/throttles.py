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


class PostCommentThrottle(SimpleRateThrottle):
    """按用户限流发评论;只限 POST(看评论列表不限)。"""

    scope = "post_comment"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}

    def allow_request(self, request, view):
        if request.method != "POST":
            return True
        return super().allow_request(request, view)


class PostReportThrottle(SimpleRateThrottle):
    """按用户限流举报动态;额度在 settings.DEFAULT_THROTTLE_RATES["post_report"]。"""

    scope = "post_report"

    def get_cache_key(self, request, view):
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
