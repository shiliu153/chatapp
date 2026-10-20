"""广场动态的数据模型:动态、配图、点赞、评论与动态举报。

设计要点:
    1. ``PostLike`` 对 ``(post, user)`` 有唯一约束,点赞天然幂等;
    2. ``PostReport.post`` 用 ``SET_NULL``:动态被删后举报行仍留档,便于运营对账
       (因此读举报时 ``post`` 可能为 ``None``);
    3. 动态列表依赖 ``Post.Meta.ordering``,但一旦 ``annotate`` 触发 GROUP BY,
       Django 会丢弃 Meta 排序,必须显式 ``order_by`` —— 见 ``services.visible_posts``。
"""

from django.conf import settings
from django.db import models

from moderation.models import ReportStatus, ReportType


class Post(models.Model):
    """一条广场动态。"""

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="posts")
    text = models.TextField("正文", max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``post#主键(作者 id)``。
        """
        return f"post#{self.pk}({self.author_id})"


class PostImage(models.Model):
    """动态的配图(单条最多 9 张,由序列化器校验)。"""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="images")
    file = models.ImageField("图片", upload_to="posts/%Y/%m/")
    order = models.PositiveSmallIntegerField("排序", default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``post_image#主键(post=动态 id)``。
        """
        return f"post_image#{self.pk}(post={self.post_id})"


class PostLike(models.Model):
    """一条点赞记录。"""

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="post_likes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["post", "user"], name="uniq_post_like"),
        ]

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``post_like(动态 id:用户 id)``。
        """
        return f"post_like({self.post_id}:{self.user_id})"


class PostComment(models.Model):
    """一条动态评论;``parent`` 非空表示它是某条顶级评论下的回复。

    层级恒为两级:回复的回复由 ``services.create_comment`` 归一到顶级评论,
    ``parent`` 永远指向顶级评论;``reply_to`` 记录"回复的是谁",用于渲染
    「回复 @昵称」与发送提醒。
    """

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="post_comments")
    parent = models.ForeignKey("self", null=True, blank=True,
                               on_delete=models.CASCADE, related_name="replies")
    reply_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL,
                                 related_name="comment_replies_received")
    text = models.CharField("内容", max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``post_comment#主键(post=动态 id)``。
        """
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
        """后台与日志中的可读表示。

        Returns:
            ``post_report#主键(举报人->动态:类型)``。
        """
        return f"post_report#{self.pk}({self.reporter_id}->{self.post_id}:{self.type})"
