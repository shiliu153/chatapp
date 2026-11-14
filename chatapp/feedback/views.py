"""意见反馈接口。

关联文档:
    - 接口契约:docs/api/feedback.md

文件信息:
    文件名称          feedback/views.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from .serializers import FeedbackCreateSerializer, FeedbackSerializer
from .throttles import FeedbackThrottle


@extend_schema(request=FeedbackCreateSerializer, responses={201: FeedbackSerializer})
@api_view(["POST"])
@throttle_classes([FeedbackThrottle])
def create_feedback(request):
    """提交意见反馈(POST /api/v1/feedback)。

    参数说明:
        request: DRF 请求对象,body 需带 ``type`` / ``content`` / 可选 ``contact``。

    返回参数:
        201 + 反馈回执(``id`` / ``type`` / ``content`` / ``contact`` / ``created_at``)。

    使用示例:
        ``POST /api/v1/feedback`` body ``{"type": "bug", "content": "夜间模式开关无效", "contact": ""}``

    备注信息:
        必须带登录令牌;``banned_heavy`` 账号由全局权限类挡成 403,``banned_light`` 仍可提交。
        按用户限流(``FeedbackThrottle``),超额 429;字段非法回 400。
    """
    serializer = FeedbackCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    feedback = serializer.save(user=request.user)
    return Response(FeedbackSerializer(feedback).data, status=201)
