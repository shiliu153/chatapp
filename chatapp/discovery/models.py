"""滑卡与配对的数据模型。

设计要点:
    1. ``Swipe`` 对 ``(swiper, target)`` 有唯一约束 —— 同一个「我 → 他」只能有一条,
       这是接口幂等的基础(重复提交保留第一次的动作);
    2. ``Match`` 一律按 **id 升序**存储(``pair_kwargs``),并配 ``user_a < user_b`` 的
       检查约束,保证 (1,2) 与 (2,1) 是同一行,不会出现重复配对;
    3. 配对不是「谁喜欢了谁」的记录,而是「互喜」的结果,查询时要同时看两个方向;
    4. **解除配对是软删除**:``unmatched_at`` 非空即失效,行保留用于审计与防复活
       (已解除的配对不会被再次滑卡复活)。
"""

from django.conf import settings
from django.db import models
from django.db.models import F, Q


class SwipeAction(models.TextChoices):
    """滑卡动作。"""

    LIKE = "like", "喜欢"
    PASS = "pass", "跳过"


class Swipe(models.Model):
    """一次滑卡记录。"""

    swiper = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="swipes_made")
    target = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="swipes_received")
    action = models.CharField("动作", max_length=10, choices=SwipeAction.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["swiper", "target"], name="uniq_swipe_swiper_target"),
        ]

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``发起者->目标:动作``。
        """
        return f"{self.swiper_id}->{self.target_id}:{self.action}"


class Match(models.Model):
    """一对互相喜欢的用户。

    Attributes:
        user_a: 恒为 id 较小的一方(由检查约束强制)。
        user_b: 恒为 id 较大的一方。
        unmatched_at: 解除配对时间;``None`` 表示配对仍然有效。
        unmatched_by: 发起解除的一方;账号注销后置空。
    """

    user_a = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="matches_as_a")
    user_b = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="matches_as_b")
    created_at = models.DateTimeField(auto_now_add=True)
    unmatched_at = models.DateTimeField("解除配对时间", null=True, blank=True, db_index=True)
    unmatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name="matches_unmatched",
        verbose_name="解除操作人",
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user_a", "user_b"], name="uniq_match_pair"),
            models.CheckConstraint(condition=Q(user_a__lt=F("user_b")), name="match_user_a_before_b"),
        ]

    @classmethod
    def pair_kwargs(cls, user1, user2):
        """配对一律按 id 排序存储,保证 (1,2) 与 (2,1) 是同一行。

        Args:
            user1: 配对中的一方。
            user2: 配对中的另一方。

        Returns:
            ``get_or_create`` 用的关键字参数,``user_a`` 恒为 id 较小的一方。
        """
        a, b = (user1, user2) if user1.id < user2.id else (user2, user1)
        return {"user_a": a, "user_b": b}

    @property
    def is_active(self) -> bool:
        """配对是否仍然有效(未解除)。

        Returns:
            ``True`` 表示正常配对;``False`` 表示已被任一方解除。
        """
        return self.unmatched_at is None

    def other_user(self, user):
        """取配对中的另一方。

        Args:
            user: 配对中的任意一方。

        Returns:
            另一方用户实例。
        """
        return self.user_b if self.user_a_id == user.id else self.user_a

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``match(较小 id,较大 id)``。
        """
        return f"match({self.user_a_id},{self.user_b_id})"
