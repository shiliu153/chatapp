from rest_framework import serializers

from .models import Report, ReportType


class ReportCreateSerializer(serializers.Serializer):
    target_user_id = serializers.IntegerField()
    type = serializers.ChoiceField(choices=ReportType.choices)
    detail = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class ReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = Report
        fields = ["id", "type", "status"]
