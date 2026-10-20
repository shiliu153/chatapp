"""意见反馈接口。

关联文档:
    - 接口契约:docs/api/feedback.md
"""

from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from .serializers import FeedbackCreateSerializer, FeedbackSerializer
from .throttles import FeedbackThrottle


@api_view(["POST"])
@throttle_classes([FeedbackThrottle])
def create_feedback(request):
    """提交意见反馈(POST /api/v1/feedback)。

    Args:
        request: DRF 请求对象,body 需带 ``type`` / ``content`` / 可选 ``contact``。

    Returns:
        201 + 反馈回执(``id`` / ``type`` / ``content`` / ``contact`` / ``created_at``)。
    """
    serializer = FeedbackCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    feedback = serializer.save(user=request.user)
    return Response(FeedbackSerializer(feedback).data, status=201)
