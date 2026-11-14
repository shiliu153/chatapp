"""广场动态的数据模型:动态、配图、点赞、收藏、评论、动态举报与关注关系。

设计要点:
    1. ``PostLike`` 对 ``(post, user)`` 有唯一约束,点赞天然幂等;
       ``PostFavorite`` 同样在库层唯一,收藏才能做成恒 204 的幂等写 ——
       收藏是**私密书签**:不通知作者、不产生 IM 灰条(批次 U);
    2. ``PostReport.post`` 用 ``SET_NULL``:动态被删后举报行仍留档,便于运营对账
       (因此读举报时 ``post`` 可能为 ``None``);
    3. 动态列表依赖 ``Post.Meta.ordering``,但一旦 ``annotate`` 触发 GROUP BY,
       Django 会丢弃 Meta 排序,必须显式 ``order_by`` —— 见 ``services.visible_posts``;
    4. ``Follow`` 是**有向**关系(我关注谁),与配对 ``Match`` 的**对称**语义无关:
       关注不产生聊天权限,也不进通知(新粉丝不通知,见计划 §2.3)。

文件信息:
    文件名称          feed/models.py
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

from moderation.models import ReportStatus, ReportType


class Post(models.Model):
    """一条广场动态。

    参数说明:
        无(字段初始值按字段名传给构造器,如 ``Post(author=user, text="...")``)。

    返回参数:
        实例化得到 ``Post`` 实例;``id`` 与 ``created_at`` 在 ``save()`` 之后才有值。

    使用示例:
        ``Post.objects.create(author=request.user, text="今天出太阳")``

    备注信息:
        ``Meta.ordering`` 只在没有 ``annotate`` 时生效:一旦注解触发 GROUP BY,
        Django 会丢弃 Meta 排序,取列表时必须显式 ``order_by("-created_at", "-id")``
        (见 ``services.visible_posts``);``post_feed_order_idx`` 就是为这条排序建的。
        字段含义见下方每条字段的行内注释。
    """

    # 作者;账号注销时动态随 CASCADE 一起删除
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="posts")
    # 正文,可空:纯图动态也允许;500 字上限由序列化器与字段共同把住
    text = models.TextField("正文", max_length=500, blank=True)
    # 发布时间,广场排序与游标都取它
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        # 广场按时间倒序翻页;没有这个索引时 MySQL 要全表扫 + filesort
        # (2026-11-03 实测:10 万条动态单次 3.3 秒,见 docs/reports/scale-report.md)。
        indexes = [models.Index(fields=["-created_at", "-id"], name="post_feed_order_idx")]

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``post#主键(作者 id)``。

        使用示例:
            ``str(post)``

        备注信息:
            只读已加载的 ``pk`` 与 ``author_id`` 两列,不会触发额外查询。
        """
        return f"post#{self.pk}({self.author_id})"


class PostImage(models.Model):
    """动态的配图(单条最多 9 张,由序列化器校验)。

    参数说明:
        无(字段初始值按字段名传给构造器)。

    返回参数:
        实例化得到 ``PostImage`` 实例;``file`` 的内容由调用方提供。

    使用示例:
        ``PostImage.objects.create(post=post, file=ContentFile(data, name="a.png"), order=0)``

    备注信息:
        「单条最多 9 张」「单张不超过 5MB」「必须是有效图片」三条由
        ``serializers.PostCreateSerializer`` 在入参阶段校验;落盘前图片统一过
        ``config.images.normalize``(仅 jpg/png/webp、长边 4096、剥离 EXIF 与 GPS)。
    """

    # 所属动态;动态删除时配图行随 CASCADE 一起删除
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="images")
    # 重编码后的图片文件,按月分目录存放
    file = models.ImageField("图片", upload_to="posts/%Y/%m/")
    # 重编码后的文件字节数:存储配额按它求和(M7)
    bytes = models.PositiveIntegerField("字节数", default=0)
    # 展示顺序,0 在最前;列表按 order 升序返回
    order = models.PositiveSmallIntegerField("排序", default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``post_image#主键(post=动态 id)``。

        使用示例:
            ``str(image)``

        备注信息:
            只读 ``pk`` 与 ``post_id``,不访问 ``file``,后台列表里不会拉文件元信息。
        """
        return f"post_image#{self.pk}(post={self.post_id})"


class PostLike(models.Model):
    """一条点赞记录。

    参数说明:
        无(字段初始值按字段名传给构造器)。

    返回参数:
        实例化得到 ``PostLike`` 实例。

    使用示例:
        ``PostLike.objects.get_or_create(post=post, user=request.user)``

    备注信息:
        ``uniq_post_like`` 让重复点赞在库层只落一行,接口因此能做成「首次 201、
        重复 200」的幂等写(``views.post_like``);站内通知只在首次点赞时发,
        再次点赞被 ``dedupe_key`` 吸收。
    """

    # 被赞的动态
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")
    # 点赞者
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="post_likes")
    # 点赞时间,点赞列表按它倒序
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["post", "user"], name="uniq_post_like"),
        ]

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``post_like(动态 id:用户 id)``。

        使用示例:
            ``str(like)``

        备注信息:
            形如 ``post_like(12:34)``,两段 id 都取自本行的外键列,不查关联表。
        """
        return f"post_like({self.post_id}:{self.user_id})"


class PostFavorite(models.Model):
    """一条收藏记录(私密书签:不通知作者、不产生 IM 灰条)。

    唯一约束 ``(post, user)`` 让「重复收藏」在库层只落一行,接口因此可以做成恒 204
    的幂等写;``(user, -created_at)`` 索引服务「我的收藏」—— 那个列表的排序键是
    **收藏时间**而不是发帖时间,没有这条索引就要对全表分组后 filesort。

    Attributes:
        post: 被收藏的动态;动态删除时收藏行随 ``CASCADE`` 一起消失。
        user: 收藏者。
        created_at: 收藏时间(也是「我的收藏」的排序与游标字段)。

    参数说明:
        无(字段初始值按字段名传给构造器)。

    返回参数:
        实例化得到 ``PostFavorite`` 实例。

    使用示例:
        ``PostFavorite.objects.get_or_create(post=post, user=request.user)``

    备注信息:
        收藏允许自己的动态(书签语义);接口侧只动本表,不调 ``notify_on_commit``、
        不碰 ``im/tasks.py``,因此收藏与取消收藏都不产生通知与 IM 灰条(批次 U)。
    """

    # 被收藏的动态;动态删除时收藏行随 CASCADE 一起消失
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="favorites")
    # 收藏者
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="post_favorites")
    # 收藏时间,「我的收藏」的排序与游标字段
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["post", "user"], name="uniq_post_favorite"),
        ]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="fav_user_time_idx"),
        ]

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``post_favorite(动态 id:用户 id)``。

        使用示例:
            ``str(favorite)``

        备注信息:
            形如 ``post_favorite(12:34)``;动态被删后该行随 ``CASCADE`` 消失,
            因此 ``post_id`` 不会悬空。
        """
        return f"post_favorite({self.post_id}:{self.user_id})"


class PostComment(models.Model):
    """一条动态评论;``parent`` 非空表示它是某条顶级评论下的回复。

    层级恒为两级:回复的回复由 ``services.create_comment`` 归一到顶级评论,
    ``parent`` 永远指向顶级评论;``reply_to`` 记录"回复的是谁",用于渲染
    「回复 @昵称」与发送提醒。

    参数说明:
        无(字段初始值按字段名传给构造器)。

    返回参数:
        实例化得到 ``PostComment`` 实例;建评论请走 ``services.create_comment``,
        由它负责层级归一。

    使用示例:
        ``PostComment.objects.create(post=post, author=user, text="好看")``

    备注信息:
        直接 ``objects.create`` 能造出三层以上的层级,而列表接口只按两级渲染,
        深层回复会显示错位;因此写评论一律走 ``services.create_comment``。
    """

    # 被评论的动态
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comments")
    # 评论者
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                               related_name="post_comments")
    # 顶级评论;为空表示本条本身就是顶级评论(层级恒为两级)
    parent = models.ForeignKey("self", null=True, blank=True,
                               on_delete=models.CASCADE, related_name="replies")
    # 被回复者,用于渲染「回复 @昵称」;对方注销后置空
    reply_to = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                 on_delete=models.SET_NULL,
                                 related_name="comment_replies_received")
    # 正文,200 字上限;违禁词在序列化器校验
    text = models.CharField("内容", max_length=200)
    # 评论时间,列表按它正序
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``post_comment#主键(post=动态 id)``。

        使用示例:
            ``str(comment)``

        备注信息:
            被删顶级评论的回复由 ``parent`` 上的 ``CASCADE`` 一并删除,
            因此日志里不会出现「孤儿回复」。
        """
        return f"post_comment#{self.pk}(post={self.post_id})"


class PostReport(models.Model):
    """动态举报;post 用 SET_NULL:动态删除后举报行留档(运营对账)。

    Attributes:
        dedupe_key: 待处理举报的去重键(``举报人:动态:pending``),唯一约束
            保证并发提交也只落一条;处理完成后置空,允许再次举报(L-2)。

    参数说明:
        无(字段初始值按字段名传给构造器)。

    返回参数:
        实例化得到 ``PostReport`` 实例;``dedupe_key`` 由 ``save()`` 自动维护。

    使用示例:
        ``PostReport.objects.create(reporter=user, post=post, type="spam")``

    备注信息:
        读举报时 ``post`` 可能为 ``None``(动态已被删),调用方必须判空;
        未处理状态的所有举报在动态删除时由 ``services.delete_post`` 统一关闭。
    """

    # 举报人
    reporter = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="post_reports")
    # 被举报动态;动态删除后置空,举报行留档
    post = models.ForeignKey(Post, null=True, on_delete=models.SET_NULL,
                             related_name="reports")
    # 举报类型,取值来自 moderation.models.ReportType
    type = models.CharField("类型", max_length=20, choices=ReportType.choices)
    # 举报人补充描述,可空
    detail = models.CharField("补充说明", max_length=200, blank=True)
    # 处理状态,默认待处理
    status = models.CharField("状态", max_length=10, choices=ReportStatus.choices,
                              default=ReportStatus.PENDING)
    # 运营处理结论;动态被删时写成「动态已删除」
    handled_note = models.CharField("处理备注", max_length=200, blank=True)
    # 处理人;运营账号注销后置空
    handled_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="post_reports_handled")
    # 举报时间
    created_at = models.DateTimeField(auto_now_add=True)
    # 处理时间;未处理为空
    handled_at = models.DateTimeField(null=True, blank=True)
    # 待处理举报的去重键,非待处理状态置空;唯一约束保证并发只落一条
    dedupe_key = models.CharField("去重键", max_length=80, null=True, blank=True,
                                  unique=True, editable=False)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        """保存前维护去重键。

        参数说明:
            *args: 透传给 ``Model.save``。
            **kwargs: 透传给 ``Model.save``;``update_fields`` 会补上 ``dedupe_key``,
                否则只改 ``status`` 时去重键清不掉。

        返回参数:
            无返回值(写入由父类 ``save`` 完成)。

        使用示例:
            ``report.save(update_fields=["status", "handled_note", "handled_at"])``

        备注信息:
            待处理举报写入 ``举报人:动态:pending``;离开待处理状态就清空,
            这样处理完可以再次举报同一动态,并发提交仍被唯一约束挡住。
            显式传 ``update_fields`` 时本方法会把它扩成集合再补 ``dedupe_key``。
        """
        if self.status == ReportStatus.PENDING:
            if not self.dedupe_key:
                self.dedupe_key = f"{self.reporter_id}:{self.post_id}:pending"
        else:
            self.dedupe_key = None
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = set(update_fields) | {"dedupe_key"}
        super().save(*args, **kwargs)

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``post_report#主键(举报人->动态:类型)``。

        使用示例:
            ``str(report)``

        备注信息:
            动态被删后 ``post`` 是 ``None``,输出形如 ``post_report#7(3->None:spam)``。
        """
        return f"post_report#{self.pk}({self.reporter_id}->{self.post_id}:{self.type})"


class Follow(models.Model):
    """一条关注关系:``follower`` 关注了 ``followee``(有向,非对称)。

    唯一约束 ``(follower, followee)`` 让「重复关注」在数据库层只落一行,
    接口因此可以做成幂等 204;``(followee, -created_at)`` 索引服务
    「谁关注了我」的计数与关注流里按作者取动态两处查询。

    参数说明:
        无(字段初始值按字段名传给构造器)。

    返回参数:
        实例化得到 ``Follow`` 实例;是否新建由 ``services.follow`` 的返回值给出。

    使用示例:
        ``Follow.objects.get_or_create(follower=me, followee=target)``

    备注信息:
        关注不产生聊天权限、不发通知、不碰 IM(新粉丝不通知,见计划 §2.3);
        关注流只按 ``followee`` 方向取数,``following_base`` 里还会排除自己。
    """

    # 关注者(动作发起方)
    follower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="following")
    # 被关注者(动作接收方)
    followee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                 related_name="followers")
    # 关注时间
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["follower", "followee"], name="uniq_follow"),
        ]
        indexes = [
            models.Index(fields=["followee", "-created_at"], name="follow_followee_idx"),
        ]

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``follow(关注者 id->被关注者 id)``。

        使用示例:
            ``str(follow)``

        备注信息:
            箭头方向即数据流向:左边关注者,右边被关注者;关系是有向的,
            反向成行只代表对方也关注了我。
        """
        return f"follow({self.follower_id}->{self.followee_id})"
