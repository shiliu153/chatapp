"""广场动态的领域服务:可见性查询、删除与评论通知。

设计要点:
    1. ``visible_posts`` 是广场**唯一的可见性口径**:排除双向拉黑与重封禁作者,
       并统一注解赞数/评数与「我是否已赞」,避免各处各写一份查询;
    2. ``delete_post`` 同时服务作者自删与运营删除,因此必须先关闭待处理举报,
       否则作者自删后举报会在审核台里悬空。
"""

from django.db import transaction
from django.db.models import Count, Exists, OuterRef
from django.utils import timezone

from im import tasks as im_tasks
from moderation.models import ReportStatus
from moderation.services import blocked_user_ids, notify_report_handled
from users.models import ProfileStatus

from .models import Post, PostComment, PostLike, PostReport


def visible_posts(viewer):
    """广场可见动态:排除双向拉黑与重封禁作者;命中注解赞/评数与「我是否已赞」。

    Args:
        viewer: 当前浏览者。

    Returns:
        已注解 ``like_count`` / ``comment_count`` / ``liked_by_me`` 的查询集。
    """
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

    Args:
        post: 待删除的动态。
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


def notify_comment_created(comment) -> None:
    """评论创建后调用:顶级评论通知动态作者,回复通知被回复者。

    自己评论自己的动态、自己回复自己都不入队(不打扰)。

    Args:
        comment: 刚创建的评论或回复。
    """
    if comment.parent_id is None:
        if comment.post.author_id == comment.author_id:
            return
        transaction.on_commit(lambda: im_tasks.post_commented.delay(comment.id),
                              robust=True)
        return
    if comment.reply_to_id is None or comment.reply_to_id == comment.author_id:
        return
    transaction.on_commit(lambda: im_tasks.post_replied.delay(comment.id), robust=True)


def visible_comments(post, viewer):
    """某条动态下对 ``viewer`` 可见的评论与回复,按时间正序。

    Args:
        post: 目标动态。
        viewer: 当前浏览者。

    Returns:
        排除双向拉黑与重封禁作者后的评论查询集;作者与被回复者已预取。
    """
    blocked = blocked_user_ids(viewer)
    return (post.comments
            .exclude(author_id__in=blocked)
            .exclude(author__profile__status=ProfileStatus.BANNED_HEAVY)
            .select_related("author__profile", "reply_to__profile")
            .prefetch_related("author__photos"))


def create_comment(post, author, text, parent=None):
    """创建评论或回复,并把层级归一到两级。

    Args:
        post: 被评论的动态。
        author: 评论者。
        text: 已通过校验的正文。
        parent: 被回复的评论(调用方已确认它属于 ``post``);``None`` 表示顶级评论。

    Returns:
        新建的 ``PostComment``;回复的 ``parent`` 一定是顶级评论,
        ``reply_to`` 是真正被回复的那个人。
    """
    if parent is None:
        return PostComment.objects.create(post=post, author=author, text=text)
    root = parent.parent or parent
    return PostComment.objects.create(post=post, author=author, text=text,
                                      parent=root, reply_to=parent.author)


def delete_comment(comment) -> None:
    """删除一条评论;删顶级评论时回复由数据库 CASCADE 一并删除。

    Args:
        comment: 待删除的评论(调用方已校验作者身份)。
    """
    comment.delete()
