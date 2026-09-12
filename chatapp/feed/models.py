from django.conf import settings
from django.db import models

from moderation.models import ReportStatus, ReportType


class Post(models.Model):
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="posts")
    text = models.TextField("正文", max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"post#{self.pk}({self.author_id})"


class PostImage(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="images")
    file = models.ImageField("图片", upload_to="posts/%Y/%m/")
    order = models.PositiveSmallIntegerField("排序", default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        return f"post_image#{self.pk}(post={self.post_id})"


class PostLike(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="post_likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["post", "user"], name="uniq_post_like"),
        ]

    def __str__(self):
        return f"post_like({self.post_id}:{self.user_id})"


class PostComment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="post_comments")
    text = models.CharField("内容", max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"post_comment#{self.pk}(post={self.post_id})"


class PostReport(models.Model):
    """动态举报;post 用 SET_NULL:动态删除后举报行留档(运营对账)。"""

    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="post_reports")
    post = models.ForeignKey(Post, null=True, on_delete=models.SET_NULL,
                             related_name="reports")
    type = models.CharField("类型", max_length=20, choices=ReportType.choices)
    detail = models.CharField("补充说明", max_length=200, blank=True)
    status = models.CharField("状态", max_length=10, choices=ReportStatus.choices,
                              default=ReportStatus.PENDING)
    handled_note = models.CharField("处理备注", max_length=200, blank=True)
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="post_reports_handled")
    created_at = models.DateTimeField(auto_now_add=True)
    handled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"post_report#{self.pk}({self.reporter_id}->{self.post_id}:{self.type})"
