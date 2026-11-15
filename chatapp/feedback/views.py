"""意见反馈接口。

关联文档:
    - 接口契约:docs/api/feedback.md
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
        ``return self.client.post(self.URL, payload, format="json")``(见 ``feedback/tests.py``
        的 ``FeedbackCreateTests._post``,其 ``URL`` 即 ``/api/v1/feedback``)

    备注信息:
        落库时状态恒为 ``pending``(``status`` 不回给客户端);``content`` 去首尾空白后
        须 10~500 字,``contact`` 最长 64 字(超限 400,见 ``FeedbackCreateSerializer``)。
        重封禁账号被全局权限类拦成 403,轻封禁仍可提交(见 ``feedback/tests.py`` 的
        ``test_light_banned_can_submit``);限流走 ``FeedbackThrottle``(按用户,超限 429)。
    """
    serializer = FeedbackCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    feedback = serializer.save(user=request.user)
    return Response(FeedbackSerializer(feedback).data, status=201)
