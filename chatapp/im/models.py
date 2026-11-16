"""IM 应用的本地数据模型:聊天图片与语音的元数据。

消息本身存在自建 imserver 的库,Django 这边只落**媒体文件**
的元数据,用于运营抽审、删除审计与注销清理。

设计要点:
    1. 文件名带随机 uuid(由视图生成),不用自增主键 —— 防止顺着 URL 遍历别人的私聊图;
    2. 运营删除只改 ``status`` 并留 ``deleted_by/deleted_at``,不删行 —— 审计可查;
    3. ``width/height`` 存的是**显示尺寸**(已按 EXIF 方向校正),不是文件原始像素;
    4. 语音多一个**转码进度**维度(``transcode_status``,第五轮审计 M-3):抢不到转码槽的
       上传先落临时区并入队,行以 ``pending`` 存在、``file`` 指向临时区路径,worker 转完
       才写正式路径。它与审核用的 ``ChatVoiceStatus`` 是两条互不相干的轴,别混用。
"""

from django.conf import settings
from django.db import models

from . import media_sign


class TranscodeStatus(models.TextChoices):
    """语音转码的三态进度,聊天语音与资料语音共用同一套取值(M-3)。

    设计要点:
        1. **与审核状态分开**:``ChatVoiceStatus``(``visible`` / ``deleted`` /
           ``expired``)是运营视角的审核与保留期,不能拿来表达「转码还没跑完」——
           两条轴的生命周期彼此独立,混用会让「已删除」与「转码中」互相覆盖;
        2. **默认 ``ready``**:列上线时存量行都已转码完成,新列必须带一个让老数据
           语义不变的默认值,所以默认值只能是 ``ready``;
        3. **只在这里定义一次**:``users.models.ProfileVoice`` 也从本模块导入(``im`` 是
           下层);``im/tasks.py`` 反过来导入 ``users.models`` 走的是运行期延迟导入,
           不构成循环导入。
    """

    PENDING = "pending", "转码中"
    READY = "ready", "可播放"
    FAILED = "failed", "转码失败"


class ChatImageStatus(models.TextChoices):
    """聊天图片的状态。"""

    VISIBLE = "visible", "正常"
    DELETED = "deleted", "已删除"
    EXPIRED = "expired", "已过期清理"


class ChatImage(models.Model):
    """一张聊天图片的文件元数据。

    Attributes:
        deleted_by: 执行删除的运营账号;未删除时为 ``None``。
        deleted_at: 删除时间;未删除时为 ``None``。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="chat_images", verbose_name="发送者")
    file = models.ImageField("原图", upload_to="chat/%Y/%m/")
    thumb = models.ImageField("缩略图", upload_to="chat/%Y/%m/")
    width = models.PositiveIntegerField("宽")
    height = models.PositiveIntegerField("高")
    bytes = models.PositiveIntegerField("字节数")
    status = models.CharField("状态", max_length=10, choices=ChatImageStatus.choices,
                              default=ChatImageStatus.VISIBLE)
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    deleted_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField("过期清理时间", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def signed_file_url(self) -> str:
        """运营台预览用:带签名的原图绝对地址。

        参数说明:
            无。

        返回参数:
            ``MEDIA_BASE_URL + 文件路径`` 并附签名 query。

        使用示例:
            ``{{ image.signed_file_url }}``(见 ``ops/templates/ops/partials/chat_images_table.html``)

        备注信息:
            URL 的有效期由 ``IM_MEDIA_SIGN_TTL`` 决定;未配置签名密钥时退化为不带 query 的绝对地址。
        """
        return media_sign.sign_url(f"{settings.MEDIA_BASE_URL.rstrip('/')}{self.file.url}")

    @property
    def signed_thumb_url(self) -> str:
        """运营台预览用:带签名的缩略图绝对地址。

        参数说明:
            无。

        返回参数:
            ``MEDIA_BASE_URL + 缩略图路径`` 并附签名 query。

        使用示例:
            ``{{ image.signed_thumb_url }}``(见 ``ops/templates/ops/partials/chat_images_table.html``)

        备注信息:
            URL 的有效期由 ``IM_MEDIA_SIGN_TTL`` 决定;未配置签名密钥时退化为不带 query 的绝对地址。
        """
        return media_sign.sign_url(f"{settings.MEDIA_BASE_URL.rstrip('/')}{self.thumb.url}")

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``chat_image#主键(owner=发送者 id)``。

        使用示例:
            ``str(image)``(见 ``im/tests.py`` 的 ``ChatImageModelTests``)

        备注信息:
            只拼主键与发送者 id,不触发任何关联查询。
        """
        return f"chat_image#{self.pk}(owner={self.owner_id})"


class ChatVoiceStatus(models.TextChoices):
    """聊天语音的状态。"""

    VISIBLE = "visible", "正常"
    DELETED = "deleted", "已删除"
    EXPIRED = "expired", "已过期清理"


class ChatVoice(models.Model):
    """一段聊天语音的文件元数据(统一转码为 m4a)。

    Attributes:
        deleted_by: 执行删除的运营账号;未删除时为 ``None``。
        deleted_at: 删除时间;未删除时为 ``None``。
        transcode_status: 转码进度(``pending`` / ``ready`` / ``failed``);抢不到转码槽的
            上传先落临时区并入队,回到 ``ready`` 才算可播放。
        transcode_error: 转码失败原因:能定位到业务码时写业务码(如 ``41301``),
            否则写一句短文案;成功时为空串。
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="chat_voices", verbose_name="发送者")
    file = models.FileField("语音", upload_to="chat/voices/%Y/%m/")
    duration_ms = models.PositiveIntegerField("时长(毫秒)")
    bytes = models.PositiveIntegerField("字节数")
    mime = models.CharField("MIME", max_length=32, default="audio/mp4")
    status = models.CharField("状态", max_length=10, choices=ChatVoiceStatus.choices,
                              default=ChatVoiceStatus.VISIBLE)
    transcode_status = models.CharField("转码状态", max_length=10,
                                        choices=TranscodeStatus.choices,
                                        default=TranscodeStatus.READY)
    transcode_error = models.CharField("转码失败原因", max_length=64, blank=True, default="")
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")
    deleted_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField("过期清理时间", null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def signed_file_url(self) -> str:
        """运营台播放用:带签名的语音绝对地址。

        参数说明:
            无。

        返回参数:
            ``MEDIA_BASE_URL + 文件路径`` 并附签名 query。

        使用示例:
            ``{{ voice.signed_file_url }}``(见 ``ops/templates/ops/report_detail.html``)

        备注信息:
            URL 的有效期由 ``IM_MEDIA_SIGN_TTL`` 决定;未配置签名密钥时退化为不带 query 的绝对地址。
            转码还没完成(``pending`` / ``failed``)的语音没有正式文件,此时返回空串而不是
            抛 ``ValueError`` —— 运营台列表按 ``ready`` 过滤,这里只是兜底,别让模板 500。
        """
        if not self.file:
            return ""
        return media_sign.sign_url(f"{settings.MEDIA_BASE_URL.rstrip('/')}{self.file.url}")

    @property
    def duration_seconds(self) -> int:
        """时长(秒,四舍五入),运营台展示用。

        参数说明:
            无。

        返回参数:
            至少为 1 的整秒数。

        使用示例:
            ``{{ voice.duration_seconds }}``(见 ``ops/templates/ops/report_detail.html``)

        备注信息:
            毫秒数四舍五入到秒;不足 1 秒按 1 秒显示,避免运营台出现「0 秒」。
        """
        return max(1, round(self.duration_ms / 1000))

    def __str__(self):
        """后台与日志中的可读表示。

        参数说明:
            无。

        返回参数:
            ``chat_voice#主键(owner=发送者 id)``。

        使用示例:
            ``str(voice)``

        备注信息:
            只拼主键与发送者 id,不触发任何关联查询;本仓库内无直接调用点。
        """
        return f"chat_voice#{self.pk}(owner={self.owner_id})"
