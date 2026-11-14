"""广场接口的限流:发布动态、发表评论、举报动态、关注、点赞列表、收藏与我的收藏。

设计要点:
    读写共用一个视图时(GET/POST 同路径),限流只应作用于写操作 ——
    因此 ``allow_request`` 里对非 POST 直接放行,看列表不受额度影响。
    关注接口的 POST/DELETE **都是写**,共用同一个额度(关注又取消地刷也会被压住);
    收藏同理(POST/DELETE 共用 ``post_favorite`` 一个额度)。

文件信息:
    文件名称          feed/throttles.py
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


class FollowThrottle(UserScopedThrottle):
    """按用户限流关注/取消关注;额度见 ``settings.DEFAULT_THROTTLE_RATES["follow"]``。

    参数说明:
        无(继承 ``UserScopedThrottle``,不自定义 ``__init__``)。

    返回参数:
        限流器实例;``allow_request`` 返回 ``False`` 时接口回 429。

    使用示例:
        ``@throttle_classes([FollowThrottle])``

    备注信息:
        默认额度 ``120/hour``(生产值,可由 ``FOLLOW_RATE`` 环境变量覆盖);
        POST 与 DELETE 都是写,共用这一个额度。测试期整体放宽到 ``100000/hour``。
    """

    scope = "follow"


class PostLikeThrottle(UserScopedThrottle):
    """按用户限流点赞/取消点赞;额度见 ``settings.DEFAULT_THROTTLE_RATES["post_like"]``。

    参数说明:
        无(继承 ``UserScopedThrottle``,不自定义 ``__init__``)。

    返回参数:
        限流器实例;``allow_request`` 返回 ``False`` 时接口回 429。

    使用示例:
        ``@throttle_classes([PostLikeThrottle])``

    备注信息:
        默认额度 ``120/hour``(可由 ``POST_LIKE_RATE`` 覆盖);POST 与 DELETE
        共用同一额度,因此连点取消再点赞同样受约束。
    """

    scope = "post_like"


class PostCreateThrottle(SimpleRateThrottle):
    """按用户限流发布动态;额度在 settings.DEFAULT_THROTTLE_RATES["post_create"]。

    参数说明:
        无(继承 DRF ``SimpleRateThrottle``,不自定义 ``__init__``)。

    返回参数:
        限流器实例;``allow_request`` 返回 ``False`` 时发布接口回 429。

    使用示例:
        ``@throttle_classes([PostCreateThrottle])``

    备注信息:
        默认额度 ``20/day``,直接写在 ``DEFAULT_THROTTLE_RATES`` 里(没有环境变量开关,
        测试期也不放宽);挂在同时承载 GET 列表的 ``posts`` 视图上,因此
        ``allow_request`` 必须放行非 POST。
    """

    scope = "post_create"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该用户在 ``post_create`` 作用域下的缓存键。

        使用示例:
            ``self.get_cache_key(request, view)``

        备注信息:
            键只带 ``scope`` 与用户 id,与其他接口的额度互不影响;
            未登录时 ``request.user.id`` 为 ``None``,本视图的权限类已先拦截。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}

    def allow_request(self, request, view):
        """只对 POST 计数,读列表不限流。

        参数说明:
            request: 当前请求。
            view: 当前视图。

        返回参数:
            非 POST 时恒为 ``True``,否则走父类的额度判定。

        使用示例:
            ``throttle.allow_request(request, view)``

        备注信息:
            GET 列表与 POST 发布同路径,若不分方法计数,刷广场会把当日发布额度耗光。
        """
        if request.method != "POST":
            return True
        return super().allow_request(request, view)


class PostCommentThrottle(SimpleRateThrottle):
    """按用户限流发评论;只限 POST(看评论列表不限)。

    参数说明:
        无(继承 DRF ``SimpleRateThrottle``,不自定义 ``__init__``)。

    返回参数:
        限流器实例;``allow_request`` 返回 ``False`` 时发评论回 429。

    使用示例:
        ``@throttle_classes([PostCommentThrottle])``

    备注信息:
        默认额度 ``60/day``,直接写在 ``DEFAULT_THROTTLE_RATES`` 里(没有环境变量开关);
        回复与顶级评论共用这一个额度,看评论列表(GET)不计数。
    """

    scope = "post_comment"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该用户在 ``post_comment`` 作用域下的缓存键。

        使用示例:
            ``self.get_cache_key(request, view)``

        备注信息:
            键格式取 ``SimpleRateThrottle.cache_format``,``ident`` 用用户 id;
            不按动态区分,同一个账号在所有动态下的评论共用一个额度。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}

    def allow_request(self, request, view):
        """只对 POST 计数,读评论不限流。

        参数说明:
            request: 当前请求。
            view: 当前视图。

        返回参数:
            非 POST 时恒为 ``True``,否则走父类的额度判定。

        使用示例:
            ``throttle.allow_request(request, view)``

        备注信息:
            GET 评论列表与 POST 发评论同路径(``/posts/{post_id}/comments``),
            不区分方法会让「翻评论」消耗发评论额度。
        """
        if request.method != "POST":
            return True
        return super().allow_request(request, view)


class PostReportThrottle(SimpleRateThrottle):
    """按用户限流举报动态;额度在 settings.DEFAULT_THROTTLE_RATES["post_report"]。

    参数说明:
        无(继承 DRF ``SimpleRateThrottle``,不自定义 ``__init__``)。

    返回参数:
        限流器实例;``allow_request`` 返回 ``False`` 时举报接口回 429。

    使用示例:
        ``@throttle_classes([PostReportThrottle])``

    备注信息:
        默认额度 ``20/day``,直接写在 ``DEFAULT_THROTTLE_RATES`` 里(没有环境变量开关);
        举报本身幂等(同一动态已有待处理举报时返回原记录),但仍按次计数,
        防止换着动态刷。
    """

    scope = "post_report"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该用户在 ``post_report`` 作用域下的缓存键。

        使用示例:
            ``self.get_cache_key(request, view)``

        备注信息:
            键里不含目标动态 id:举报额度是「账号级」的,不因换动态而重置。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}


class FollowingReadThrottle(UserScopedThrottle):
    """按用户限流关注流;额度见 ``settings.DEFAULT_THROTTLE_RATES["following_read"]``。

    关注流每次请求要跑三段 SQL(总行数 ``COUNT``、当页 id、当页聚合),
    因此按用户限流,防止刷流放大查询成本。

    参数说明:
        无(继承 ``UserScopedThrottle``,不自定义 ``__init__``)。

    返回参数:
        限流器实例;``allow_request`` 返回 ``False`` 时接口回 429。

    使用示例:
        ``@throttle_classes([FollowingReadThrottle])``

    备注信息:
        默认额度 ``240/hour``(可由 ``FOLLOWING_READ_RATE`` 覆盖),比写接口宽松:
        正常下拉刷新与翻页都在配额内。
    """

    scope = "following_read"


class CommentRepliesThrottle(UserScopedThrottle):
    """按用户限流回复列表;额度见 ``settings.DEFAULT_THROTTLE_RATES["comment_replies"]``。

    回复列表不是「一页一条 SQL」:可见性过滤会带上拉黑/封禁子查询,
    且展开楼中楼时客户端会连续请求多条顶级评论,额度比关注流略宽。

    参数说明:
        无(继承 ``UserScopedThrottle``,不自定义 ``__init__``)。

    返回参数:
        限流器实例;``allow_request`` 返回 ``False`` 时接口回 429。

    使用示例:
        ``@throttle_classes([CommentRepliesThrottle])``

    备注信息:
        默认额度 ``360/hour``(可由 ``COMMENT_REPLIES_RATE`` 覆盖)——
        「略宽」相对关注流的 ``240/hour``;展开楼中楼会成串请求,额度太紧会误伤。
    """

    scope = "comment_replies"


class PostLikesReadThrottle(UserScopedThrottle):
    """按用户限流点赞列表;额度见 ``settings.DEFAULT_THROTTLE_RATES["post_likes_read"]``。

    点赞列表每页要跑「可见总数 COUNT + 当页点赞行 + 头像预取」三条 SQL,
    且每次点击点赞数都会请求一次,额度与关注流同档(120 次/小时)。

    参数说明:
        无(继承 ``UserScopedThrottle``,不自定义 ``__init__``)。

    返回参数:
        限流器实例;``allow_request`` 返回 ``False`` 时接口回 429。

    使用示例:
        ``@throttle_classes([PostLikesReadThrottle])``

    备注信息:
        默认额度 ``120/hour``(可由 ``POST_LIKES_READ_RATE`` 覆盖),与关注流同档;
        测试期整体放宽到 ``100000/hour``。
    """

    scope = "post_likes_read"


class PostFavoriteThrottle(UserScopedThrottle):
    """按用户限流收藏/取消收藏;额度见 ``settings.DEFAULT_THROTTLE_RATES["post_favorite"]``。

    POST 与 DELETE **都是写**,共用同一个额度(收藏又取消地刷同样会被压住),
    与关注接口同口径。额度比点赞宽松:收藏是私密书签,正常使用会成串点。

    参数说明:
        无(继承 ``UserScopedThrottle``,不自定义 ``__init__``)。

    返回参数:
        限流器实例;``allow_request`` 返回 ``False`` 时接口回 429。

    使用示例:
        ``@throttle_classes([PostFavoriteThrottle])``

    备注信息:
        默认额度 ``300/hour``(可由 ``POST_FAVORITE_RATE`` 覆盖),是点赞额度
        (``120/hour``)的 2.5 倍:收藏是私密书签,连点正常;POST/DELETE 共用一个额度。
    """

    scope = "post_favorite"


class FavoritesReadThrottle(UserScopedThrottle):
    """按用户限流「我的收藏」;额度见 ``settings.DEFAULT_THROTTLE_RATES["favorites_read"]``。

    我的收藏是两段式取数(可见帖子集 + 收藏行游标 + 当页聚合),成本与关注流同级。

    参数说明:
        无(继承 ``UserScopedThrottle``,不自定义 ``__init__``)。

    返回参数:
        限流器实例;``allow_request`` 返回 ``False`` 时接口回 429。

    使用示例:
        ``@throttle_classes([FavoritesReadThrottle])``

    备注信息:
        默认额度 ``120/hour``(可由 ``FAVORITES_READ_RATE`` 覆盖),与点赞列表同档;
        它与关注流的 ``240/hour`` 不同档,改额度时按 scope 单独配。
    """

    scope = "favorites_read"

