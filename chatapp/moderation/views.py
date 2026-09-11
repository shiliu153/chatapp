from django.contrib.auth import get_user_model
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response

from .models import Report, ReportStatus
from .serializers import ReportCreateSerializer, ReportSerializer
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
