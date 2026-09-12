from django.contrib.auth import get_user_model
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from config.pagination import DefaultLimitOffsetPagination

from .models import Block, Report, ReportStatus
from .serializers import (BlockCreateSerializer, BlockSerializer, ReportCreateSerializer,
                          ReportSerializer)
from .services import sync_im_blacklist
from .throttles import ReportThrottle

User = get_user_model()


@api_view(["POST"])
@throttle_classes([ReportThrottle])
def create_report(request):
    serializer = ReportCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if data["target_user_id"] == request.user.id:
        raise ValidationError("不能举报自己")
    target = get_object_or_404(User, id=data["target_user_id"])
    # 幂等:同一对象已有未处理举报就不重复建,直接返回已有记录
    report, created = Report.objects.get_or_create(
        reporter=request.user, target=target, status=ReportStatus.PENDING,
        defaults={"type": data["type"], "detail": data["detail"]},
    )
    return Response(ReportSerializer(report).data, status=201 if created else 200)


@api_view(["GET", "POST"])
def blocks(request):
    if request.method == "POST":
        serializer = BlockCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target_id = serializer.validated_data["target_user_id"]
        if target_id == request.user.id:
            raise ValidationError("不能拉黑自己")
        target = get_object_or_404(User, id=target_id)
        block, created = Block.objects.get_or_create(blocker=request.user, blocked=target)
        if created:
            sync_im_blacklist(request.user, target, add=True)
        return Response(BlockSerializer(block, context={"request": request}).data,
                        status=201 if created else 200)

    entries = (Block.objects.filter(blocker=request.user)
               .select_related("blocked__profile").prefetch_related("blocked__photos"))
    paginator = DefaultLimitOffsetPagination()
    page = paginator.paginate_queryset(entries, request)
    return paginator.get_paginated_response(
        [BlockSerializer(block, context={"request": request}).data for block in page])


@api_view(["DELETE"])
def unblock(request, user_id):
    block = Block.objects.filter(blocker=request.user, blocked_id=user_id).first()
    if block is not None:
        target = block.blocked
        block.delete()
        sync_im_blacklist(request.user, target, add=False)
    return Response(status=204)
