"""举报与拉黑接口。

设计要点:
    1. **举报幂等**:同一对「举报人 → 被举报人」若已有待处理举报,直接返回已有记录
       (201 仅表示本次新建),避免刷单式重复举报;
    2. **拉黑要同步 IM**:拉黑/解除拉黑除了写本地 ``Block`` 表,还要入队同步 IM 黑名单,
       否则对方仍能发来消息;
    3. 拉黑是单向的,但**可见性按双向计算**(见 ``moderation.services.blocked_user_ids``)。

关联文档:
    - 接口契约:docs/api/moderation.md
"""

from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from config.pagination import DefaultLimitOffsetPagination

from discovery.models import Match
from .models import Block, Report, ReportStatus
from .serializers import (BlockCreateSerializer, BlockSerializer, ReportCreateSerializer,
                          ReportSerializer)
from .services import sync_im_blacklist, sync_im_pair
from .throttles import BlockThrottle, ReportThrottle

User = get_user_model()


@api_view(["POST"])
@throttle_classes([ReportThrottle])
def create_report(request):
    """提交举报(POST /api/v1/reports)。

    幂等:同一被举报人若已有待处理举报,返回已有记录且状态码为 200;
    本次新建时返回 201。

    Args:
        request: DRF 请求对象,body 需带 ``target_user_id`` / ``type`` / 可选 ``detail``。

    Returns:
        ``{id, type, status}``。

    Raises:
        ValidationError: 举报自己。
        NotFound: 被举报人不存在。
    """
    serializer = ReportCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    if data["target_user_id"] == request.user.id:
        raise ValidationError("不能举报自己")
    target = get_object_or_404(User, id=data["target_user_id"])
    # 幂等:同一对「举报人 → 被举报人」的待处理举报共用同一个 dedupe_key。
    # 并发提交时由数据库唯一约束兜底,get_or_create 会回查已有记录,不会产生重复行。
    dedupe_key = f"{request.user.id}:{target.id}:{ReportStatus.PENDING}"
    report, created = Report.objects.get_or_create(
        dedupe_key=dedupe_key,
        defaults={"reporter": request.user, "target": target,
                  "type": data["type"], "detail": data["detail"]},
    )
    return Response(ReportSerializer(report).data, status=201 if created else 200)


@api_view(["GET", "POST"])
@throttle_classes([BlockThrottle])
def blocks(request):
    """黑名单:读取列表与新增拉黑(GET/POST /api/v1/blocks)。

    POST 幂等(重复拉黑返回已有记录);仅在真正新建时才入队同步 IM 黑名单。

    Args:
        request: DRF 请求对象;POST 时 body 需带 ``target_user_id``。

    Returns:
        GET 返回分页后的黑名单条目;POST 返回拉黑对象(新建为 201,已存在为 200)。

    Raises:
        ValidationError: 拉黑自己。
        NotFound: 目标用户不存在。
    """
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
            # 拉黑即撤销聊天权限:即使两人之前配对过,也不能继续发消息
            sync_im_pair(request.user.id, target.id, add=False)
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
    """解除拉黑(DELETE /api/v1/blocks/{user_id})。

    幂等:没有该条拉黑记录时直接返回 204,不报错。

    Args:
        request: DRF 请求对象。
        user_id: 被解除拉黑的账号 id。

    Returns:
        204 空响应。
    """
    block = Block.objects.filter(blocker=request.user, blocked_id=user_id).first()
    if block is not None:
        target = block.blocked
        block.delete()
        sync_im_blacklist(request.user, target, add=False)
        # 解除拉黑后,如果两人仍是有效配对,恢复聊天权限;否则不恢复。
        still_matched = Match.objects.filter(
            Q(user_a=request.user, user_b=target) | Q(user_a=target, user_b=request.user),
            unmatched_at__isnull=True,
        ).exists()
        if still_matched:
            sync_im_pair(request.user.id, target.id, add=True)
    return Response(status=204)
