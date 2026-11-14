"""意见反馈的序列化器。

设计要点:
    ``content`` 用 ``CharField`` 而不是直接暴露模型字段,借 DRF 的
    ``trim_whitespace`` 与 ``min_length`` / ``max_length`` 一次校验「去空白后 10–500 字」。

文件信息:
    文件名称          feedback/serializers.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
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
