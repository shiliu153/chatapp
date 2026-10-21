"""应用版本接口。"""

from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response


@api_view(["GET"])
@permission_classes([AllowAny])
def app_config(request):
    """返回客户端启动所需的最低版本配置。

    Args:
        request: DRF 请求对象。

    Returns:
        ``{min_app_version, latest_version, download_url}``。
    """
    return Response({
        "min_app_version": settings.MIN_APP_VERSION,
        "latest_version": settings.LATEST_APP_VERSION,
        "download_url": settings.APP_DOWNLOAD_URL,
    })
