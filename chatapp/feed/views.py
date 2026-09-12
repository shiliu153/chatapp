from django.db import transaction
from django.db.models import Count, Exists, OuterRef
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from config.pagination import DefaultLimitOffsetPagination

from .models import Post, PostImage, PostLike
from .serializers import PostCreateSerializer, PostSerializer
from .services import visible_posts
from .throttles import PostCreateThrottle


def _page_response(request, queryset):
    paginator = DefaultLimitOffsetPagination()
    page = paginator.paginate_queryset(queryset, request)
    return paginator.get_paginated_response(
        PostSerializer(page, many=True, context={"request": request}).data)


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


@api_view(["GET"])
def post_detail(request, post_id):
    post = get_object_or_404(visible_posts(request.user), pk=post_id)
    return Response(PostSerializer(post, context={"request": request}).data)
