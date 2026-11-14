"""广场动态接口:发布/列表、我的动态、详情与删除、点赞、收藏、评论、举报、关注流。

设计要点:
    1. **可见性一律走 ``services.visible_posts`` / ``visible_base``**,它同时排除双向拉黑
       与重封禁作者;评论列表、点赞列表另需单独过滤(点赞者/评论者可能是被拉黑或被重封禁的人);
    2. **删除动态与举报联动**:删除前先关闭该动态的全部待处理举报,否则举报会在
       审核台里悬空(作者自删与运营删除共用同一条路径);
    3. 点赞与举报都幂等:重复点赞返回 200(首次为 201),重复举报返回已有记录;
       收藏恒 204(与关注同口径,接口不区分「是不是第一次」);
    4. **关注接口挂在 ``/users/{user_id}/follow``**(路由写在 ``users/urls.py``,视图在本文件):
       它操作的是「用户关系」而不是「广场动态」,但关系语义归 feed,所以视图放这里;
    5. 收藏**不发通知、不产生 IM 灰条**:它是私密书签,只动 ``PostFavorite`` 一张表。

关联文档:
    - 接口契约:docs/api/feed.md

文件信息:
    文件名称          feed/views.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import uuid

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from config import images, storage
from config.cursor import (cursor_body, paginated_response, read_before, slice_page,
                           wants_legacy_offset)
from config.pagination import DefaultLimitOffsetPagination
from config.params import int_param
from config.schema_helpers import cursor_page, cursor_params, offset_page, offset_params
from moderation.models import ReportStatus
from moderation.services import blocked_user_ids
from notifications.models import NotificationKind, NotificationTarget
from notifications.services import display_name, notify_on_commit
from users.models import ProfileStatus

from .models import (Post, PostComment, PostFavorite, PostImage, PostLike, PostReport)
from .serializers import (POST_LIKER_SCHEMA, PostCommentCreateSerializer,
                          PostCommentSerializer, PostCreateSerializer,
                          PostReportCreateSerializer, PostSerializer, author_brief)
from .services import (create_comment, delete_comment, delete_post, follow,
                       following_base, notify_comment_created, page_favorite_posts,
                       page_visible_posts, unfollow, visible_base, visible_comments,
                       visible_likers, visible_posts)
from .throttles import (CommentRepliesThrottle, FavoritesReadThrottle, FollowThrottle,
                        FollowingReadThrottle, PostCommentThrottle, PostCreateThrottle,
                        PostFavoriteThrottle, PostLikeThrottle, PostLikesReadThrottle,
                        PostReportThrottle)

User = get_user_model()

# 点赞/举报的回执是纯字典,给 schema 用的内联序列化器(200 与 201 共用同一个组件)
POST_LIKE_SCHEMA = inline_serializer("PostLikeResult", fields={
    "liked": serializers.BooleanField()})
POST_REPORT_SCHEMA = inline_serializer("PostReportResult", fields={
    "id": serializers.IntegerField(),
    "status": serializers.CharField(),
})
POST_CREATE_SCHEMA = inline_serializer("PostCreateBody", fields={
    "text": serializers.CharField(required=False),
    "images": serializers.ListField(child=serializers.ImageField(), required=False),
})


def _page_response(request, queryset, serializer_class=PostSerializer):
    """把查询集按统一分页约定包成响应。

    备注信息:
        走 ``DefaultLimitOffsetPagination``(``limit`` / ``offset`` 风格),响应形状
        ``{count, next, previous, results}``;只用于评论与回复列表 —— 广场、关注流、
        我的收藏已改成游标分页,不经过本函数。
    """
    paginator = DefaultLimitOffsetPagination()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(
        serializer_class(page, many=True, context={"request": request}).data)


@extend_schema(methods=["GET"], operation_id="posts_list", parameters=cursor_params(),
               responses={200: cursor_page("PostPage", PostSerializer)})
@extend_schema(methods=["POST"], request=POST_CREATE_SCHEMA,
               responses={201: PostSerializer})
@api_view(["GET", "POST"])
@throttle_classes([PostCreateThrottle])
def posts(request):
    """广场动态:列表与发布(GET/POST /api/v1/posts)。

    GET 返回可见动态(排除双向拉黑与重封禁作者);POST 发布一条新动态。
    限流只作用于 POST(见 ``PostCreateThrottle.allow_request``)。

    参数说明:
        request: DRF 请求对象;POST 时为 multipart,正文 ``text`` + 可选多张 ``images``。

    返回参数:
        GET 返回分页后的动态列表;POST 返回 201 + 新动态。

    使用示例:
        ``GET /api/v1/posts?limit=20&before=<游标>``

    备注信息:
        GET 默认走复合游标(响应 ``{count, next_cursor, has_more, results}``),
        带 ``offset`` 的老客户端走兼容分支(响应 ``{count, next, previous, results}``);
        POST 的正文与图片由 ``PostCreateSerializer`` 校验,配额超限是 413 + ``41301``。
    """
    if request.method == "POST":
        return _create_post(request)
    return _page_visible_posts(request)


def _page_visible_posts(request):
    """两段式分页:先取当页 id,再只对这几条做赞/评聚合(见 ``page_visible_posts``)。

    备注信息:
        默认走**复合游标**(``?before=``),响应 ``{count, next_cursor, has_more, results}``;
        请求里带 ``offset`` 的老客户端仍走旧的 ``LimitOffsetPagination`` 路径,
        响应形状保持 ``{count, next, previous, results}``(审查 N-5 / backlog D-1)。
        ``limit`` 由 ``int_param`` 夹在 ``[1, max_limit]`` 之间,越界不报错而是截断。
    """
    if wants_legacy_offset(request):
        return _legacy_page_visible_posts(request)
    limit = int_param(request, "limit", default=DefaultLimitOffsetPagination.default_limit,
                      minimum=1, maximum=DefaultLimitOffsetPagination.max_limit)
    page = page_visible_posts(request.user, limit, before=read_before(request))
    return Response(cursor_body(
        PostSerializer(page.rows, many=True, context={"request": request}).data,
        count=page.total, next_cursor=page.next_cursor, has_more=page.has_more))


def _legacy_page_visible_posts(request):
    """offset 分页(老客户端兼容路径):响应形状与改造前逐字段一致。

    备注信息:
        手工把 ``count`` / ``limit`` / ``offset`` / ``request`` 填回 paginator,
        是因为数据和总数来自 ``page_visible_posts`` 而非 paginator 自己切的查询集;
        这条分支只服务还在用 ``offset`` 的旧客户端,新代码不要再接它。
    """
    paginator = DefaultLimitOffsetPagination()
    limit = paginator.get_limit(request)
    offset = paginator.get_offset(request)
    page = page_visible_posts(request.user, limit, offset=offset)
    paginator.count = page.total
    paginator.limit = limit
    paginator.offset = offset
    paginator.request = request
    return paginator.get_paginated_response(
        PostSerializer(page.rows, many=True, context={"request": request}).data)


def _create_post(request):
    """在事务内建动态与配图,再回读一次带注解的对象返回。

    备注信息:
        顺序是刻意的:先把图片全部校验并重编码(``images.open_checked`` +
        ``images.normalize``),再统一查一次配额(``storage.ensure_quota``),
        最后才进事务建动态与配图。配额超限抛 ``StorageQuotaExceeded``(413 + ``41301``,
        不是 ``ValidationError``);若边建动态边写图,超限时文件已落盘、事务回滚删不掉,
        会留下孤儿文件。返回前用 ``visible_posts`` 回读,响应里才带赞/评数与作者信息。
    """
    serializer = PostCreateSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    # 先把图片全部校验/重编码完,再统一查一次配额:配额超限是 413(APIException),
    # 不是 ValidationError;若边建动态边写图,超限时文件已经落盘,事务回滚删不掉,
    # 会留下一批孤儿文件。
    normalized_images = []
    for file in request.FILES.getlist("images"):
        try:
            normalized_images.append(images.normalize(images.open_checked(file.read())))
        except images.ImageError as error:
            raise ValidationError(str(error)) from error
    storage.ensure_quota(request.user,
                         sum(len(item.data) for item in normalized_images))
    with transaction.atomic():
        post = Post.objects.create(author=request.user,
                                   text=serializer.validated_data["text"])
        for order, normalized in enumerate(normalized_images):
            PostImage.objects.create(
                post=post,
                file=ContentFile(normalized.data,
                                 name=f"{request.user.id}-{uuid.uuid4().hex}{normalized.extension}"),
                bytes=len(normalized.data),
                order=order)
    post = visible_posts(request.user).get(pk=post.pk)
    return Response(PostSerializer(post, context={"request": request}).data, status=201)


@extend_schema(parameters=cursor_params(),
               responses={200: cursor_page("MyPostPage", PostSerializer)})
@api_view(["GET"])
def my_posts(request):
    """我的动态列表(GET /api/v1/posts/mine)。

    与广场列表不同:这里只按作者过滤,不套用 ``visible_posts`` 的可见性规则 ——
    自己发过的动态自己始终能看到。

    参数说明:
        request: DRF 请求对象,支持 ``limit`` / ``before``(或兼容的 ``offset``)。

    返回参数:
        分页后的动态列表,按发布时间倒序。

    使用示例:
        ``GET /api/v1/posts/mine?limit=20``

    备注信息:
        注解与 ``visible_posts`` 同款(``like_count`` / ``comment_count`` /
        ``liked_by_me`` / ``is_favorited``),只是作者范围换成了自己;
        这里走 ``paginated_response``,因此同时支持游标与旧 ``offset`` 两种翻页。
    """
    queryset = (Post.objects.filter(author=request.user)
                .select_related("author__profile").prefetch_related("author__photos", "images")
                .annotate(like_count=Count("likes", distinct=True),
                          comment_count=Count("comments", distinct=True),
                          liked_by_me=Exists(
                              PostLike.objects.filter(post=OuterRef("pk"), user=request.user)),
                          # 与 ``visible_posts`` 同款注解:自己的动态也要能显示「已收藏」
                          is_favorited=Exists(
                              PostFavorite.objects.filter(post=OuterRef("pk"),
                                                          user=request.user)))
                .order_by("-created_at", "-id"))
    return paginated_response(
        request, queryset,
        lambda rows: PostSerializer(rows, many=True, context={"request": request}).data)


@extend_schema(methods=["GET"], responses={200: PostSerializer})
@extend_schema(methods=["DELETE"], responses={204: None})
@api_view(["GET", "DELETE"])
def post_detail(request, post_id):
    """动态详情与删除(GET/DELETE /api/v1/posts/{post_id})。

    DELETE 只允许作者本人操作,非作者一律 404(不暴露该动态是否存在);
    删除走 ``services.delete_post``,会连带关闭待处理举报并删除图片文件。

    参数说明:
        request: DRF 请求对象。
        post_id: 动态主键。

    返回参数:
        GET 返回动态详情;DELETE 返回 204 空响应。

    使用示例:
        ``DELETE /api/v1/posts/12``

    备注信息:
        GET 用 ``visible_posts`` 取对象,不可见(不存在 / 双向拉黑 / 作者被重封禁)
        同样是 404;DELETE 走作者条件查询,因此拿别人的动态删除也是 404 而不是 403。
    """
    if request.method == "DELETE":
        post = get_object_or_404(Post, pk=post_id, author=request.user)   # 非作者 404
        delete_post(post)
        return Response(status=204)
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    return Response(PostSerializer(post, context={"request": request}).data)


@extend_schema(methods=["POST"], request=None,
               responses={200: POST_LIKE_SCHEMA, 201: POST_LIKE_SCHEMA})
@extend_schema(methods=["DELETE"], responses={204: None})
@api_view(["POST", "DELETE"])
@throttle_classes([PostLikeThrottle])
def post_like(request, post_id):
    """点赞与取消点赞(POST/DELETE /api/v1/posts/{post_id}/like)。

    点赞幂等:重复点赞返回 200(首次为 201);取消点赞幂等,没赞过也返回 204。
    首次点赞会给动态作者写一条站内通知(自己赞自己不通知,取消赞不通知)。

    参数说明:
        request: DRF 请求对象。
        post_id: 动态主键。

    返回参数:
        POST 返回 ``{"liked": true}``;DELETE 返回 204 空响应。

    使用示例:
        ``POST /api/v1/posts/12/like``

    备注信息:
        动态先过 ``visible_posts``,不可见即 404;``like_count`` 不在表里存计数列,
        由查询时注解 ``Count("likes")`` 得出,因此这里不需要维护计数。
        POST 与 DELETE 共用一个限流额度(``post_like``,默认 120/hour)。
    """
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    if request.method == "POST":
        _, created = PostLike.objects.get_or_create(post=post, user=request.user)
        if created and post.author_id != request.user.id:
            # 站内通知(批次 H):只在**首次**点赞时写一条;取消赞不产生通知,
            # 再次点赞被 dedupe_key 吸收。灰条链路不受影响。
            notify_on_commit(
                post.author_id, NotificationKind.POST_LIKE, actor_id=request.user.id,
                target_kind=NotificationTarget.POST, target_id=post.id,
                text=f"{display_name(request.user)} 赞了你的动态",
                dedupe_key=f"like:{post.id}:{request.user.id}")
        return Response({"liked": True}, status=201 if created else 200)
    PostLike.objects.filter(post=post, user=request.user).delete()
    return Response(status=204)


@extend_schema(parameters=cursor_params(),
               responses={200: cursor_page("PostLikerPage", POST_LIKER_SCHEMA)})
@api_view(["GET"])
@throttle_classes([PostLikesReadThrottle])
def post_likes(request, post_id):
    """点赞列表(GET /api/v1/posts/{post_id}/likes)。

    按**点赞时间倒序**返回「谁点了赞」,游标建在 ``PostLike`` 行上。
    动态本身走广场可见性口径,不可见(不存在 / 双向拉黑 / 作者被重封禁)一律 404;
    点赞者同样过滤双向拉黑与重封禁账号,``count`` 是**过滤后**的可见人数。
    没人点赞返回 200 + 空列表(不 404)。新接口没有老客户端,不提供 ``offset`` 兼容分支。

    参数说明:
        request: DRF 请求对象,支持 ``limit`` / ``before``。
        post_id: 动态主键。

    返回参数:
        ``{count, next_cursor, has_more, results}``,``results[]`` 元素为
        ``{user_id, nickname, avatar_url, liked_at}``。

    使用示例:
        ``GET /api/v1/posts/12/likes?limit=20``

    备注信息:
        动态可见性只做判断、不注解:``get_object_or_404(visible_base(...))``
        比用 ``visible_posts`` 少跑三条 SQL;``liked_at`` 是点赞行的时间,
        不是用户资料或动态的时间。限流见 ``PostLikesReadThrottle``(默认 120/hour)。
    """
    # 可见性用 ``visible_base``(与 ``visible_posts`` 同一口径,但不再注解/预取):
    # 这里只需要判断「这条动态能不能看」;拿带 COUNT … GROUP BY 与图片预取的查询集去
    # get() 会白跑三条 SQL,把点赞列表的查询预算抬高。
    post = get_object_or_404(visible_base(request.user), pk=post_id)
    likers = visible_likers(post, request.user)
    total = likers.count()
    page = slice_page(request, likers, field="created_at")
    results = []
    for like in page.rows:
        brief = author_brief(like.user, request)
        results.append({"user_id": brief["user_id"], "nickname": brief["nickname"],
                        "avatar_url": brief["avatar_url"], "liked_at": like.created_at})
    return Response(cursor_body(results, count=total, next_cursor=page.next_cursor,
                                has_more=page.has_more))


@extend_schema(methods=["POST"], request=None, responses={204: None})
@extend_schema(methods=["DELETE"], responses={204: None})
@api_view(["POST", "DELETE"])
@throttle_classes([PostFavoriteThrottle])
def post_favorite(request, post_id):
    """收藏与取消收藏(POST/DELETE /api/v1/posts/{post_id}/favorite)。

    **两个方法都恒 204**(首次收藏、重复收藏、没收藏过就取消,全都 204):
    与关注接口同口径,客户端只做乐观翻转,不需要知道「是不是第一次」。
    收藏自己的动态允许(书签语义)。**不发通知、不产生 IM 灰条** —— 收藏是私密书签,
    只动 ``PostFavorite`` 一张表(不调 ``notify_on_commit``、不碰 ``im/tasks.py``)。

    参数说明:
        request: DRF 请求对象。
        post_id: 动态主键。

    返回参数:
        204 空响应。

    使用示例:
        ``POST /api/v1/posts/12/favorite``

    备注信息:
        动态不可见(不存在 / 双向拉黑 / 作者被重封禁)统一 404,与点赞列表同款;
        POST 与 DELETE 共用 ``post_favorite`` 一个额度(默认 300/hour),
        额度比点赞宽松,因为收藏是私密书签、正常使用会成串点。
    """
    # 与点赞列表同款:只为判可见,不注解、不预取。
    post = get_object_or_404(visible_base(request.user), pk=post_id)
    if request.method == "POST":
        PostFavorite.objects.get_or_create(post=post, user=request.user)
    else:
        PostFavorite.objects.filter(post=post, user=request.user).delete()
    return Response(status=204)


@extend_schema(methods=["GET"], parameters=offset_params(),
               responses={200: offset_page("CommentPage", PostCommentSerializer)})
@extend_schema(methods=["POST"], request=PostCommentCreateSerializer,
               responses={201: PostCommentSerializer})
@api_view(["GET", "POST"])
@throttle_classes([PostCommentThrottle])
def post_comments(request, post_id):
    """评论列表与发表评论(GET/POST /api/v1/posts/{post_id}/comments)。

    GET 只返回顶级评论(内嵌前两条回复);POST 可带 ``parent_id`` 发表回复,
    层级由 ``services.create_comment`` 归一为两级,提醒在事务提交后入队。

    参数说明:
        request: DRF 请求对象;POST 时 body 需带 ``text``,可选 ``parent_id``。
        post_id: 动态主键。

    返回参数:
        GET 返回分页后的顶级评论;POST 返回 201 + 新评论。

    使用示例:
        ``POST /api/v1/posts/12/comments {"text": "好看", "parent_id": 3}``

    备注信息:
        评论列表与回复列表都是 ``limit`` / ``offset`` 分页(不走游标);
        GET 用 ``Prefetch(..., to_attr="visible_replies")`` 一次取回全部可见回复,
        序列化器只截前两条内嵌,``reply_count`` 仍按全量算;
        ``parent_id`` 不在该动态或不可见时 404;限流只作用于 POST(默认 60/day)。
    """
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    if request.method == "POST":
        serializer = PostCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        parent = None
        parent_id = serializer.validated_data.get("parent_id")
        if parent_id is not None:
            parent = get_object_or_404(visible_comments(post, request.user), pk=parent_id)
        comment = create_comment(post, request.user,
                                 serializer.validated_data["text"], parent)
        notify_comment_created(comment)
        return Response(PostCommentSerializer(comment, context={"request": request}).data,
                        status=201)
    top = visible_comments(post, request.user).filter(parent__isnull=True)
    top = top.prefetch_related(
        Prefetch("replies",
                 queryset=visible_comments(post, request.user).filter(parent__isnull=False),
                 to_attr="visible_replies"))
    return _page_response(request, top, PostCommentSerializer)


@extend_schema(parameters=offset_params(),
               responses={200: offset_page("ReplyPage", PostCommentSerializer)})
@api_view(["GET"])
@throttle_classes([CommentRepliesThrottle])
def post_comment_replies(request, post_id, comment_id):
    """某条顶级评论的回复列表(GET /api/v1/posts/{post_id}/comments/{comment_id}/replies)。

    参数说明:
        request: DRF 请求对象,支持 ``limit`` / ``offset``。
        post_id: 动态主键。
        comment_id: 顶级评论主键。

    返回参数:
        分页后的回复列表,按时间正序。

    使用示例:
        ``GET /api/v1/posts/12/comments/3/replies?limit=20``

    备注信息:
        ``comment_id`` 必须是**顶级评论**:用 ``parent__isnull=True`` 过滤后再取对象,
        传回复的 id 会 404。返回的每条回复自身 ``replies`` 恒空、``reply_count`` 恒 0,
        不再往下递归;限流见 ``CommentRepliesThrottle``(默认 360/hour,比关注流略宽)。
    """
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    root = get_object_or_404(
        visible_comments(post, request.user).filter(parent__isnull=True), pk=comment_id)
    replies = visible_comments(post, request.user).filter(parent=root)
    return _page_response(request, replies, PostCommentSerializer)


@extend_schema(responses={204: None})
@api_view(["DELETE"])
def post_comment_detail(request, post_id, comment_id):
    """删除自己的评论(DELETE /api/v1/posts/{post_id}/comments/{comment_id})。

    删顶级评论会连带删除该楼全部回复;非作者一律 404(不暴露存在性)。

    参数说明:
        request: DRF 请求对象。
        post_id: 动态主键。
        comment_id: 评论主键。

    返回参数:
        204 空响应。

    使用示例:
        ``DELETE /api/v1/posts/12/comments/3``

    备注信息:
        查询条件是 ``pk`` + ``post`` + ``author`` 三者同时命中,因此别人的评论、
        别的动态下的评论、不可见动态下的评论都是 404;回复随
        ``PostComment.parent`` 上的 ``CASCADE`` 一并删除。
    """
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    comment = get_object_or_404(PostComment, pk=comment_id, post=post,
                                author=request.user)
    delete_comment(comment)
    return Response(status=204)


@extend_schema(request=PostReportCreateSerializer,
               responses={200: POST_REPORT_SCHEMA, 201: POST_REPORT_SCHEMA})
@api_view(["POST"])
@throttle_classes([PostReportThrottle])
def post_report(request, post_id):
    """举报动态(POST /api/v1/posts/{post_id}/report)。

    幂等:同一动态已有待处理举报时返回已有记录(200),本次新建返回 201。

    参数说明:
        request: DRF 请求对象,body 需带 ``type`` 与可选 ``detail``。
        post_id: 动态主键。

    返回参数:
        ``{id, status}``。

    使用示例:
        ``POST /api/v1/posts/12/report {"type": "spam", "detail": "广告"}``

    备注信息:
        举报自己的动态抛 ``ValidationError``(400);幂等靠 ``dedupe_key``
        (``举报人:动态:pending``)的唯一约束,并发提交时 ``get_or_create``
        会回查已有记录,不产生重复行;同一动态被处理完可以再次举报,此时键已置空、
        走新建分支返回 201。限流 ``post_report`` 默认 20/day。
    """
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    if post.author_id == request.user.id:
        raise ValidationError("不能举报自己的动态")
    serializer = PostReportCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    # 幂等:同一对「举报人 → 动态」的待处理举报共用同一个 dedupe_key。
    # 并发提交时由数据库唯一约束兜底,get_or_create 会回查已有记录,不会产生重复行(L-2)。
    dedupe_key = f"{request.user.id}:{post.id}:{ReportStatus.PENDING}"
    report, created = PostReport.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={"reporter": request.user, "post": post,
                  "type": serializer.validated_data["type"],
                  "detail": serializer.validated_data["detail"]})
    return Response({"id": report.id, "status": report.status},
                    status=201 if created else 200)


@extend_schema(parameters=cursor_params(),
               responses={200: cursor_page("FollowingPage", PostSerializer)})
@api_view(["GET"])
@throttle_classes([FollowingReadThrottle])
def following_posts(request):
    """关注流(GET /api/v1/feed/following)。

    只含**我关注的人**的动态(不含自己),可见性复用广场口径
    (排除双向拉黑与重封禁作者);游标分页,响应形状与广场列表完全一致。
    新接口没有老客户端,因此不提供 ``offset`` 兼容分支。

    参数说明:
        request: DRF 请求对象,支持 ``limit`` / ``before``。

    返回参数:
        ``{count, next_cursor, has_more, results}``。

    使用示例:
        ``GET /api/v1/feed/following?limit=20``

    备注信息:
        ``base`` 传 ``following_base``,可见性规则与广场完全同源,只是作者范围收窄;
        关注为空时返回 200 + 空列表 + ``count=0``;限流 ``following_read`` 默认 240/hour。
    """
    limit = int_param(request, "limit", default=DefaultLimitOffsetPagination.default_limit,
                      minimum=1, maximum=DefaultLimitOffsetPagination.max_limit)
    page = page_visible_posts(request.user, limit, before=read_before(request),
                              base=following_base(request.user))
    return Response(cursor_body(
        PostSerializer(page.rows, many=True, context={"request": request}).data,
        count=page.total, next_cursor=page.next_cursor, has_more=page.has_more))


@extend_schema(parameters=cursor_params(),
               responses={200: cursor_page("FavoritesPage", PostSerializer)})
@api_view(["GET"])
@throttle_classes([FavoritesReadThrottle])
def favorite_posts(request):
    """我的收藏(GET /api/v1/feed/favorites)。

    按**收藏时间倒序**(不是发帖时间),响应形状与广场列表逐字段一致。
    游标建在 ``PostFavorite`` 行上(见 ``services.page_favorite_posts``):
    收藏了但已不可见的动态(被双向拉黑 / 作者被重封禁 / 已被删)**既不出现在列表,
    也不计入 ``count``**。新接口没有老客户端,不提供 ``offset`` 兼容分支。

    参数说明:
        request: DRF 请求对象,支持 ``limit`` / ``before``。

    返回参数:
        ``{count, next_cursor, has_more, results}``,``results[]`` 为动态对象。

    使用示例:
        ``GET /api/v1/feed/favorites?limit=20``

    备注信息:
        收藏了别人的动态后被对方拉黑,该条会从列表与 ``count`` 里一起消失;
        动态被删时收藏行随 ``CASCADE`` 消失,不需要额外清理;
        限流 ``favorites_read`` 默认 120/hour。
    """
    limit = int_param(request, "limit", default=DefaultLimitOffsetPagination.default_limit,
                      minimum=1, maximum=DefaultLimitOffsetPagination.max_limit)
    page = page_favorite_posts(request.user, limit, before=read_before(request))
    return Response(cursor_body(
        PostSerializer(page.rows, many=True, context={"request": request}).data,
        count=page.total, next_cursor=page.next_cursor, has_more=page.has_more))


@extend_schema(methods=["POST"], request=None, responses={204: None})
@extend_schema(methods=["DELETE"], responses={204: None})
@api_view(["POST", "DELETE"])
@throttle_classes([FollowThrottle])
def follow_user(request, user_id):
    """关注与取消关注(POST/DELETE /api/v1/users/{user_id}/follow)。

    幂等:重复关注、重复取消都返回 204(不返回 201,也不报 409);
    不能关注自己(400);与我互相拉黑、对方不存在或处于重封禁状态一律 404
    (三种情况统一按「用户不存在」处理,不泄漏账号是否存在)。
    关注**不发通知、不建立聊天权限**,只影响「关注」tab 的内容。

    参数说明:
        request: DRF 请求对象。
        user_id: 被关注/被取消关注的账号 id。

    返回参数:
        204 空响应。

    使用示例:
        ``POST /api/v1/users/34/follow``

    备注信息:
        判定顺序是刻意的:先判「关注自己」(400),再判是否在双向拉黑集合里
        (命中即 404),最后查账号与资料并判重封禁(404)—— 三种「不可见」情形
        统一返回「用户不存在」,避免通过状态码泄漏账号是否存在。
        路由写在 ``users/urls.py``,视图留在本文件(关系语义归 feed)。
        幂等与限额:POST/DELETE 共用 ``follow`` 一个额度(默认 120/hour)。
    """
    if user_id == request.user.id:
        raise ValidationError("不能关注自己")
    if user_id in blocked_user_ids(request.user):
        raise NotFound("用户不存在")
    target = get_object_or_404(User, id=user_id)
    profile = getattr(target, "profile", None)
    if profile is None or profile.status == ProfileStatus.BANNED_HEAVY:
        raise NotFound("用户不存在")
    if request.method == "POST":
        follow(request.user, target)
    else:
        unfollow(request.user, target)
    return Response(status=204)
