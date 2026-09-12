from django.db import transaction
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from .models import Post, PostImage
from .serializers import PostCreateSerializer, PostSerializer
from .services import visible_posts
from .throttles import PostCreateThrottle


@api_view(["POST"])
@throttle_classes([PostCreateThrottle])
def posts(request):
    serializer = PostCreateSerializer(data=request.data, context={"request": request})
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        post = Post.objects.create(author=request.user,
                                   text=serializer.validated_data["text"])
        for order, file in enumerate(request.FILES.getlist("images")):
            PostImage.objects.create(post=post, file=file, order=order)
    post = visible_posts(request.user).get(pk=post.pk)
    return Response(PostSerializer(post, context={"request": request}).data, status=201)
