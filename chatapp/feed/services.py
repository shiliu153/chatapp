from django.db.models import Count, Exists, OuterRef
from django.utils import timezone

from moderation.models import ReportStatus
from moderation.services import blocked_user_ids, notify_report_handled
from users.models import ProfileStatus

from .models import Post, PostLike, PostReport


def visible_posts(viewer):
    """广场可见动态:排除双向拉黑与重封禁作者;命中注解赞/评数与「我是否已赞」。"""
    blocked = blocked_user_ids(viewer)
    return (Post.objects
            .exclude(author_id__in=blocked)
            .exclude(author__profile__status=ProfileStatus.BANNED_HEAVY)
            .select_related("author__profile")
            .prefetch_related("author__photos", "images")
            .annotate(like_count=Count("likes", distinct=True),
                      comment_count=Count("comments", distinct=True),
                      liked_by_me=Exists(
                          PostLike.objects.filter(post=OuterRef("pk"), user=viewer)))
            # annotate 触发 GROUP BY 时 Meta.ordering 会被丢弃,必须显式排序
            .order_by("-created_at", "-id"))


def delete_post(post) -> None:
    """删除动态:先关闭该动态全部待处理举报(标记 + 通知),再删图片文件与行。

    作者自删与运营删除共用:否则作者自删后举报会在 ops 队列里悬空。
    """
    pending = list(PostReport.objects.filter(post=post, status=ReportStatus.PENDING))
    for report in pending:
        report.status = ReportStatus.HANDLED
        report.handled_note = "动态已删除"
        report.handled_at = timezone.now()
        report.save(update_fields=["status", "handled_note", "handled_at"])
        notify_report_handled(report)   # 内部 on_commit 入队
    for image in post.images.all():
        image.file.delete(save=False)
    post.delete()
