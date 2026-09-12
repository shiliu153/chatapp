from django.db.models import Count, Exists, OuterRef

from moderation.services import blocked_user_ids
from users.models import ProfileStatus

from .models import Post, PostLike


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
