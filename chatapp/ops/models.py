"""ops 应用的数据模型:目前只有私聊媒体的访问审计。

私聊图片/语音没有机器审核(M5/H5 的遗留),上线靠运营人工抽审。
抽审必须可追溯:谁、什么时候、按什么筛选、看了多少条。
"""

from django.conf import settings
from django.db import models


class MediaAccessLog(models.Model):
    """运营浏览私聊媒体(聊天图片/语音)的审计记录。

    每次打开抽审列表写一条;只记「浏览」,删除动作本身已有 ``deleted_by``
    与 ``deleted_at`` 落库,不在这里重复记。
    """

    class Kind(models.TextChoices):
        """媒体类型;与 ``im.ChatImage`` / ``im.ChatVoice`` 对应。"""

        IMAGE = "image", "聊天图片"
        VOICE = "voice", "聊天语音"

    staff = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="操作人",
                              null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="+")
    kind = models.CharField("媒体类型", max_length=8, choices=Kind.choices)
    filter = models.CharField("筛选条件", max_length=16, default="all")
    count = models.PositiveIntegerField("返回条数", default=0)
    ip = models.GenericIPAddressField("来源 IP", null=True, blank=True)
    created_at = models.DateTimeField("时间", auto_now_add=True, db_index=True)

    class Meta:
        """按时间倒序展示,并按「操作人 + 时间」建索引供事后追查。"""

        verbose_name = "媒体访问审计"
        verbose_name_plural = verbose_name
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["staff", "-created_at"])]

    def __str__(self) -> str:
        """后台列表里的可读标识。

        Returns:
            形如 ``image/all/120`` 的摘要。
        """
        return f"{self.kind}/{self.filter}/{self.count}"
