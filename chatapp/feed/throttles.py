"""广场接口的限流:发布动态、发表评论、举报动态、关注。

设计要点:
    读写共用一个视图时(GET/POST 同路径),限流只应作用于写操作 ——
    因此 ``allow_request`` 里对非 POST 直接放行,看列表不受额度影响。
    关注接口的 POST/DELETE **都是写**,共用同一个额度(关注又取消地刷也会被压住)。
"""

from rest_framework.throttling import SimpleRateThrottle

from config.throttling import UserScopedThrottle


class FollowThrottle(UserScopedThrottle):
    """按用户限流关注/取消关注;额度见 ``settings.DEFAULT_THROTTLE_RATES["follow"]``。"""

    scope = "follow"


class PostLikeThrottle(UserScopedThrottle):
    """按用户限流点赞/取消点赞;额度见 ``settings.DEFAULT_THROTTLE_RATES["post_like"]``。"""

    scope = "post_like"


class PostCreateThrottle(SimpleRateThrottle):
    """按用户限流发布动态;额度在 settings.DEFAULT_THROTTLE_RATES["post_create"]。"""

    scope = "post_create"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该用户在 ``post_create`` 作用域下的缓存键。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}

    def allow_request(self, request, view):
        """只对 POST 计数,读列表不限流。

        Args:
            request: 当前请求。
            view: 当前视图。

        Returns:
            非 POST 时恒为 ``True``,否则走父类的额度判定。
        """
        if request.method != "POST":
            return True
        return super().allow_request(request, view)


class PostCommentThrottle(SimpleRateThrottle):
    """按用户限流发评论;只限 POST(看评论列表不限)。"""

    scope = "post_comment"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该用户在 ``post_comment`` 作用域下的缓存键。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}

    def allow_request(self, request, view):
        """只对 POST 计数,读评论不限流。

        Args:
            request: 当前请求。
            view: 当前视图。

        Returns:
            非 POST 时恒为 ``True``,否则走父类的额度判定。
        """
        if request.method != "POST":
            return True
        return super().allow_request(request, view)


class PostReportThrottle(SimpleRateThrottle):
    """按用户限流举报动态;额度在 settings.DEFAULT_THROTTLE_RATES["post_report"]。"""

    scope = "post_report"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该用户在 ``post_report`` 作用域下的缓存键。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}


class FollowingReadThrottle(UserScopedThrottle):
    """按用户限流关注流;额度见 ``settings.DEFAULT_THROTTLE_RATES["following_read"]``。

    关注流每次请求要跑三段 SQL(总行数 ``COUNT``、当页 id、当页聚合),
    因此按用户限流,防止刷流放大查询成本。
    """

    scope = "following_read"


class CommentRepliesThrottle(UserScopedThrottle):
    """按用户限流回复列表;额度见 ``settings.DEFAULT_THROTTLE_RATES["comment_replies"]``。

    回复列表不是「一页一条 SQL」:可见性过滤会带上拉黑/封禁子查询,
    且展开楼中楼时客户端会连续请求多条顶级评论,额度比关注流略宽。
    """

    scope = "comment_replies"
