from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from . import services
from .serializers import PhoneSerializer
from .throttles import SmsSendThrottle


@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    return Response({"status": "ok"})


@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([SmsSendThrottle])
def sms_send(request):
    serializer = PhoneSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    services.send_code(serializer.validated_data["phone"])
    return Response({"status": "ok"})
