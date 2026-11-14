"""ops 应用的数据模型:目前只有私聊媒体的访问审计。

私聊图片/语音没有机器审核(M5/H5 的遗留),上线靠运营人工抽审。
抽审必须可追溯:谁、什么时候、按什么筛选、看了多少条。

文件信息:
    文件名称          ops/models.py
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


class MediaAccessLog(models.Model):
    """运营浏览私聊媒体(聊天图片/语音)的审计记录。

    每次打开抽审列表写一条;只记「浏览」,删除动作本身已有 ``deleted_by``
    与 ``deleted_at`` 落库,不在这里重复记。

    参数说明:
        按字段关键字传参:``staff``(操作人,可空)、``kind``(媒体类型,取值见 ``Kind``)、
        ``filter``(筛选条件,默认 ``all``)、``count``(返回条数,默认 0)、``ip``(来源 IP,可空)。

    返回参数:
        构造出的 ``MediaAccessLog`` 实例。

    使用示例:
        ``MediaAccessLog.objects.create(staff=request.user, kind="image", filter="all", count=12)``

    备注信息:
        记录写完不再更新:``staff`` 用 ``SET_NULL``,账号注销后审计行仍在、操作人置空,
        审计链不会因删号断裂;``created_at`` 是 ``auto_now_add``,无法补写历史时间。
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

        参数说明:
            无。

        返回参数:
            形如 ``image/all/120`` 的摘要,依次是媒体类型、筛选条件、返回条数。

        使用示例:
            ``str(log)``

        备注信息:
            不含操作人与时间:后台列表按 ``-created_at`` 排序,时间已在行上展示。
        """
        return f"{self.kind}/{self.filter}/{self.count}"
