from django.db import transaction
from django.db.models import Count, Exists, OuterRef
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from config.pagination import DefaultLimitOffsetPagination
from moderation.models import ReportStatus
from moderation.services import blocked_user_ids
from users.models import ProfileStatus

from .models import Post, PostComment, PostImage, PostLike, PostReport
from .serializers import (PostCommentCreateSerializer, PostCommentSerializer,
                          PostCreateSerializer, PostReportCreateSerializer,
                          PostSerializer)
from .services import delete_post, notify_post_commented, visible_posts
from .throttles import PostCommentThrottle, PostCreateThrottle, PostReportThrottle


def _page_response(request, queryset, serializer_class=PostSerializer):
    paginator = DefaultLimitOffsetPagination()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(
        serializer_class(page, many=True, context={"request": request}).data)


@api_view(["GET", "POST"])
@throttle_classes([PostCreateThrottle])
def posts(request):
    if request.method == "POST":
        return _create_post(request)
    return _page_response(request, visible_posts(request.user))


def _create_post(request):
    serializer = PostCreateSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        post = Post.objects.create(author=request.user,
                                   text=serializer.validated_data["text"])
        for order, file in enumerate(request.FILES.getlist("images")):
            PostImage.objects.create(post=post, file=file, order=order)
    post = visible_posts(request.user).get(pk=post.pk)
    return Response(PostSerializer(post, context={"request": request}).data, status=201)


@api_view(["GET"])
def my_posts(request):
    queryset = (Post.objects.filter(author=request.user)
                .select_related("author__profile").prefetch_related("author__photos", "images")
                .annotate(like_count=Count("likes", distinct=True),
                          comment_count=Count("comments", distinct=True),
                          liked_by_me=Exists(
                              PostLike.objects.filter(post=OuterRef("pk"), user=request.user)))
                .order_by("-created_at", "-id"))
    return _page_response(request, queryset)


@api_view(["GET", "DELETE"])
def post_detail(request, post_id):
    if request.method == "DELETE":
        post = get_object_or_404(Post, pk=post_id, author=request.user)   # 非作者 404
        delete_post(post)
        return Response(status=204)
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    return Response(PostSerializer(post, context={"request": request}).data)


@api_view(["POST", "DELETE"])
def post_like(request, post_id):
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    if request.method == "POST":
        _, created = PostLike.objects.get_or_create(post=post, user=request.user)
        return Response({"liked": True}, status=201 if created else 200)
    PostLike.objects.filter(post=post, user=request.user).delete()
    return Response(status=204)


@api_view(["GET", "POST"])
@throttle_classes([PostCommentThrottle])
def post_comments(request, post_id):
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    if request.method == "POST":
        serializer = PostCommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        comment = PostComment.objects.create(post=post, author=request.user,
                                             text=serializer.validated_data["text"])
        notify_post_commented(comment)
        return Response(PostCommentSerializer(comment, context={"request": request}).data,
                        status=201)
    blocked = blocked_user_ids(request.user)
    comments = (post.comments
                .exclude(author_id__in=blocked)
                .exclude(author__profile__status=ProfileStatus.BANNED_HEAVY)
                .select_related("author__profile").prefetch_related("author__photos"))
    return _page_response(request, comments, PostCommentSerializer)


@api_view(["POST"])
@throttle_classes([PostReportThrottle])
def post_report(request, post_id):
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    if post.author_id == request.user.id:
        raise ValidationError("不能举报自己的动态")
    serializer = PostReportCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    report, created = PostReport.objects.get_or_create(
        reporter=request.user, post=post, status=ReportStatus.PENDING,
        defaults={"type": serializer.validated_data["type"],
                  "detail": serializer.validated_data["detail"]})
    return Response({"id": report.id, "status": report.status},
                    status=201 if created else 200)
