"""通知相关的持久化模型:设备、通知偏好与站内通知。

设计要点:
    1. ``registration_id`` 全局唯一:同一台设备换账号登录时设备易主,
       旧账号自然失去这台设备(与单设备登录一致);
    2. 偏好是账号级、不预建:``NotificationPreference.for_user`` 读取时
       才落库,默认全开;注销随用户 CASCADE 删除;
    3. ``InAppNotification`` 是站内通知中心的事实表(批次 H):目标用
       ``target_kind`` + ``target_id`` 两个普通字段表达,**不建外键** ——
       帖子被删时通知要留痕,外键级联会把痕迹一起删掉。
"""

from django.conf import settings
from django.db import models


class PushPlatform(models.TextChoices):
    """推送设备平台。"""

    ANDROID = "android", "Android"
    IOS = "ios", "iOS"


class PushDevice(models.Model):
    """一台接收推送的设备(以极光 registration_id 标识)。"""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="push_devices")
    registration_id = models.CharField("极光 registration_id", max_length=128, unique=True)
    platform = models.CharField("平台", max_length=16, choices=PushPlatform.choices)
    app_version = models.CharField("App 版本", max_length=32, blank=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        ordering = ["-updated_at"]
        verbose_name = "推送设备"
        verbose_name_plural = "推送设备"

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``用户 id:平台:registration_id``。
        """
        return f"{self.user_id}:{self.platform}:{self.registration_id}"


class NotificationPreference(models.Model):
    """账号级通知偏好;四类通知默认全开。

    ``messages`` 是新消息推送的开关,也是「免打扰」的落点:C-1 只做「关掉哪一类就不推
    哪一类」,不做时段静默 —— 产品里没有 DND 概念,加时段表只会多一份要维护的状态
    (取舍见 docs/ops/push.md)。

    ``social`` 是站内通知中心(批次 H)新增的一类:动态被赞 / 被评论 / 评论被回复。
    它**不塞进** ``likes``:``likes`` 的语义是「新的喜欢」(滑卡场景),动态互动混进去
    会让用户分不清自己关掉的是哪一件事(取舍见计划 §2.3)。
    """

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                                related_name="notification_preference")
    likes = models.BooleanField("新的喜欢", default=True)
    matches = models.BooleanField("配对成功", default=True)
    messages = models.BooleanField("新消息", default=True)
    system = models.BooleanField("系统通知", default=True)
    social = models.BooleanField("动态互动", default=True)
    updated_at = models.DateTimeField("更新时间", auto_now=True)

    class Meta:
        verbose_name = "通知偏好"
        verbose_name_plural = "通知偏好"

    @classmethod
    def for_user(cls, user):
        """取(必要时创建)用户的通知偏好。

        Args:
            user: 目标用户。

        Returns:
            该用户的 ``NotificationPreference`` 实例。
        """
        preference, _ = cls.objects.get_or_create(user=user)
        return preference

    def allows(self, kind: str) -> bool:
        """判断某一类通知是否开启。

        Args:
            kind: 通知类型,取值 ``like`` / ``match`` / ``message`` / ``system`` / ``social``。

        Returns:
            开启返回 ``True``;未知类型返回 ``False``(宁可不发)。
        """
        return {
            "like": self.likes,
            "match": self.matches,
            "message": self.messages,
            "system": self.system,
            "social": self.social,
        }.get(kind, False)


class NotificationKind(models.TextChoices):
    """站内通知的事件类型(批次 H 的六类)。

    前五类是真实业务事件;``SYSTEM`` 是预留位(账号限制 / 解封等系统消息),
    当前没有调用方,保留是为了「新增一类事件」时不用再改模型与迁移。
    """

    POST_LIKE = "post_like", "动态被赞"
    POST_COMMENT = "post_comment", "动态被评论"
    COMMENT_REPLY = "comment_reply", "评论被回复"
    MATCH = "match", "配对成功"
    REPORT_HANDLED = "report_handled", "举报已处理"
    SYSTEM = "system", "系统通知"


class NotificationTarget(models.TextChoices):
    """通知点击后要跳向哪类目标。"""

    POST = "post", "动态"
    USER = "user", "用户"
    NONE = "none", "无"


class InAppNotification(models.Model):
    """一条站内通知(通知中心的唯一事实表)。

    字段取舍:
        - ``actor`` 用 ``SET_NULL``:对方注销后通知仍在,只是不再展示头像昵称;
        - ``target_kind`` / ``target_id`` 是普通字段,**不建外键**:帖子被删后通知
          要能留痕(外键级联会把通知一起删掉),点击时目标不存在按「只标已读」处理;
        - ``dedupe_key`` 唯一且可空:同一事件重复触发(重复点赞、重复处理举报)
          只留一条;``NULL`` 不参与唯一性(MySQL 允许多个 NULL);
        - ``text`` 由**服务端**生成,双端直接显示(双端各写一套文案必然漂移)。
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="in_app_notifications")
    kind = models.CharField("类型", max_length=20, choices=NotificationKind.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="in_app_actions")
    target_kind = models.CharField("目标类型", max_length=10,
                                   choices=NotificationTarget.choices,
                                   default=NotificationTarget.NONE)
    target_id = models.PositiveIntegerField("目标 id", null=True, blank=True)
    text = models.CharField("正文", max_length=200)
    is_read = models.BooleanField("已读", default=False)
    dedupe_key = models.CharField("去重键", max_length=120, null=True, blank=True,
                                  unique=True)
    created_at = models.DateTimeField("创建时间", auto_now_add=True)

    class Meta:
        # 次级排序键必须是 -id:游标分页(keyset)靠 (created_at, id) 定序,
        # 只按 -created_at 排序时同一秒内的多行顺序不稳定,翻页会重复或漏行。
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["user", "-created_at"], name="notif_user_created_idx"),
            models.Index(fields=["user", "is_read"], name="notif_user_read_idx"),
        ]
        verbose_name = "站内通知"
        verbose_name_plural = "站内通知"

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``用户 id:类型:正文``。
        """
        return f"{self.user_id}:{self.kind}:{self.text}"
