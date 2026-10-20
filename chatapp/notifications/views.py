"""推送设备与通知偏好接口。

设计要点:
    1. 上报设备即「单设备」:同一账号只保留最新一台,旧设备记录直接删除;
    2. 解绑只删自己的设备,且不区分「不存在」与「不是你的」—— 一律 204,
       避免泄漏他人设备是否存在;
    3. 偏好读取时按需创建,默认全开。
"""

from django.db import transaction
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .models import NotificationPreference, PushDevice
from .serializers import DeviceSerializer, PreferenceSerializer


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


@api_view(["GET", "PATCH"])
def preferences(request):
    """读取或修改通知偏好(GET/PATCH /api/v1/push/preferences)。

    PATCH 为局部更新:只改传入的字段,未传的保持不变。

    Args:
        request: DRF 请求对象;PATCH 时 body 可带 ``likes`` / ``matches`` / ``system``。

    Returns:
        ``{"likes": bool, "matches": bool, "system": bool}``。
    """
    preference = NotificationPreference.for_user(request.user)
    if request.method == "PATCH":
        serializer = PreferenceSerializer(preference, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
    return Response(PreferenceSerializer(preference).data)
