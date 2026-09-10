from django.conf import settings
from django.db import models
from django.db.models import F, Q


class SwipeAction(models.TextChoices):
    LIKE = "like", "喜欢"
    PASS = "pass", "跳过"


class Swipe(models.Model):
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
        return f"{self.swiper_id}->{self.target_id}:{self.action}"


class Match(models.Model):
    user_a = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="matches_as_a")
    user_b = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="matches_as_b")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["user_a", "user_b"], name="uniq_match_pair"),
            models.CheckConstraint(condition=Q(user_a__lt=F("user_b")), name="match_user_a_before_b"),
        ]

    @classmethod
    def pair_kwargs(cls, user1, user2):
        """配对一律按 id 排序存储,保证 (1,2) 与 (2,1) 是同一行。"""
        a, b = (user1, user2) if user1.id < user2.id else (user2, user1)
        return {"user_a": a, "user_b": b}

    def other_user(self, user):
        return self.user_b if self.user_a_id == user.id else self.user_a

    def __str__(self):
        return f"match({self.user_a_id},{self.user_b_id})"
