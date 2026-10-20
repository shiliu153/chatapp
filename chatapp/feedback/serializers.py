"""意见反馈的序列化器。

设计要点:
    ``content`` 用 ``CharField`` 而不是直接暴露模型字段,借 DRF 的
    ``trim_whitespace`` 与 ``min_length`` / ``max_length`` 一次校验「去空白后 10–500 字」。
"""

from rest_framework import serializers

from .models import Feedback, FeedbackType


class FeedbackCreateSerializer(serializers.ModelSerializer):
    """反馈入参。"""

    type = serializers.ChoiceField(choices=FeedbackType.choices)
    content = serializers.CharField(min_length=10, max_length=500)
    contact = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")

    class Meta:
        model = Feedback
        fields = ["type", "content", "contact"]


class FeedbackSerializer(serializers.ModelSerializer):
    """反馈的对外回执(不回显处理状态与处理人)。"""

    class Meta:
        model = Feedback
        fields = ["id", "type", "content", "contact", "created_at"]
