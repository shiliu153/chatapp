"""广场动态接口:发布/列表、我的动态、详情与删除、点赞、评论、举报。

设计要点:
    1. **可见性一律走 ``services.visible_posts``**,它同时排除双向拉黑与重封禁作者;
       评论列表另需单独过滤(评论作者可能是被拉黑或被重封禁的人);
    2. **删除动态与举报联动**:删除前先关闭该动态的全部待处理举报,否则举报会在
       审核台里悬空(作者自删与运营删除共用同一条路径);
    3. 点赞与举报都幂等:重复点赞返回 200(首次为 201),重复举报返回已有记录。

关联文档:
    - 接口契约:docs/api/feed.md
"""

import uuid

from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Prefetch
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from config import images, storage
from config.cursor import cursor_body, paginated_response, read_before, wants_legacy_offset
from config.pagination import DefaultLimitOffsetPagination
from config.params import int_param
from config.schema_helpers import cursor_page, cursor_params, offset_page, offset_params
from moderation.models import ReportStatus
from notifications.models import NotificationKind, NotificationTarget
from notifications.services import display_name, notify_on_commit

from .models import Post, PostComment, PostImage, PostLike, PostReport
from .serializers import (PostCommentCreateSerializer, PostCommentSerializer,
                          PostCreateSerializer, PostReportCreateSerializer,
                          PostSerializer)
from .services import (create_comment, delete_comment, delete_post,
                       notify_comment_created, page_visible_posts, visible_comments,
                       visible_posts)
from .throttles import (PostCommentThrottle, PostCreateThrottle, PostLikeThrottle,
                        PostReportThrottle)

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

    Args:
        request: DRF 请求对象,提供 ``limit`` / ``offset``。
        queryset: 已排序并注解好的查询集。
        serializer_class: 用于序列化的类,默认 ``PostSerializer``。

    Returns:
        带 ``count`` / ``next`` / ``previous`` / ``results`` 的分页响应。
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

    Args:
        request: DRF 请求对象;POST 时为 multipart,正文 ``text`` + 可选多张 ``images``。

    Returns:
        GET 返回分页后的动态列表;POST 返回 201 + 新动态。
    """
    if request.method == "POST":
        return _create_post(request)
    return _page_visible_posts(request)


def _page_visible_posts(request):
    """两段式分页:先取当页 id,再只对这几条做赞/评聚合(见 ``page_visible_posts``)。

    默认走**复合游标**(``?before=``),响应 ``{count, next_cursor, has_more, results}``;
    请求里带 ``offset`` 的老客户端仍走旧的 ``LimitOffsetPagination`` 路径,
    响应形状保持 ``{count, next, previous, results}``(审查 N-5 / backlog D-1)。

    Args:
        request: DRF 请求对象,提供 ``limit`` 与 ``before``(或兼容的 ``offset``)。

    Returns:
        分页后的动态列表响应。
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

    Args:
        request: DRF 请求对象,提供 ``limit`` / ``offset``。

    Returns:
        带 ``count`` / ``next`` / ``previous`` / ``results`` 的分页响应。
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

    Args:
        request: DRF 请求对象,正文与图片已由序列化器校验。

    Returns:
        201 + 新建动态(已带赞/评数与作者信息)。

    Raises:
        ValidationError: 配图不是 jpg/png/webp 或超过尺寸上限。
        config.storage.StorageQuotaExceeded: 账号媒体存储配额已满(413/``41301``)。
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

    Args:
        request: DRF 请求对象,支持 ``limit`` / ``before``(或兼容的 ``offset``)。

    Returns:
        分页后的动态列表,按发布时间倒序。
    """
    queryset = (Post.objects.filter(author=request.user)
                .select_related("author__profile").prefetch_related("author__photos", "images")
                .annotate(like_count=Count("likes", distinct=True),
                          comment_count=Count("comments", distinct=True),
                          liked_by_me=Exists(
                              PostLike.objects.filter(post=OuterRef("pk"), user=request.user)))
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

    Args:
        request: DRF 请求对象。
        post_id: 动态主键。

    Returns:
        GET 返回动态详情;DELETE 返回 204 空响应。
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

    Args:
        request: DRF 请求对象。
        post_id: 动态主键。

    Returns:
        POST 返回 ``{"liked": true}``;DELETE 返回 204 空响应。
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

    Args:
        request: DRF 请求对象;POST 时 body 需带 ``text``,可选 ``parent_id``。
        post_id: 动态主键。

    Returns:
        GET 返回分页后的顶级评论;POST 返回 201 + 新评论。
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
def post_comment_replies(request, post_id, comment_id):
    """某条顶级评论的回复列表(GET /api/v1/posts/{post_id}/comments/{comment_id}/replies)。

    Args:
        request: DRF 请求对象,支持 ``limit`` / ``offset``。
        post_id: 动态主键。
        comment_id: 顶级评论主键。

    Returns:
        分页后的回复列表,按时间正序。

    Raises:
        Http404: 动态不可见、评论不存在/不属于该动态/本身是回复。
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

    Args:
        request: DRF 请求对象。
        post_id: 动态主键。
        comment_id: 评论主键。

    Returns:
        204 空响应。

    Raises:
        Http404: 动态不可见,或评论不存在 / 不属于该动态 / 不是自己发的。
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

    Args:
        request: DRF 请求对象,body 需带 ``type`` 与可选 ``detail``。
        post_id: 动态主键。

    Returns:
        ``{id, status}``。

    Raises:
        ValidationError: 举报自己的动态。
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
