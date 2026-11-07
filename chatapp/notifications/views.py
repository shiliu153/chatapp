"""推送设备与通知偏好接口,以及站内通知中心接口。

设计要点:
    1. 上报设备即「单设备」:同一账号只保留最新一台,旧设备记录直接删除
       (与「单设备登录」一致);
    2. 解绑只删自己的设备,且不区分「不存在」与「不是你的」—— 一律 204,
       避免泄漏他人设备是否存在;
    3. 偏好读取时按需创建,默认全开;
    4. 站内通知**只返回 90 天内、只返回自己的**:查询侧截断,物理删除交给
       ``notifications_prune`` 命令(不接 cron,取舍见计划 §2.3);
    5. 已读接口只影响自己的通知:别人的 id 混进来会被 user 条件过滤掉,仍然 204
       (不泄漏「这条通知是否存在」)。

关联文档:
    - 接口契约:docs/api/push.md(推送设备与偏好)、docs/api/notifications.md(站内通知)
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from config.cursor import paginated_response
from config.schema_helpers import cursor_page, cursor_params

from .models import InAppNotification, NotificationPreference, PushDevice
from .serializers import (DeviceResponseSerializer, DeviceSerializer, NotificationItemSerializer,
                          NotificationReadSerializer, PushPreferenceSerializer,
                          UnreadCountSerializer, notification_payload)
from .throttles import NotificationsThrottle, NotificationsUnreadThrottle

# 通知中心只展示最近 90 天:更早的记录仍留在库里,由 ``notifications_prune`` 回收。
NOTIFICATION_WINDOW_DAYS = 90


@extend_schema(request=DeviceSerializer, responses={200: DeviceResponseSerializer})
@api_view(["POST"])
def register_device(request):
    """上报推送设备(POST /api/v1/push/devices)。

    幂等:同一 registration_id 重复上报只更新归属与版本;同账号的其他设备被删除。

    Args:
        request: DRF 请求对象,body 需带 ``registration_id`` 与 ``platform``。

    Returns:
        ``{"registration_id": str, "platform": str}``。
    """
    serializer = DeviceSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    me = request.user
    with transaction.atomic():
        PushDevice.objects.update_or_create(
            registration_id=data["registration_id"],
            defaults={
                "user": me,
                "platform": data["platform"],
                "app_version": data.get("app_version", ""),
            },
        )
        PushDevice.objects.filter(user=me).exclude(
            registration_id=data["registration_id"]).delete()
    return Response({"registration_id": data["registration_id"],
                     "platform": data["platform"]})


@extend_schema(request=None, responses={204: None})
@api_view(["DELETE"])
def unregister_device(request, registration_id):
    """解绑推送设备(DELETE /api/v1/push/devices/{registration_id})。

    幂等:设备不存在、或属于别人,一律 204(不泄漏他人设备信息)。

    Args:
        request: DRF 请求对象。
        registration_id: 极光 registration_id。

    Returns:
        204 空响应。
    """
    PushDevice.objects.filter(user=request.user, registration_id=registration_id).delete()
    return Response(status=204)


@extend_schema(methods=["GET"], responses={200: PushPreferenceSerializer})
@extend_schema(methods=["PATCH"], request=PushPreferenceSerializer,
               responses={200: PushPreferenceSerializer})
@api_view(["GET", "PATCH"])
def preferences(request):
    """读取或修改通知偏好(GET/PATCH /api/v1/push/preferences)。

    PATCH 为局部更新:只改传入的字段,未传的保持不变。

    Args:
        request: DRF 请求对象;PATCH 时 body 可带
            ``likes`` / ``matches`` / ``messages`` / ``system`` / ``social``。

    Returns:
        ``{"likes": bool, "matches": bool, "messages": bool, "system": bool, "social": bool}``。
    """
    preference = NotificationPreference.for_user(request.user)
    if request.method == "PATCH":
        serializer = PushPreferenceSerializer(preference, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
    return Response(PushPreferenceSerializer(preference).data)


def _visible_notifications(user):
    """当前用户 90 天内可见的通知查询集(列表与未读数共用同一口径)。

    Args:
        user: 当前用户。

    Returns:
        已按 ``-created_at, -id`` 排序、并预取触发者资料与照片的查询集
        (预取是为了列表序列化时不产生 N+1)。
    """
    cutoff = timezone.now() - timedelta(days=NOTIFICATION_WINDOW_DAYS)
    return (InAppNotification.objects
            .filter(user=user, created_at__gte=cutoff)
            .select_related("actor__profile")
            .prefetch_related("actor__photos"))


@extend_schema(methods=["GET"], parameters=cursor_params(),
               responses={200: cursor_page("NotificationPage", NotificationItemSerializer)})
@api_view(["GET"])
@throttle_classes([NotificationsThrottle])
def notification_list(request):
    """站内通知列表(GET /api/v1/notifications)。

    只返回自己的、90 天内的通知,按时间倒序;默认走复合游标分页
    (``{count, next_cursor, has_more, results}``),带 ``offset`` 的老客户端
    仍走 offset 兼容路径。

    Args:
        request: DRF 请求对象,提供 ``limit`` / ``before``(或兼容的 ``offset``)。

    Returns:
        分页后的通知列表;``results[]`` 每项含触发者摘要与跳转目标。
    """
    return paginated_response(
        request, _visible_notifications(request.user),
        lambda rows: NotificationItemSerializer(
            [notification_payload(row, request) for row in rows], many=True).data,
        field="created_at")


@extend_schema(methods=["GET"], responses={200: UnreadCountSerializer})
@api_view(["GET"])
@throttle_classes([NotificationsUnreadThrottle])
def notification_unread_count(request):
    """未读通知数(GET /api/v1/notifications/unread_count)。

    口径与列表完全一致(自己的、90 天内),供消息页铃铛角标使用。

    Args:
        request: DRF 请求对象。

    Returns:
        ``{"unread": n}``。
    """
    unread = _visible_notifications(request.user).filter(is_read=False).count()
    return Response({"unread": unread})


@extend_schema(methods=["POST"], request=NotificationReadSerializer, responses={204: None})
@api_view(["POST"])
def notification_read(request):
    """标记已读(POST /api/v1/notifications/read)。

    两种用法:``{"ids": [...]}`` 只标指定几条,``{"all": true}`` 标全部未读。
    只影响自己的通知,幂等 204;别人的 id 混进来会被静默过滤。

    Args:
        request: DRF 请求对象;body 需带 ``ids`` 或 ``all=true``。

    Returns:
        204 空响应。
    """
    serializer = NotificationReadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    queryset = _visible_notifications(request.user).filter(is_read=False)
    if serializer.validated_data.get("all"):
        queryset.update(is_read=True)
    else:
        queryset.filter(pk__in=serializer.validated_data["ids"]).update(is_read=True)
    return Response(status=204)
