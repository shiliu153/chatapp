"""应用版本接口。

文件信息:
    文件名称          appconfig/views.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

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
        ``GET /api/v1/app/config``

    备注信息:
        匿名可调(``AllowAny``):App 启动时还没登录就要判断是否强制更新。
        三个值全部读 ``settings``,不查库,因此没有缓存与失效问题。
    """
    return Response({
        "min_app_version": settings.MIN_APP_VERSION,
        "latest_version": settings.LATEST_APP_VERSION,
        "download_url": settings.APP_DOWNLOAD_URL,
    })
