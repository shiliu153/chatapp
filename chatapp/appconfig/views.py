"""应用版本接口。"""

from django.conf import settings
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@extend_schema(responses={200: inline_serializer("AppConfig", fields={
    "min_app_version": serializers.CharField(),
    "latest_version": serializers.CharField(),
    "download_url": serializers.CharField(),
})})
@api_view(["GET"])
@permission_classes([AllowAny])
def app_config(request):
    """返回客户端启动所需的最低版本配置(GET /api/v1/app/config)。

    参数说明:
        request: DRF 请求对象。

    返回参数:
        ``{min_app_version, latest_version, download_url}``。

    使用示例:
        ``response = self.client.get("/api/v1/app/config")``(见 ``appconfig/tests.py`` 的 ``AppConfigTests``)

    备注信息:
        公开接口(``AllowAny``),不鉴权 —— 客户端要在登录前就知道该不该强制升级;
        三个值分别取 ``settings.MIN_APP_VERSION`` / ``LATEST_APP_VERSION`` /
        ``APP_DOWNLOAD_URL``,``MIN_APP_VERSION`` 同时卡网页端的更新闸门。
    """
    return Response({
        "min_app_version": settings.MIN_APP_VERSION,
        "latest_version": settings.LATEST_APP_VERSION,
        "download_url": settings.APP_DOWNLOAD_URL,
    })
