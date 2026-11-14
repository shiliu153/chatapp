"""用户意见反馈的数据模型。

设计要点:
    反馈与举报分开建模:举报有「被举报人」与处理动作,反馈只有内容与处理状态。
    ``user`` 用 ``CASCADE`` —— 注销账号即删除其全部反馈,与「注销 = 删除全部数据」一致;
    ``handled_by`` 用 ``SET_NULL`` —— 运营账号被删不应连带删除用户反馈。

文件信息:
    文件名称          feedback/models.py
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
from django.db import models


class FeedbackType(models.TextChoices):
    """反馈类型。"""

    FEATURE = "feature", "功能建议"
    BUG = "bug", "问题反馈"
    ACCOUNT = "account", "账号问题"
    OTHER = "other", "其他"


class FeedbackStatus(models.TextChoices):
    """反馈处理状态。"""

    PENDING = "pending", "待处理"
    HANDLED = "handled", "已处理"


class Feedback(models.Model):
    """一条用户意见反馈。

    参数说明:
        无。实例由 Django ORM 按字段构造,不接受显式构造参数。

    返回参数:
        ``Feedback`` 实例。

    使用示例:
        ``Feedback.objects.create(user=request.user, type="bug", content="夜间模式开关无效")``

    备注信息:
        ``handled_by`` 是处理人(运营账号),未处理时为 ``None``;``handled_at`` 是首次标记已处理的时间。
        ``user`` 级联删除、``handled_by`` 置空,取舍见模块 docstring。默认按 ``created_at`` 倒序。
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="feedbacks")
    type = models.CharField("类型", max_length=20, choices=FeedbackType.choices)
    content = models.TextField("反馈内容", max_length=500)
    contact = models.CharField("联系方式", max_length=64, blank=True)
    status = models.CharField("状态", max_length=10, choices=FeedbackStatus.choices,
                              default=FeedbackStatus.PENDING)
    handled_note = models.CharField("处理备注", max_length=200, blank=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="feedbacks_handled")
    created_at = models.DateTimeField(auto_now_add=True)
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``feedback#主键(用户:类型)``。

        使用示例:
            ``str(feedback)``

        备注信息:
            只用于 Django 后台与日志,不进对外接口响应。
        """
        return f"feedback#{self.pk}({self.user_id}:{self.type})"
