"""广场动态的领域服务:可见性查询、删除、评论通知、收藏分页与关注关系。

设计要点:
    1. ``visible_posts`` 是广场**唯一的可见性口径**:排除双向拉黑与重封禁作者,
       并统一注解赞数/评数、「我是否已赞」与「我是否已收藏」,避免各处各写一份查询;
    2. ``delete_post`` 同时服务作者自删与运营删除,因此必须先关闭待处理举报,
       否则作者自删后举报会在审核台里悬空;
    3. 关注是**有向**关系且不产生聊天权限:``follow`` / ``unfollow`` 只动 ``Follow`` 表,
       不发通知、不碰 IM(新粉丝不通知,见计划 §2.3);
    4. ``follow_state_for_profiles`` 是「资料卡关注态」的唯一取数口径:单条走一条
       聚合 SQL,批量走三条分组 SQL,**不随资料条数增长**;
    5. 「我是否已收藏」和「我是否已赞」一样是 ``Exists`` 子查询注解,嵌在同一条 SQL 里
       —— 在序列化器里逐条 ``.exists()`` 会让广场一页 20 条变成 20 次往返
       (``config/test_query_budget.py`` 会红)。

文件信息:
    文件名称          feed/services.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from typing import NamedTuple

from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from config.cursor import apply_before, encode_cursor
from im import tasks as im_tasks
from moderation.models import ReportStatus
from moderation.services import blocked_user_ids, notify_report_handled
from notifications.models import NotificationKind, NotificationTarget
from notifications.services import display_name, notify_on_commit
from users.models import Profile, ProfileStatus

from .models import Follow, Post, PostComment, PostFavorite, PostLike, PostReport


class FeedPage(NamedTuple):
    """广场动态流的一页(两段式取数的结果)。

    Attributes:
        rows: 当页 ``Post`` 列表(已带赞/评数与作者信息)。
        total: 可见动态总数。
        has_more: 是否还有下一页。
        next_cursor: 下一页的游标;没有下一页时为 ``None``。

    参数说明:
        无(``NamedTuple``,按位置或关键字传 ``rows`` / ``total`` / ``has_more`` /
        ``next_cursor`` 四个字段)。

    返回参数:
        实例化得到不可变的四元组,字段可用属性名读取。

    使用示例:
        ``FeedPage(rows=[], total=0, has_more=False, next_cursor=None)``

    备注信息:
        ``total`` 是**过滤后**的可见总数(与页面数据同口径),不是全表条数;
        ``next_cursor`` 只在 ``has_more`` 为真时非空,视图直接把它写进响应体。
    """

    rows: list
    total: int
    has_more: bool
    next_cursor: str | None


def visible_base(viewer):
    """广场可见性的基础查询集(不注解、不预取),用于取当页 id 与总数。

    重封禁作者用**子查询**而不是 ``author__profile__status`` 关联过滤:后者会生成
    LEFT JOIN,MySQL 优化器因此放弃 ``created_at`` 索引、改成全表扫 + filesort
    (2026-11-03 实测 10 万条动态 214ms;改 NOT IN 子查询后走索引,同数据量 ~1ms)。

    参数说明:
        viewer: 当前浏览者。

    返回参数:
        只带可见性过滤的 ``Post`` 查询集。

    使用示例:
        ``get_object_or_404(visible_base(request.user), pk=post_id)``

    备注信息:
        排除两类作者:与 ``viewer`` 双向拉黑的人(``blocked_user_ids``)与
        ``ProfileStatus.BANNED_HEAVY`` 的账号;``blocked_user_ids`` 每次调用执行一次 SQL,
        分页场景下要把本函数的结果传下去复用,别重复调用。
    """
    blocked = blocked_user_ids(viewer)
    banned_author_ids = Profile.objects.filter(
        status=ProfileStatus.BANNED_HEAVY).values("user_id")
    return (Post.objects
            .exclude(author_id__in=blocked)
            .exclude(author_id__in=banned_author_ids))


def visible_posts(viewer, base=None):
    """广场可见动态:排除双向拉黑与重封禁作者;注解赞/评数与「我是否已赞/已收藏」。

    参数说明:
        viewer: 当前浏览者。
        base: 已构建的可见性查询集(可选)。分页场景下复用同一个 base,
            避免 ``blocked_user_ids`` 被重复执行两次。

    返回参数:
        已注解 ``like_count`` / ``comment_count`` / ``liked_by_me`` /
        ``is_favorited`` 的查询集。

    使用示例:
        ``visible_posts(request.user).get(pk=post.pk)``

    备注信息:
        注解里有 ``COUNT(DISTINCT)``,直接切片会先对全表分组(LIMIT 失效),
        列表取数请走 ``page_visible_posts`` 的两段式;
        ``order_by`` 必须显式写 —— ``annotate`` 触发 GROUP BY 后 ``Meta.ordering`` 会被丢弃。
        ``liked_by_me`` / ``is_favorited`` 是 ``Exists`` 子查询,不新增往返。
    """
    return ((base if base is not None else visible_base(viewer))
            .select_related("author__profile")
            .prefetch_related("author__photos", "images")
            .annotate(like_count=Count("likes", distinct=True),
                      comment_count=Count("comments", distinct=True),
                      liked_by_me=Exists(
                          PostLike.objects.filter(post=OuterRef("pk"), user=viewer)),
                      # 收藏态与点赞态同款:一条 EXISTS 子查询嵌进同一条 SQL,
                      # 不新增任何往返(禁止改成序列化器里的逐条 .exists())。批次 U。
                      is_favorited=Exists(
                          PostFavorite.objects.filter(post=OuterRef("pk"), user=viewer)))
            # annotate 触发 GROUP BY 时 Meta.ordering 会被丢弃,必须显式排序
            .order_by("-created_at", "-id"))


def following_base(viewer):
    """关注流的可见性基础查询集:只含**我关注的人**,不含自己。

    可见性复用 :func:`visible_base`(排除双向拉黑与重封禁作者),只是把作者范围
    收窄到我的关注列表 —— 与广场主流程同一套规则,不另立口径。关注流**不含自己**
    的动态:自己的动态在 ``/posts/mine``,混进来会让「关注」tab 变成第二个「我的」。

    参数说明:
        viewer: 当前浏览者。

    返回参数:
        只含关注者动态的基础查询集(未注解、未预取)。

    使用示例:
        ``page_visible_posts(request.user, limit, base=following_base(request.user))``

    备注信息:
        我关注的人一个都没有时返回空集,``total`` 就是 0,不报错;
        结果要交给 ``page_visible_posts`` 再注解,别直接序列化。
    """
    followee_ids = Follow.objects.filter(follower=viewer).values("followee_id")
    return (visible_base(viewer)
            .filter(author_id__in=followee_ids)
            .exclude(author_id=viewer.id))


def page_visible_posts(viewer, limit: int, before: tuple | None = None,
                       offset: int | None = None, base=None) -> "FeedPage":
    """两段式取一页动态:先按索引取当页 id,再只对这几条做聚合。

    为什么不能直接 ``visible_posts(viewer)[offset:offset+limit]``:注解里有
    ``COUNT(DISTINCT)``,MySQL 必须先把**全表**分组完才能 LIMIT;10 万条动态时
    单次请求实测 3.3 秒。拆成「取 id(走 created_at 索引) + 对 10 条聚合」后,
    成本与数据量脱钩。

    翻页用**复合游标**而不是 offset(审查 N-5):动态流是头部持续插入的列表,
    offset 在「读完第 1 页、又有人发了新动态」时必然重复一条并漏掉一条。
    ``offset`` 参数只为还在用老版本客户端的设备保留。

    参数说明:
        viewer: 当前浏览者。
        limit: 每页条数。
        before: 游标 ``(created_at, id)``;``None`` 表示第一页。
        offset: 旧客户端兼容用的跳过条数;``None``/0 表示不用。
        base: 已构建的可见性查询集(可选)。关注流传 :func:`following_base`,
            广场主流程不传(等价于 ``visible_base(viewer)``)。

    返回参数:
        当页的 ``FeedPage``(行、可见总数、是否还有下一页、下一页游标)。

    使用示例:
        ``page_visible_posts(request.user, 20, before=read_before(request))``

    备注信息:
        多取一条(``limit + 1``)判断 ``has_more``;游标记的是当页最后一条的
        ``(created_at, id)``,由 ``apply_before`` 做「严格小于」过滤,因此不会重复。
        当页 id 拿到后按原顺序还原 —— ``pk__in`` 不保序,Django 也不会额外排序。
    """
    base = base if base is not None else visible_base(viewer)
    total = base.count()
    ordered = base.order_by("-created_at", "-id")
    if before is not None:
        ordered = apply_before(ordered, "created_at", before)
    if offset:
        ordered = ordered[offset:]
    pairs = list(ordered.values_list("id", "created_at")[:limit + 1])
    has_more = len(pairs) > limit
    pairs = pairs[:limit]
    if not pairs:
        return FeedPage(rows=[], total=total, has_more=False, next_cursor=None)
    ids = [post_id for post_id, _ in pairs]
    rows = {post.pk: post for post in visible_posts(viewer, base=base).filter(pk__in=ids)}
    next_cursor = None
    if has_more:
        last_id, last_at = pairs[-1]
        next_cursor = encode_cursor(last_at, last_id)
    return FeedPage(rows=[rows[post_id] for post_id in ids if post_id in rows],
                    total=total, has_more=has_more, next_cursor=next_cursor)


def visible_likers(post, viewer):
    """某条动态下对 ``viewer`` 可见的点赞者,按点赞时间倒序。

    可见性沿用评论那套「双向拉黑 + 重封禁作者」口径(不另立一份):
    我拉黑的 / 拉黑我的人、以及被重封禁的账号,不出现点赞列表里,
    因此接口回执的 ``count`` 是**过滤后**的人数,而不是原始点赞行数。

    ``select_related("user__profile")`` + ``prefetch_related("user__photos")`` 是
    ``author_brief`` 的取数前提:两条 SQL 固定,与页大小无关(禁止循环里查库)。

    参数说明:
        post: 目标动态(调用方已确认它对 ``viewer`` 可见)。
        viewer: 当前浏览者。

    返回参数:
        已按 ``-created_at, -id`` 排序、带作者信息预取的 ``PostLike`` 查询集。

    使用示例:
        ``visible_likers(post, request.user).count()``

    备注信息:
        只过滤点赞者,不再校验动态本身是否可见 —— 那是调用方
        (``get_object_or_404(visible_base(...))``)的责任;
        分页由 ``config.cursor.slice_page`` 在 ``created_at`` 上做。
    """
    banned_user_ids = Profile.objects.filter(
        status=ProfileStatus.BANNED_HEAVY).values("user_id")
    return (PostLike.objects.filter(post=post)
            .exclude(user_id__in=blocked_user_ids(viewer))
            .exclude(user_id__in=banned_user_ids)
            .select_related("user__profile")
            .prefetch_related("user__photos")
            .order_by("-created_at", "-id"))


def page_favorite_posts(viewer, limit: int, before: tuple | None = None) -> "FeedPage":
    """「我的收藏」一页:排序与游标都建在**收藏行**上,不是发帖时间。

    实现是两段式(与 :func:`page_visible_posts` 同构,但游标换了一行):
        1. 先算可见帖子集 ``base``,只在其中取我的收藏行(收藏了但已被拉黑/封禁的
           动态连 ``count`` 都不算);
        2. 按 ``PostFavorite.created_at`` 倒序取 ``limit + 1`` 个 ``(post_id,
           created_at, id)`` 判断 ``has_more`` 并记录游标 —— 游标指向收藏行,
           所以「先收藏新帖、后收藏老帖」时顺序按收藏时间走,不会退化成发帖时间;
        3. 再用 :func:`visible_posts` 取当页带注解的对象,并按第 2 步的顺序还原
           (``pk__in`` 不保序,Django 也不会额外排序)。

    动态被删时 ``PostFavorite`` 随 ``CASCADE`` 一起消失,列表自动少一条,
    不需要额外的清理逻辑。

    参数说明:
        viewer: 当前浏览者(收藏的归属人)。
        limit: 每页条数。
        before: 游标 ``(收藏行 created_at, 收藏行 id)``;``None`` 表示第一页。

    返回参数:
        当页的 :class:`FeedPage`(``rows`` 为 ``Post``,``total`` 为可见收藏总数)。

    使用示例:
        ``page_favorite_posts(request.user, 20, before=read_before(request))``

    备注信息:
        游标里的 ``created_at`` / ``id`` 都是**收藏行**的,与动态的发布时间无关;
        收藏了但已不可见的动态既不出现在 ``rows``,也不计入 ``total``。
    """
    base = visible_base(viewer)
    favorites = PostFavorite.objects.filter(user=viewer,
                                            post_id__in=base.values("id"))
    total = favorites.count()
    ordered = favorites.order_by("-created_at", "-id")
    if before is not None:
        ordered = apply_before(ordered, "created_at", before)
    rows = list(ordered.values_list("post_id", "created_at", "id")[:limit + 1])
    has_more = len(rows) > limit
    rows = rows[:limit]
    if not rows:
        return FeedPage(rows=[], total=total, has_more=False, next_cursor=None)
    post_ids = [post_id for post_id, _, _ in rows]
    posts = {post.pk: post for post in visible_posts(viewer, base=base)
             .filter(pk__in=post_ids)}
    next_cursor = None
    if has_more:
        _, last_at, last_id = rows[-1]
        next_cursor = encode_cursor(last_at, last_id)
    return FeedPage(rows=[posts[post_id] for post_id in post_ids if post_id in posts],
                    total=total, has_more=has_more, next_cursor=next_cursor)


def delete_post(post) -> None:
    """删除动态:先关闭该动态全部待处理举报(标记 + 通知),再删图片文件与行。

    作者自删与运营删除共用:否则作者自删后举报会在 ops 队列里悬空。

    参数说明:
        post: 待删除的动态。

    返回参数:
        无返回值。

    使用示例:
        ``delete_post(post)``

    备注信息:
        顺序不可颠倒:待处理举报先置 ``HANDLED`` 并把 ``handled_note`` 写成
        「动态已删除」,再逐个删图片文件(``save=False`` 只动磁盘),最后删行动态
        (配图、点赞、收藏、评论随 ``CASCADE`` 一起消失);举报行本身留档。
        ``notify_report_handled`` 内部走 ``on_commit`` 入队。
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

    站内通知(批次 H)与 IM 灰条**并存**:灰条是聊天记录里的事实,通知是聚合索引;
    这里只追加通知调用,不改灰条的入队条件与次数。

    参数说明:
        comment: 刚创建的评论或回复。

    返回参数:
        无返回值(通知与灰条都在事务提交后入队)。

    使用示例:
        ``notify_comment_created(comment)``

    备注信息:
        两条链路都用 ``transaction.on_commit(..., robust=True)``,因此必须在
        「已经用本评论参与事务」的请求路径里调用,否则通知要等提交才发。
        顶级评论走 ``im_tasks.post_commented`` + ``POST_COMMENT`` 通知,
        回复走 ``im_tasks.post_replied`` + ``COMMENT_REPLY`` 通知,
        ``dedupe_key`` 分别是 ``comment:{id}`` / ``reply:{id}``。
    """
    if comment.parent_id is None:
        if comment.post.author_id == comment.author_id:
            return
        transaction.on_commit(lambda: im_tasks.post_commented.delay(comment.id),
                              robust=True)
        notify_on_commit(
            comment.post.author_id, NotificationKind.POST_COMMENT,
            actor_id=comment.author_id, target_kind=NotificationTarget.POST,
            target_id=comment.post_id,
            text=f"{display_name(comment.author)} 评论了你的动态:{comment.text[:30]}",
            dedupe_key=f"comment:{comment.id}")
        return
    if comment.reply_to_id is None or comment.reply_to_id == comment.author_id:
        return
    transaction.on_commit(lambda: im_tasks.post_replied.delay(comment.id), robust=True)
    notify_on_commit(
        comment.reply_to_id, NotificationKind.COMMENT_REPLY, actor_id=comment.author_id,
        target_kind=NotificationTarget.POST, target_id=comment.post_id,
        text=f"{display_name(comment.author)} 回复了你的评论:{comment.text[:30]}",
        dedupe_key=f"reply:{comment.id}")


def visible_comments(post, viewer):
    """某条动态下对 ``viewer`` 可见的评论与回复,按时间正序。

    参数说明:
        post: 目标动态。
        viewer: 当前浏览者。

    返回参数:
        排除双向拉黑与重封禁作者后的评论查询集;作者与被回复者已预取。

    使用示例:
        ``visible_comments(post, request.user).filter(parent__isnull=True)``

    备注信息:
        排序取 ``PostComment.Meta.ordering``(``created_at, id`` 正序),查询集里不再写
        ``order_by``;重封禁过滤用 ``author__profile__status`` 关联条件 —— 只在这条
        已按动态收窄的查询上,不影响广场主列表的索引选择。
    """
    blocked = blocked_user_ids(viewer)
    return (post.comments
            .exclude(author_id__in=blocked)
            .exclude(author__profile__status=ProfileStatus.BANNED_HEAVY)
            .select_related("author__profile", "reply_to__profile")
            .prefetch_related("author__photos"))


def create_comment(post, author, text, parent=None):
    """创建评论或回复,并把层级归一到两级。

    参数说明:
        post: 被评论的动态。
        author: 评论者。
        text: 已通过校验的正文。
        parent: 被回复的评论(调用方已确认它属于 ``post``);``None`` 表示顶级评论。

    返回参数:
        新建的 ``PostComment``;回复的 ``parent`` 一定是顶级评论,
        ``reply_to`` 是真正被回复的那个人。

    使用示例:
        ``create_comment(post, request.user, "好看", parent=comment)``

    备注信息:
        「回复的回复」由 ``parent.parent or parent`` 归一到顶级评论,
        ``reply_to`` 取被回复那条的作者,因此层级恒为两级;
        本函数不校验正文违禁词,也不发通知 —— 两者分别由序列化器与
        ``notify_comment_created`` 负责。
    """
    if parent is None:
        return PostComment.objects.create(post=post, author=author, text=text)
    root = parent.parent or parent
    return PostComment.objects.create(post=post, author=author, text=text,
                                      parent=root, reply_to=parent.author)


def delete_comment(comment) -> None:
    """删除一条评论;删顶级评论时回复由数据库 CASCADE 一并删除。

    参数说明:
        comment: 待删除的评论(调用方已校验作者身份)。

    返回参数:
        无返回值。

    使用示例:
        ``delete_comment(comment)``

    备注信息:
        只删行,不发通知也不改动态计数 —— ``comment_count`` 是查询时注解算出来的,
        删完自然少一条;作者身份校验在视图里(非作者 404)。
    """
    comment.delete()


def follow(follower, followee) -> bool:
    """关注某人(幂等);重复关注不报错、不产生第二行。

    参数说明:
        follower: 关注者(当前登录用户)。
        followee: 被关注者(调用方已校验存在、未重封禁、未互相拉黑、不是自己)。

    返回参数:
        本次是否**新建**了关注关系(已关注过返回 ``False``)。

    使用示例:
        ``follow(request.user, target_user)``

    备注信息:
        只写 ``Follow`` 一张表:不发通知、不碰 IM、不建立聊天权限。
        幂等靠 ``Follow`` 上的 ``uniq_follow`` 唯一约束 + ``get_or_create``。
    """
    _, created = Follow.objects.get_or_create(follower=follower, followee=followee)
    return created


def unfollow(follower, followee) -> None:
    """取消关注(幂等):没有该关系时静默返回。

    参数说明:
        follower: 关注者(当前登录用户)。
        followee: 被取消关注的人。

    返回参数:
        无返回值。

    使用示例:
        ``unfollow(request.user, target_user)``

    备注信息:
        条件删除,本来就没关注时删除 0 行,同样算成功(接口恒 204);
        与 ``follow`` 一样不发通知、不碰 IM。
    """
    Follow.objects.filter(follower=follower, followee=followee).delete()


def follow_state_for_profiles(profiles, viewer) -> dict[int, dict]:
    """批量取「资料卡关注态」:是否已关注 + 粉丝数 + 关注数。

    单条资料卡时用**一条**聚合 SQL 同时算三个值(资料页接口因此只多 1 条查询);
    批量时退化成三条分组 SQL(分别取粉丝数、关注数、我关注了谁),条数与资料数无关,
    不会出现 N+1(``config/test_query_budget.py`` 会拦)。

    参数说明:
        profiles: 资料对象序列;只用到 ``user_id``,``None`` 项自动忽略。
        viewer: 当前登录用户(未登录传 ``None``)。

    返回参数:
        ``{user_id: {"is_followed": bool, "follower_count": int,
        "following_count": int}}``;没有资料的 id 不出现在字典里。

    使用示例:
        ``follow_state_for_profiles([profile], request.user)``

    备注信息:
        ``viewer`` 为 ``None`` 时 ``is_followed`` 恒为 ``False``(不额外查「我关注了谁」);
        空列表直接返回 ``{}``,不产生任何 SQL;走批量分支还是单条分支只看
        ``len(user_ids)``,与调用方是否分页无关。
    """
    user_ids = [profile.user_id for profile in profiles if profile is not None]
    if not user_ids:
        return {}
    viewer_id = getattr(viewer, "id", None)
    if len(user_ids) == 1:
        user_id = user_ids[0]
        aggregates = {
            "follower_count": Count("id", filter=Q(followee_id=user_id)),
            "following_count": Count("id", filter=Q(follower_id=user_id)),
        }
        if viewer_id is not None:
            aggregates["followed"] = Count(
                "id", filter=Q(follower_id=viewer_id, followee_id=user_id))
        aggregated = Follow.objects.filter(
            Q(followee_id=user_id) | Q(follower_id=user_id)).aggregate(**aggregates)
        return {user_id: {"is_followed": bool(aggregated.get("followed")),
                          "follower_count": aggregated["follower_count"],
                          "following_count": aggregated["following_count"]}}
    follower_counts = dict(
        Follow.objects.filter(followee_id__in=user_ids)
        .values_list("followee_id").annotate(total=Count("id")))
    following_counts = dict(
        Follow.objects.filter(follower_id__in=user_ids)
        .values_list("follower_id").annotate(total=Count("id")))
    followed_ids = set()
    if viewer_id is not None:
        followed_ids = set(Follow.objects
                           .filter(follower_id=viewer_id, followee_id__in=user_ids)
                           .values_list("followee_id", flat=True))
    return {user_id: {"is_followed": user_id in followed_ids,
                      "follower_count": follower_counts.get(user_id, 0),
                      "following_count": following_counts.get(user_id, 0)}
            for user_id in user_ids}
