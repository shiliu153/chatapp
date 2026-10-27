# 语音消息 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> 本项目约定:**一律内联执行**(用户 2026-10-04 明确要求),不要为执行计划派发子 agent。

**Goal:** 自建 IM 后端下支持单聊语音消息:按住说话录制、Django 统一转码为 m4a、imserver `kind=4` 收发与历史、双端播放、运营抽审与 30 天清理。

**Architecture:** 与图片链路同构——Django 收上传并转码落盘、签发限时 URL;imserver 只扩协议(kind=4 + 前缀校验 + 读时签名);App 用 `record`/`audioplayers`,Web 用 `MediaRecorder`/`Audio`。能力位 `voice` 只在自建后端为 true。

**Tech Stack:** Django 5.2 + DRF + Pillow(现有)+ ffmpeg/ffprobe(服务器依赖);C++20 + Boost.Beast + MySQL(imserver);Flutter 3.47 + Riverpod + record + audioplayers;Vue 3 + Pinia + MediaRecorder。

## Global Constraints

- 规格:`docs/superpowers/specs/2026-10-27-im-voice-messages-design.md`(已确认)。
- 时长 **1–60 秒**;输入 ≤ **5MB**;转码产物 ≤ **2MB**;上传限流 **60 次/小时**;客户端声明时长与实测差 ≤ **2 秒**。
- 存储统一 **m4a/AAC**,单声道 **16kHz / 32kbps**,落 `media/chat/voices/%Y/%m/`;保存时只传文件名。
- imserver 只接受 `IM_MEDIA_PREFIX` 前缀下的 URL;`duration_ms` 1000–60000;`size` 1–2MB;违规一律 `42201`。
- ffmpeg/ffprobe 缺失时上传返回 **503 + code 50302**(`50301` 已被短信占用)。
- 能力位 `voice`:自建 true、腾讯 false;腾讯 `sendVoice` 抛 `42202`。
- 每步全绿再进下一步:后端 `python manage.py test`(前置 Redis);imserver `test.sh` / `test_http.sh`;App `flutter analyze` 零告警 + 全量测试;Web `type-check` + `lint --max-warnings 0` + `vitest`。
- 提交信息用中文 `feat(im)/test(im)/docs(im)` 前缀,沿用仓库风格。
- 注释纪律:新增/修改 `.py` 必须补模块与函数 docstring(公开函数带参数写 `Args:`),`CommentCoverageTests` 会比对。

---

### Task 1: Django 语音模型、转码与上传接口

**Files:**
- Modify: `chatapp/im/models.py`(末尾追加 `ChatVoiceStatus` / `ChatVoice`)
- Create: `chatapp/im/voice.py`(ffmpeg 探测、时长校验、转码)
- Modify: `chatapp/im/serializers.py`、`chatapp/im/throttles.py`、`chatapp/im/views.py`、`chatapp/im/urls.py`
- Modify: `chatapp/config/settings.py`(限流额度与 `CHAT_VOICE_*`)、`chatapp/config/error_codes.py`
- Create: `chatapp/im/migrations/0002_chatvoice.py`(用 `makemigrations` 生成)
- Test: `chatapp/im/tests.py`(追加 `ChatVoiceUploadTests`)

**Interfaces:**
- Produces: `POST /api/v1/im/voices` → `{id, url, duration_ms, size}`;`ChatVoice.signed_file_url`;`im.voice.normalize(raw: bytes, content_type: str, declared_ms: int) -> tuple[bytes, int]`;`im.voice.VoiceError` / `im.voice.VoiceUnavailable`。

- [ ] **Step 1: 写失败测试(模型 + 上传)**

在 `chatapp/im/tests.py` 末尾追加(顶部 import 补 `from .models import ChatVoice, ChatVoiceStatus`):

```python
class ChatVoiceUploadTests(APITestCase):
    """语音上传:成功返回四元组、时长/大小/格式校验、ffmpeg 缺失 503、限流。"""

    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir, MEDIA_BASE_URL="http://cdn.test",
                                 IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=86400)
        override.enable()
        self.addCleanup(override.disable)
        cache.clear()
        self.user = User.objects.create_user(phone="13900139009")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")
        self.url = "/api/v1/im/voices"

    def upload(self, content=b"fake-m4a", content_type="audio/mp4", duration_ms=12500):
        """上传一段语音。

        Args:
            content: 文件字节。
            content_type: MIME 类型。
            duration_ms: 客户端声明时长。

        Returns:
            DRF 测试客户端响应。
        """
        return self.client.post(
            self.url,
            {"file": SimpleUploadedFile("a.m4a", content, content_type=content_type),
             "duration_ms": duration_ms},
            format="multipart")

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"transcoded"))
    @patch("im.voice._probe_ms", return_value=12500)
    def test_upload_returns_signed_url(self, _probe, _transcode, _ffmpeg):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.data)
        data = response.data
        self.assertTrue(data["url"].startswith("http://cdn.test/media/chat/voices/"))
        self.assertIn("?e=", data["url"])
        self.assertEqual(data["duration_ms"], 12500)
        self.assertEqual(data["size"], len(b"transcoded"))
        voice = ChatVoice.objects.get()
        self.assertEqual(voice.owner_id, self.user.id)
        self.assertRegex(voice.file.name, r"^chat/voices/\d{4}/\d{2}/\d+-[0-9a-f]{32}\.m4a$")
        self.assertTrue(voice.file.storage.exists(voice.file.name))

    @patch("im.voice.ffmpeg_available", return_value=False)
    def test_returns_503_without_ffmpeg(self, _ffmpeg):
        response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], 50302)

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._probe_ms", return_value=61000)
    def test_rejects_too_long(self, _probe, _ffmpeg):
        response = self.upload(duration_ms=61000)
        self.assertEqual(response.status_code, 400)

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._probe_ms", return_value=5000)
    def test_rejects_declared_duration_mismatch(self, _probe, _ffmpeg):
        response = self.upload(duration_ms=20000)
        self.assertEqual(response.status_code, 400)

    def test_rejects_non_audio_content_type(self):
        response = self.upload(content_type="image/png")
        self.assertEqual(response.status_code, 400)

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"x"))
    @patch("im.voice._probe_ms", return_value=5000)
    def test_signed_url_passes_auth_helper(self, _probe, _transcode, _ffmpeg):
        data = self.upload(duration_ms=5000).data
        parts = urlsplit(data["url"])
        query = parse_qs(parts.query)
        self.assertTrue(media_sign.verify(parts.path, query["e"][0], query["s"][0]))

    @patch("im.throttles.ChatVoiceThrottle.get_rate", return_value="1/hour")
    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"x"))
    @patch("im.voice._probe_ms", return_value=5000)
    def test_second_upload_is_throttled(self, _rate, _probe, _transcode, _ffmpeg):
        cache.clear()
        self.assertEqual(self.upload(duration_ms=5000).status_code, 201)
        self.assertEqual(self.upload(duration_ms=5000).status_code, 429)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test im.tests.ChatVoiceUploadTests -v 2`
Expected: FAIL(`ImportError: cannot import name 'ChatVoice'` / 404)。

- [ ] **Step 3: 加模型**

`chatapp/im/models.py` 末尾追加(模块 docstring 顺手把「聊天图片」改为「聊天媒体」):

```python
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
    """

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                              related_name="chat_voices", verbose_name="发送者")
    file = models.FileField("语音", upload_to="chat/voices/%Y/%m/")
    duration_ms = models.PositiveIntegerField("时长(毫秒)")
    bytes = models.PositiveIntegerField("字节数")
    mime = models.CharField("MIME", max_length=32, default="audio/mp4")
    status = models.CharField("状态", max_length=10, choices=ChatVoiceStatus.choices,
                              default=ChatVoiceStatus.VISIBLE)
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

        Returns:
            ``MEDIA_BASE_URL + 文件路径`` 并附签名 query。
        """
        return media_sign.sign_url(f"{settings.MEDIA_BASE_URL.rstrip('/')}{self.file.url}")

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``chat_voice#主键(owner=发送者 id)``。
        """
        return f"chat_voice#{self.pk}(owner={self.owner_id})"
```

Run: `cd chatapp && python manage.py makemigrations im --name chatvoice`
Expected: 生成 `chatapp/im/migrations/0002_chatvoice.py`。

- [ ] **Step 4: 写转码模块**

`chatapp/im/voice.py`:

```python
"""聊天语音的校验与统一转码。

App 录 m4a(AAC),Web 的 ``MediaRecorder`` 输出因浏览器而异(webm/ogg/mp4)。
为了让 iOS 也能播放 Web 发来的语音,这里统一转成 **m4a/AAC 单声道 16kHz 32kbps**,
并用 ``ffprobe`` 校验真实时长(不信任客户端声明)。
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

ALLOWED_CONTENT_TYPES = {
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
}

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


class VoiceError(Exception):
    """语音不合法或无法处理;消息直接回给客户端。"""


class VoiceUnavailable(Exception):
    """服务器缺少 ffmpeg/ffprobe;调用方回 503。"""


def ffmpeg_available() -> bool:
    """检查转码依赖是否齐全。

    Returns:
        两者都在 PATH 中时为 ``True``。
    """
    return shutil.which(FFMPEG) is not None and shutil.which(FFPROBE) is not None


def _probe_ms(path: Path) -> int:
    """用 ffprobe 读真实时长。

    Args:
        path: 本地音频文件。

    Returns:
        时长(毫秒)。

    Raises:
        VoiceError: ffprobe 读不出时长(不是音频 / 文件损坏)。
    """
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, timeout=15, check=False)
    try:
        return max(0, int(round(float(result.stdout.strip()) * 1000)))
    except (TypeError, ValueError):
        raise VoiceError("音频无法解码,请重新录制") from None


def _transcode(src: Path, dst: Path) -> None:
    """把任意输入转成 m4a/AAC 单声道。

    Args:
        src: 输入文件。
        dst: 输出文件(扩展名 ``.m4a``)。

    Raises:
        VoiceError: ffmpeg 非零退出或超时。
    """
    try:
        subprocess.run(
            [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
             "-vn", "-ac", "1", "-ar", str(settings.CHAT_VOICE_SAMPLE_RATE),
             "-c:a", "aac", "-b:a", settings.CHAT_VOICE_BITRATE, "-f", "mp4", str(dst)],
            capture_output=True, timeout=15, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise VoiceError("音频无法解码,请重新录制") from None


def normalize(raw: bytes, content_type: str, declared_ms: int) -> tuple[bytes, int]:
    """校验并转码一段上传的语音。

    Args:
        raw: 原始文件字节。
        content_type: 上传声明的 MIME。
        declared_ms: 客户端声明的时长(毫秒)。

    Returns:
        ``(m4a 字节, 实测毫秒)``。

    Raises:
        VoiceUnavailable: 服务器缺 ffmpeg/ffprobe。
        VoiceError: 格式、时长、大小或解码不合法。
    """
    suffix = ALLOWED_CONTENT_TYPES.get(content_type)
    if suffix is None:
        raise VoiceError("只支持 M4A/AAC/WebM/OGG 音频")
    if not ffmpeg_available():
        raise VoiceUnavailable()
    with tempfile.TemporaryDirectory() as workdir:
        src = Path(workdir) / f"in{suffix}"
        src.write_bytes(raw)
        duration = _probe_ms(src)
        if not (settings.CHAT_VOICE_MIN_MS <= duration <= settings.CHAT_VOICE_MAX_MS):
            raise VoiceError("语音时长需在 1–60 秒之间")
        if abs(duration - declared_ms) > settings.CHAT_VOICE_DURATION_TOLERANCE_MS:
            raise VoiceError("语音时长不合法")
        dst = Path(workdir) / "out.m4a"
        _transcode(src, dst)
        data = dst.read_bytes()
    if not data:
        raise VoiceError("音频无法解码,请重新录制")
    if len(data) > settings.CHAT_VOICE_MAX_OUT_BYTES:
        raise VoiceError("语音文件过大")
    return data, duration
```

- [ ] **Step 5: 加配置、错误码、序列化器、限流、视图、路由**

`chatapp/config/settings.py`(限流额度块内,`CHAT_IMAGE_RATE` 下一行):

```python
CHAT_VOICE_RATE = os.getenv("CHAT_VOICE_RATE", "60/hour")   # 聊天语音上传,按用户计数
```

`DEFAULT_THROTTLE_RATES` 里加 `"chat_voice": CHAT_VOICE_RATE,`;文件末尾媒体配置区(`CHAT_IMAGE_*` 之后)加:

```python
# --- 聊天语音(ffmpeg 统一转 m4a/AAC)---
CHAT_VOICE_MAX_BYTES = 5 * 1024 * 1024
CHAT_VOICE_MAX_OUT_BYTES = 2 * 1024 * 1024
CHAT_VOICE_MIN_MS = 1000
CHAT_VOICE_MAX_MS = 60000
CHAT_VOICE_DURATION_TOLERANCE_MS = 2000
CHAT_VOICE_SAMPLE_RATE = 16000
CHAT_VOICE_BITRATE = "32k"
CHAT_VOICE_RETENTION_DAYS = int(os.getenv("CHAT_VOICE_RETENTION_DAYS", "30"))
```

`chatapp/config/error_codes.py` 追加:

```python
CHAT_VOICE_UNAVAILABLE = 50302     # 服务器缺 ffmpeg/ffprobe,语音上传暂不可用
```

`chatapp/im/serializers.py` 追加:

```python
ALLOWED_AUDIO_CONTENT_TYPES = {
    "audio/mp4", "audio/m4a", "audio/x-m4a", "audio/aac", "audio/webm", "audio/ogg",
}


class ChatVoiceUploadSerializer(serializers.Serializer):
    """聊天语音上传入参(multipart 字段 ``file`` + ``duration_ms``)。"""

    file = serializers.FileField()
    duration_ms = serializers.IntegerField(min_value=1000, max_value=60000)

    def validate_file(self, value):
        """校验大小与 MIME。

        Args:
            value: 上传的文件对象。

        Returns:
            通过校验的文件对象。

        Raises:
            serializers.ValidationError: 超过大小上限或类型不在白名单。
        """
        if value.size > settings.CHAT_VOICE_MAX_BYTES:
            raise serializers.ValidationError("语音不能超过 5MB")
        if value.content_type not in ALLOWED_AUDIO_CONTENT_TYPES:
            raise serializers.ValidationError("只支持 M4A/AAC/WebM/OGG 音频")
        return value
```

`chatapp/im/throttles.py` 追加:

```python
class ChatVoiceThrottle(SimpleRateThrottle):
    """按用户限流聊天语音上传;额度在 settings.DEFAULT_THROTTLE_RATES["chat_voice"]。"""

    scope = "chat_voice"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该用户在 ``chat_voice`` 作用域下的缓存键。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
```

`chatapp/im/views.py`(import 补 `logging`、`from config import error_codes`、`ContentFile` 已有、`ChatVoice`、`ChatVoiceUploadSerializer`、`ChatVoiceThrottle`、`from . import voice`,并在 import 段后加 `logger = logging.getLogger(__name__)`),追加:

```python
@api_view(["POST"])
@throttle_classes([ChatVoiceThrottle])
def upload_voice(request):
    """上传一段聊天语音(POST /api/v1/im/voices)。

    同步执行:写临时文件 → ffprobe 校验时长 → ffmpeg 转 m4a → 落盘。全程本地进程,
    没有第三方网络调用,符合「响应路径禁止外部调用」纪律。

    Args:
        request: DRF 请求对象,multipart 字段为 ``file`` 与 ``duration_ms``。

    Returns:
        201 + ``{id, url, duration_ms, size}``;URL 为限时签名地址。
        400 参数不合法;503 服务器缺 ffmpeg(``code=50302``)。
    """
    serializer = ChatVoiceUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    upload = serializer.validated_data["file"]
    try:
        data, duration_ms = voice.normalize(
            upload.read(), upload.content_type, serializer.validated_data["duration_ms"])
    except voice.VoiceUnavailable:
        logger.error("聊天语音上传失败:服务器缺少 ffmpeg/ffprobe")
        return Response({"code": error_codes.CHAT_VOICE_UNAVAILABLE,
                         "message": "语音消息暂不可用"}, status=503)
    except voice.VoiceError as error:
        return Response({"code": 400, "message": str(error)}, status=400)

    stem = f"{request.user.id}-{uuid.uuid4().hex}"
    chat_voice = ChatVoice(owner=request.user, duration_ms=duration_ms, bytes=len(data))
    chat_voice.file.save(f"{stem}.m4a", ContentFile(data), save=False)
    chat_voice.save()

    base = settings.MEDIA_BASE_URL.rstrip("/")
    return Response({
        "id": chat_voice.id,
        "url": media_sign.sign_url(f"{base}{chat_voice.file.url}"),
        "duration_ms": chat_voice.duration_ms,
        "size": chat_voice.bytes,
    }, status=201)
```

`chatapp/im/urls.py` 加 `path("voices", views.upload_voice),`。

- [ ] **Step 6: 跑测试确认通过**

Run: `cd chatapp && python manage.py test im -v 2`
Expected: 全绿(含既有 60+ 用例)。

- [ ] **Step 7: 提交**

```bash
git add chatapp/im chatapp/config
git commit -m "feat(im): 聊天语音上传与统一转码"
```

---

### Task 2: 注销清理、30 天过期与 ops 抽审

**Files:**
- Modify: `chatapp/users/services.py`(注销收集文件)
- Modify: `chatapp/im/management/commands/im_media_cleanup.py`(语音过期 + 孤儿集合)
- Modify: `chatapp/ops/views.py`、`chatapp/ops/urls.py`、`chatapp/ops/templates/ops/base.html`、`chatapp/ops/templates/ops/report_detail.html`
- Create: `chatapp/ops/templates/ops/chat_voices.html`、`chatapp/ops/templates/ops/partials/chat_voices_table.html`
- Test: `chatapp/im/tests.py`(清理)、`chatapp/ops/tests.py`(抽审)

**Interfaces:**
- Consumes: Task 1 的 `ChatVoice` / `ChatVoiceStatus` / `signed_file_url`。
- Produces: `GET /ops/chat-voices/`、`POST /ops/chat-voices/<id>/delete`;`im_media_cleanup` 覆盖语音。

- [ ] **Step 1: 写失败测试**

`chatapp/im/tests.py` 追加:

```python
class ChatVoiceCleanupTests(TestCase):
    """语音清理:30 天过期删文件,孤儿扫描不误删正常语音。"""

    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(phone="13900139010")

    def make_voice(self, name="v.m4a", created_days_ago=0):
        """造一条语音行(带真实文件)。

        Args:
            name: 文件名。
            created_days_ago: 创建时间距今天数。

        Returns:
            保存后的 ``ChatVoice``。
        """
        voice = ChatVoice(owner=self.user, duration_ms=5000, bytes=3)
        voice.file.save(name, ContentFile(b"abc"), save=False)
        voice.save()
        if created_days_ago:
            ChatVoice.objects.filter(pk=voice.pk).update(
                created_at=timezone.now() - timedelta(days=created_days_ago))
        return voice

    def test_expires_old_voice_and_keeps_fresh(self):
        old = self.make_voice("old.m4a", created_days_ago=31)
        fresh = self.make_voice("fresh.m4a")
        call_command("im_media_cleanup", "--apply")
        old.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(old.status, ChatVoiceStatus.EXPIRED)
        self.assertFalse(old.file.storage.exists(old.file.name))
        self.assertEqual(fresh.status, ChatVoiceStatus.VISIBLE)
        self.assertTrue(fresh.file.storage.exists(fresh.file.name))

    def test_orphan_scan_keeps_known_voice(self):
        voice = self.make_voice()
        path = Path(settings.MEDIA_ROOT) / voice.file.name
        os.utime(path, (time.time() - 48 * 3600, time.time() - 48 * 3600))
        call_command("im_media_cleanup", "--apply", "--orphan-hours", "24")
        self.assertTrue(voice.file.storage.exists(voice.file.name))
```

`chatapp/ops/tests.py` 追加(若文件不存在则新建,`from im.models import ChatVoice`):

```python
class ChatVoiceOpsTests(TestCase):
    """运营台语音抽审:列表可见、删除置 deleted 并删文件。"""

    def setUp(self):
        self.staff = User.objects.create_user(phone="13900139011", is_staff=True)
        self.owner = User.objects.create_user(phone="13900139012")
        self.voice = ChatVoice(owner=self.owner, duration_ms=5000, bytes=3)
        self.voice.file.save("v.m4a", ContentFile(b"abc"), save=False)
        self.voice.save()
        self.client.force_login(self.staff)

    def test_list_shows_voice(self):
        response = self.client.get("/ops/chat-voices/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "v.m4a")

    def test_delete_marks_deleted_and_removes_file(self):
        response = self.client.post(f"/ops/chat-voices/{self.voice.pk}/delete")
        self.assertEqual(response.status_code, 200)
        self.voice.refresh_from_db()
        self.assertEqual(self.voice.status, ChatVoiceStatus.DELETED)
        self.assertFalse(self.voice.file.storage.exists(self.voice.file.name))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test im.tests.ChatVoiceCleanupTests ops.tests.ChatVoiceOpsTests -v 2`
Expected: FAIL(清理命令不认语音 / `/ops/chat-voices/` 404)。

- [ ] **Step 3: 实现注销收集与清理**

`chatapp/users/services.py` 第 100 行附近 import 改为同时引入 `ChatVoice`,并在 `file_names` 处追加:

```python
from im.models import ChatImage, ChatVoice
...
file_names += list(ChatVoice.objects.filter(owner=user).values_list("file", flat=True))
```

`chatapp/im/management/commands/im_media_cleanup.py`:

- import 加 `ChatVoice`、`ChatVoiceStatus`;
- 新增 `_expire_voices(retention_days, batch_size, apply)`(照现有 `_expire_old` 写:筛 `status=VISIBLE` 且 `created_at < now - days`,删文件、置 `EXPIRED` + `expired_at`);
- `handle` 里调用它;
- `_delete_orphans` 的 `known` 集合追加:

```python
known |= set(ChatVoice.objects.values_list("file", flat=True))
```

- 新增 `--voice-retention-days` 参数,默认 `settings.CHAT_VOICE_RETENTION_DAYS`(与现有 `--retention-days` 并列,不改后者语义)。

- [ ] **Step 4: 实现 ops 抽审**

`chatapp/ops/views.py`(import 补 `ChatVoice`、`ChatVoiceStatus`):

```python
@staff_required
def chat_voices(request):
    """聊天语音抽审列表,按时间倒序最多 120 条。

    Args:
        request: Django 请求对象,支持 ``user`` 查询参数(按发送者过滤)。

    Returns:
        渲染后的聊天语音表格页。
    """
    qs = ChatVoice.objects.select_related("owner").filter(
        status=ChatVoiceStatus.VISIBLE).order_by("-created_at")
    user_id = request.GET.get("user")
    if user_id:
        qs = qs.filter(owner_id=user_id)
    return render(request, "ops/chat_voices.html", {"voices": qs[:120]})


@require_POST
@staff_required
def chat_voice_delete(request, voice_id):
    """删除一条聊天语音:删文件,行保留并记审计。

    Args:
        request: Django 请求对象。
        voice_id: 聊天语音主键。

    Returns:
        刷新后的表格局部片段。
    """
    voice = get_object_or_404(ChatVoice, pk=voice_id)
    if voice.file:
        default_storage.delete(voice.file.name)
    voice.status = ChatVoiceStatus.DELETED
    voice.deleted_by = request.user
    voice.deleted_at = timezone.now()
    voice.save(update_fields=["status", "deleted_by", "deleted_at"])
    qs = ChatVoice.objects.select_related("owner").filter(
        status=ChatVoiceStatus.VISIBLE).order_by("-created_at")
    return render(request, "ops/partials/chat_voices_table.html", {"voices": qs[:120]})
```

`chatapp/ops/urls.py` 加两条(`chat-voices/` 与 `chat-voices/<int:voice_id>/delete`),`ops/base.html` 导航加「聊天语音」。

`chat_voices.html` 照 `chat_images.html` 写,表格列:发送者 / 试听 / 时长 / 大小 / 时间 / 删除;试听列:

```html
<audio controls preload="none" src="{{ voice.signed_file_url }}"></audio>
```

`partials/chat_voices_table.html` 为 `<tbody>` 片段,`hx-post` 删除后 `hx-target` 自身。

`report_detail.html` 在图片区块后加语音区块(最近 7 天,最多 10 条,同样 `<audio controls>`)。

- [ ] **Step 5: 跑测试确认通过**

Run: `cd chatapp && python manage.py test im ops users -v 2`
Expected: 全绿。

- [ ] **Step 6: 提交**

```bash
git add chatapp
git commit -m "feat(im): 语音注销清理与运营抽审"
```

---

### Task 3: imserver `kind=4` 协议与读时签名

**Files:**
- Modify: `imserver/src/util/media_sign.h`、`media_sign.cpp`(通用 `sign_media`)
- Modify: `imserver/src/service/message_service.h`、`message_service.cpp`(kind=4 校验)
- Modify: `imserver/src/net/ws_server.cpp`(解析 `kind:"voice"`)
- Modify: `imserver/src/net/frames.h`(推送帧)
- Modify: `imserver/src/net/http_api.cpp`(`message_json` 历史/会话)
- Test: `imserver/tests/message_service_test.cpp`

**Interfaces:**
- Consumes: 客户端帧 `{kind:"voice", voice:{url,duration_ms,size}}`。
- Produces: 推送/历史/会话 `last_message` 同形 `voice` 载荷,URL 已签名;`kind=4`。

- [ ] **Step 1: 写失败测试**

`imserver/tests/message_service_test.cpp` 追加(与现有 image 用例同款,`reset()` 在 `setUp` 里已由 fixture 处理):

```cpp
TEST(MessageServiceTest, SendsVoiceMessage) {
  reset();
  SendRequest request;
  request.from = 1;
  request.to = 2;
  request.client_msg_id = "v-1";
  request.kind = 4;
  request.voice = {{"url", "http://cdn/media/chat/voices/2026/10/a.m4a"},
                   {"duration_ms", 12500},
                   {"size", 48000}};
  const auto result = make_service().send(request);
  ASSERT_TRUE(std::holds_alternative<SendResult>(result));
  const auto rows = make_service().list_messages(1, 2, 0, 10);
  ASSERT_EQ(rows.size(), 1u);
  EXPECT_EQ(rows[0].kind, 4);
  EXPECT_NE(rows[0].body.find("\"duration_ms\":12500"), std::string::npos);
}

TEST(MessageServiceTest, RejectsVoiceWithForeignUrl) {
  reset();
  SendRequest request;
  request.from = 1;
  request.to = 2;
  request.client_msg_id = "v-2";
  request.kind = 4;
  request.voice = {{"url", "https://evil.example/a.m4a"},
                   {"duration_ms", 5000},
                   {"size", 1000}};
  const auto result = make_service().send(request);
  ASSERT_TRUE(std::holds_alternative<int>(result));
  EXPECT_EQ(std::get<int>(result), 42201);
}

TEST(MessageServiceTest, RejectsVoiceOutOfBounds) {
  reset();
  for (const auto& [duration, size] : std::vector<std::pair<int, int>>{
           {999, 1000}, {60001, 1000}, {5000, 0}, {5000, 2 * 1024 * 1024 + 1}}) {
    SendRequest request;
    request.from = 1;
    request.to = 2;
    request.client_msg_id = "v-bad";
    request.kind = 4;
    request.voice = {{"url", "http://cdn/media/chat/voices/a.m4a"},
                     {"duration_ms", duration},
                     {"size", size}};
    const auto result = make_service().send(request);
    ASSERT_TRUE(std::holds_alternative<int>(result)) << duration << "/" << size;
    EXPECT_EQ(std::get<int>(result), 42201);
  }
}
```

`reset()` 与 `make_service()` 是文件里现成的帮助函数,照 image 用例的写法即可。

- [ ] **Step 2: 跑测试确认失败**

Run: `docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_integration.sh`
Expected: 编译失败(`SendRequest` 无 `voice` 成员)。

- [ ] **Step 3: 通用化签名**

`media_sign.h` 把 `sign_image` 换成:

```cpp
  // 就地给对象里某个 URL 字段签名(图片有 url/thumb_url,语音只有 url)
  void sign_media(nlohmann::json& object, std::initializer_list<const char*> keys,
                  int64_t now = 0) const;
```

`media_sign.cpp`:

```cpp
void MediaSigner::sign_media(nlohmann::json& object,
                             std::initializer_list<const char*> keys, int64_t now) const {
  if (!enabled() || !object.is_object()) {
    return;
  }
  for (const char* key : keys) {
    if (!object.contains(key) || !object[key].is_string()) {
      continue;
    }
    object[key] = sign_url(object[key].get<std::string>(), now);
  }
}
```

`frames.h` 的图片分支改为 `signer.sign_media(data["image"], {"url", "thumb_url"});`,
`http_api.cpp` 同理;删掉 `sign_image` 声明与定义。

- [ ] **Step 4: 实现 kind=4**

`message_service.h`:`SendRequest` 加 `nlohmann::json voice;`,注释 `// kind=4 的载荷`。

`message_service.cpp` 的 kind 分支(`kind == 3` 之后)加:

```cpp
    } else if (request.kind == 4) {
      // 语音与图片同理:只接受本服务媒体前缀下的 URL,落规范 URL,读时现签
      const auto& voice = request.voice;
      if (!voice.is_object()) {
        return 42201;
      }
      const auto canonical = signer_.canonical(voice.value("url", std::string()));
      if (!canonical.has_value() || canonical->size() > 512) {
        return 42201;
      }
      const auto duration = voice.value("duration_ms", 0LL);
      const auto size = voice.value("size", 0LL);
      if (duration < 1000 || duration > 60000 || size <= 0 ||
          size > 2 * 1024 * 1024) {
        return 42201;
      }
      nlohmann::json stored = voice;
      stored["url"] = *canonical;
      body = {{"voice", stored}};
    } else {
```

`ws_server.cpp` 的 `handle_send` 在 `kind == "image"` 分支后加:

```cpp
    } else if (kind == "voice") {
      request.kind = 4;
      request.voice = data.at("voice");
```

`frames.h`:`kind_name` 加 `case 4: return "voice";`;`build_message_frame` 加

```cpp
  } else if (request.kind == 4) {
    data["voice"] = request.voice;
    signer.sign_media(data["voice"], {"url"});
```

`http_api.cpp::message_json` 加

```cpp
    } else if (row.kind == 4) {
      data["kind"] = "voice";
      data["voice"] = body.value("voice", nlohmann::json::object());
      signer.sign_media(data["voice"], {"url"});
```

- [ ] **Step 5: 跑测试确认通过**

Run: `docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test.sh`
Run: `docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_integration.sh`
Expected: 全绿。

- [ ] **Step 6: 提交**

```bash
git add imserver
git commit -m "feat(imserver): 语音消息 kind=4 与读时签名"
```

---

### Task 4: App IM 数据层(sendVoice / 解析 / capability)

**Files:**
- Modify: `app/lib/im/im_client.dart`(kind、字段、capability、抽象方法、resend)
- Create: `app/lib/im/self_voice_uploader.dart`
- Modify: `app/lib/im/self_im_client.dart`、`routing_im_client.dart`、`tencent_im_client.dart`
- Test: `app/test/im/self_im_client_test.dart`、`app/test/support/fake_im_client.dart`

**Interfaces:**
- Produces: `ImClient.sendVoice({peerId, localPath, durationMs})`;`ChatMessage.voiceUrl` / `voiceDurationMs`;`ChatMessageKind.voice`;`ImCapabilities.voice`;`SelfVoiceUploader.upload(path, durationMs) -> ChatVoiceUpload`。

- [ ] **Step 1: 写失败测试**

`app/test/im/self_im_client_test.dart` 追加(沿用该文件既有的假 transport 与上传器写法):

```dart
test('sendVoice 上传后发 kind=voice 帧并在 ack 后返回语音消息', () async {
  final uploader = _FakeVoiceUploader();
  final client = SelfImClient(
    transportFactory: () => transport,
    imageUploader: null,
    voiceUploader: uploader,
  );
  await client.init(bootstrap);
  await client.login(userId: 'u2', userSig: 't');

  final future = client.sendVoice(peerId: 'u9', localPath: '/tmp/a.m4a', durationMs: 12500);
  final sent = jsonDecode(transport.sent.single) as Map<String, dynamic>;
  expect(sent['data']['kind'], 'voice');
  expect(sent['data']['voice']['duration_ms'], 12500);
  expect(sent['data']['voice']['url'], 'http://cdn/media/chat/voices/a.m4a');

  transport.emit({
    'v': 1, 'type': 'ack', 'id': sent['id'],
    'data': {'msg_id': '77', 'seq': 3, 'ts': 1760000000000},
  });
  final message = await future;
  expect(message.kind, ChatMessageKind.voice);
  expect(message.voiceUrl, 'http://cdn/media/chat/voices/a.m4a');
  expect(message.voiceDurationMs, 12500);
  expect(uploader.calls.single, ('/tmp/a.m4a', 12500));
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/im/self_im_client_test.dart`
Expected: FAIL(`sendVoice` 未定义)。

- [ ] **Step 3: 扩模型与接口**

`app/lib/im/im_client.dart`:

- `enum ChatMessageKind { text, matchNotice, banNotice, image, voice, other }`;
- `ChatMessage` 加 `final String? voiceUrl; final int voiceDurationMs;`,构造参数 `this.voiceDurationMs = 0,`;`copyWith` 透传两字段;
- `ImCapabilities` 加 `this.voice = false,` 与 `final bool voice;`
- `ImClient` 加:

```dart
  /// 发送语音(仅自建后端支持;腾讯抛 [ImException] 42202)。
  Future<ChatMessage> sendVoice({required String peerId, required String localPath,
      required int durationMs}) =>
      throw const ImException(42202, '当前聊天服务暂不支持语音');
```

- `resend` 加语音分支:

```dart
    if (message.kind == ChatMessageKind.voice && message.localPath != null) {
      return sendVoice(peerId: message.peerId, localPath: message.localPath!,
          durationMs: message.voiceDurationMs);
    }
```

- [ ] **Step 4: 上传器**

`app/lib/im/self_voice_uploader.dart`(照 `self_image_uploader.dart`):

```dart
import 'dart:io';

import 'package:dio/dio.dart';

import '../core/api_client.dart';

/// 语音上传结果,字段与 `POST /api/v1/im/voices` 的响应一一对应。
class ChatVoiceUpload {
  const ChatVoiceUpload({required this.id, required this.url,
      required this.durationMs, required this.size});

  final int id;
  final String url;
  final int durationMs;
  final int size;

  /// 组装 WS `send` 帧里的 `voice` 载荷(与 imserver 约定同形)。
  Map<String, dynamic> toPayload() => {
        'url': url,
        'duration_ms': durationMs,
        'size': size,
      };
}

/// 上传器抽象:自建 IM 的语音要先经 Django 转码落盘,再发 WS 消息。
abstract class SelfVoiceUploader {
  Future<ChatVoiceUpload> upload(String localPath, int durationMs);
}

/// 走 Django 的上传实现(复用 ApiClient 的 JWT 与刷新通道)。
class ApiVoiceUploader implements SelfVoiceUploader {
  ApiVoiceUploader(this._api);

  final ApiClient _api;

  @override
  Future<ChatVoiceUpload> upload(String localPath, int durationMs) async {
    final bytes = await File(localPath).readAsBytes();
    final name = localPath.split(Platform.pathSeparator).last;
    final data = await _api.post('/im/voices', data: FormData.fromMap({
      'file': MultipartFile.fromBytes(bytes, filename: name),
      'duration_ms': '$durationMs',
    })) as Map<String, dynamic>;
    return ChatVoiceUpload(
      id: data['id'] as int,
      url: data['url'] as String,
      durationMs: data['duration_ms'] as int,
      size: data['size'] as int,
    );
  }
}
```

- [ ] **Step 5: SelfImClient 实现**

- 构造参数加 `SelfVoiceUploader? voiceUploader`,字段 `_voiceUploader`;
- `capabilities => const ImCapabilities(image: true, search: true, voice: true)`;
- `_PendingSend` 加 `ChatVoiceUpload? voice` 与 `int durationMs = 0`;
- `_onAck` 里按 `pending.voice` 还原:

```dart
    final voice = pending.voice;
    pending.completer.complete(ChatMessage(
      ...
      kind: voice != null
          ? ChatMessageKind.voice
          : (image == null ? ChatMessageKind.text : ChatMessageKind.image),
      voiceUrl: voice?.url,
      voiceDurationMs: voice?.durationMs ?? 0,
    ));
```

- 新增 `sendVoice`(照 `sendImage` 写,`kind: 'voice'`,载荷 `voice: voice.toPayload()`);
- `_messageFromJson` 加 `'voice' => ChatMessageKind.voice`,并解析:

```dart
    final voice = (json['voice'] as Map?)?.cast<String, dynamic>() ?? const {};
    ...
      voiceUrl: voice['url'] as String?,
      voiceDurationMs: (voice['duration_ms'] as num?)?.toInt() ?? 0,
```

- `routing_im_client.dart` 加 `sendVoice` 转发;`tencent_im_client.dart` 不用写(继承默认抛错),但 `capabilities` 显式 `voice: false`(如未传默认值)。

- [ ] **Step 6: 假客户端与测试辅助**

`app/test/support/fake_im_client.dart`:构造参数加 `voiceCapability = true`,`capabilities` 带上;加

```dart
  Future<ChatMessage> sendVoice({required String peerId, required String localPath,
      required int durationMs}) async {
    log.add('sendVoice:$peerId:$localPath:$durationMs');
    return ChatMessage(msgId: 'v-${log.length}', peerId: peerId, isSelf: true,
        timestamp: 0, kind: ChatMessageKind.voice, voiceUrl: 'http://cdn/v.m4a',
        voiceDurationMs: durationMs);
  }
```

- [ ] **Step 7: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat test test/im`
Expected: 全绿。

- [ ] **Step 8: 提交**

```bash
git add app/lib/im app/test
git commit -m "feat(app): 语音消息数据层与上传器"
```

---

### Task 5: App 录音、气泡与播放

**Files:**
- Modify: `app/pubspec.yaml`、`app/android/app/src/main/AndroidManifest.xml`、`app/ios/Runner/Info.plist`
- Create: `app/lib/im/voice_recorder.dart`、`app/lib/features/chat/voice_playback.dart`、`app/lib/features/chat/widgets/voice_bubble.dart`、`app/lib/features/chat/widgets/voice_record_overlay.dart`
- Modify: `app/lib/features/chat/chat_page.dart`、`chat_controller.dart`、`widgets/message_bubble.dart`、`chats_page.dart`(或会话行组件)
- Test: `app/test/features/chat/voice_bubble_test.dart`、`chat_page_test.dart`(追加)

**Interfaces:**
- Consumes: Task 4 的 `sendVoice` / `ChatMessageKind.voice`。
- Produces: `voiceRecorderProvider`(可注入假实现)、`voicePlayerProvider`、`VoiceBubble`。

- [ ] **Step 1: 写失败测试**

`app/test/features/chat/voice_bubble_test.dart`:

```dart
testWidgets('语音气泡显示秒数并可播放', (tester) async {
  final player = FakeVoicePlayer();
  await tester.pumpWidget(ProviderScope(
    overrides: [voicePlayerProvider.overrideWithValue(player)],
    child: MaterialApp(home: Scaffold(body: VoiceBubble(
      message: const ChatMessage(msgId: '1', peerId: 'u9', isSelf: false,
          timestamp: 0, kind: ChatMessageKind.voice,
          voiceUrl: 'http://cdn/v.m4a', voiceDurationMs: 12500),
    ))),
  ));
  expect(find.text('12″'), findsOneWidget);
  await tester.tap(find.byKey(const Key('voice.play')));
  await tester.pump();
  expect(player.played.single, 'http://cdn/v.m4a');
});
```

`chat_page_test.dart` 追加:

```dart
testWidgets('长按麦克风录音、松手发送语音', (tester) async {
  final recorder = FakeVoiceRecorder();
  await tester.pumpWidget(harness.pumpApp(overrides: [
    voiceRecorderProvider.overrideWithValue(recorder),
  ]));
  await tester.longPress(find.byKey(const Key('chat.mic')));
  await tester.pump(const Duration(seconds: 2));
  await tester.pumpAndSettle();
  expect(recorder.started, isTrue);
  expect(recorder.stopped, isTrue);
  expect(fakeIm.log, contains('sendVoice:u9:/tmp/voice.m4a:2000'));
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/chat/voice_bubble_test.dart`
Expected: FAIL(找不到 `VoiceBubble`)。

- [ ] **Step 3: 加依赖与权限**

`app/pubspec.yaml` dependencies 加:

```yaml
  record: ^5.1.2
  audioplayers: ^6.1.0
```

Run: `cd app && ../flutter/bin/flutter.bat pub get`
Expected: 解析成功(若版本与 Flutter 3.47 冲突,取 pub 提示的最近兼容版本,并把实际版本写回本计划)。

`AndroidManifest.xml` `<manifest>` 内加:

```xml
    <uses-permission android:name="android.permission.RECORD_AUDIO" />
```

`ios/Runner/Info.plist` 加:

```xml
	<key>NSMicrophoneUsageDescription</key>
	<string>用于录制并发送语音消息</string>
```

- [ ] **Step 4: 录音与播放抽象**

`app/lib/im/voice_recorder.dart`:

```dart
import 'dart:io';

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:path_provider/path_provider.dart';
import 'package:record/record.dart';

/// 录音抽象:测试注入假实现,避免依赖真实麦克风。
abstract class VoiceRecorder {
  Future<bool> hasPermission();
  Future<void> start(String path);
  /// 停止并返回文件路径;取消时返回 null。
  Future<String?> stop();
  Future<void> cancel();
}

/// `record` 包实现:AAC-LC / 单声道,输出 m4a。
class DeviceVoiceRecorder implements VoiceRecorder {
  final _recorder = AudioRecorder();

  @override
  Future<bool> hasPermission() => _recorder.hasPermission();

  @override
  Future<void> start(String path) => _recorder.start(
        const RecordConfig(encoder: AudioEncoder.aacLc, bitRate: 64000,
            sampleRate: 16000, numChannels: 1),
        path: path,
      );

  @override
  Future<String?> stop() => _recorder.stop();

  @override
  Future<void> cancel() async {
    await _recorder.cancel();
  }
}

final voiceRecorderProvider = Provider<VoiceRecorder>((ref) => DeviceVoiceRecorder());

/// 录音文件落在系统临时目录。
Future<String> voiceTempPath() async {
  final dir = await getTemporaryDirectory();
  return '${dir.path}${Platform.pathSeparator}voice-'
      '${DateTime.now().microsecondsSinceEpoch}.m4a';
}
```

> 若 `path_provider` 尚未在依赖里,同一次 pubspec 改动中加入 `path_provider: ^2.1.4`。

`app/lib/features/chat/voice_playback.dart`:

```dart
import 'dart:async';

import 'package:audioplayers/audioplayers.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

/// 语音播放抽象(单例,同一时刻只播一条)。
abstract class VoicePlayer {
  Future<void> play(String source, {required bool isLocal});
  Future<void> stop();
  Stream<void> get onComplete;
}

class DeviceVoicePlayer implements VoicePlayer {
  DeviceVoicePlayer() {
    _player.onPlayerComplete.listen((_) => _complete.add(null));
  }

  final _player = AudioPlayer();
  final _complete = StreamController<void>.broadcast();

  @override
  Stream<void> get onComplete => _complete.stream;

  @override
  Future<void> play(String source, {required bool isLocal}) async {
    await _player.stop();
    await _player.play(isLocal ? DeviceFileSource(source) : UrlSource(source));
  }

  @override
  Future<void> stop() => _player.stop();
}

final voicePlayerProvider = Provider<VoicePlayer>((ref) {
  final player = DeviceVoicePlayer();
  ref.onDispose(player.stop);
  return player;
});
```

- [ ] **Step 5: 气泡**

`app/lib/features/chat/widgets/voice_bubble.dart`:

```dart
/// 语音气泡:宽度随时长增长(60→180),播放/暂停图标 + 秒数。
class VoiceBubble extends ConsumerStatefulWidget {
  const VoiceBubble({super.key, required this.message});
  final ChatMessage message;

  @override
  ConsumerState<VoiceBubble> createState() => _VoiceBubbleState();
}

class _VoiceBubbleState extends ConsumerState<VoiceBubble> {
  bool _playing = false;
  late final StreamSubscription<void> _sub;

  @override
  void initState() {
    super.initState();
    _sub = ref.read(voicePlayerProvider).onComplete.listen((_) {
      if (mounted) setState(() => _playing = false);
    });
  }

  @override
  void dispose() {
    _sub.cancel();
    super.dispose();
  }

  Future<void> _toggle() async {
    final player = ref.read(voicePlayerProvider);
    if (_playing) {
      await player.stop();
      if (mounted) setState(() => _playing = false);
      return;
    }
    final message = widget.message;
    final local = message.localPath;
    final source = (local != null && local.isNotEmpty) ? local : (message.voiceUrl ?? '');
    if (source.isEmpty) return;
    setState(() => _playing = true);
    await player.play(source, isLocal: local != null && local.isNotEmpty);
  }

  @override
  Widget build(BuildContext context) {
    final seconds = (widget.message.voiceDurationMs / 1000).round().clamp(1, 60);
    final width = (60 + seconds * 2).clamp(60, 180).toDouble();
    return GestureDetector(
      key: const Key('voice.bubble'),
      onTap: _toggle,
      child: Container(
        width: width,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: widget.message.isSelf ? AppColors.brand : AppColors.bgCard,
          borderRadius: BorderRadius.circular(AppRadius.bubble),
        ),
        child: Row(children: [
          Icon(_playing ? Icons.pause_rounded : Icons.play_arrow_rounded,
              key: const Key('voice.play'), size: 20,
              color: widget.message.isSelf ? Colors.white : AppColors.text1),
          const SizedBox(width: 6),
          Text('$seconds″', style: AppText.body.copyWith(
              color: widget.message.isSelf ? Colors.white : AppColors.text1)),
        ]),
      ),
    );
  }
}
```

- [ ] **Step 6: 接进聊天页**

`message_bubble.dart`:

- 顶部 `if` 把 voice 视为支持类型:`message.kind != text && != image && != voice` 才走灰条;
- `_bubbleContent` 加 `if (message.kind == ChatMessageKind.voice) return VoiceBubble(message: message);`

`chat_controller.dart` 加:

```dart
  Future<void> sendVoice(String path, int durationMs) => _sendOut(ChatMessage(
        msgId: 'local-${DateTime.now().microsecondsSinceEpoch}',
        peerId: peerId,
        isSelf: true,
        timestamp: DateTime.now().millisecondsSinceEpoch,
        kind: ChatMessageKind.voice,
        localPath: path,
        voiceDurationMs: durationMs,
        isPending: true,
      ));
```

`chat_page.dart` 的 `_InputBar`(当前是 `StatelessWidget`,**改成 `ConsumerStatefulWidget`** 才能持有录音状态):

- 加参数 `onSendVoice: (String path, int ms)`;
- 在表情按钮左侧加麦克风按钮(`Key('chat.mic')`),用 `GestureDetector(onLongPressStart/onLongPressMoveUpdate/onLongPressEnd)`:

```dart
onLongPressStart: (_) => _startRecording(),
onLongPressMoveUpdate: (details) => _cancelArmed = details.localOffsetFromOrigin.dy < -60,
onLongPressEnd: (_) => _finishRecording(),
```

`_startRecording`:

```dart
  Future<void> _startRecording() async {
    final recorder = ref.read(voiceRecorderProvider);
    if (!await recorder.hasPermission()) {
      AppToast.show(context, '需要麦克风权限才能发语音');
      return;
    }
    final path = await voiceTempPath();
    await recorder.start(path);
    _stopwatch
      ..reset()
      ..start();
    setState(() => _recording = true);
  }
```

`_finishRecording`:

```dart
  Future<void> _finishRecording() async {
    _stopwatch.stop();
    final recorder = ref.read(voiceRecorderProvider);
    final path = await recorder.stop();
    final ms = _stopwatch.elapsedMilliseconds;
    setState(() => _recording = false);
    if (_cancelArmed || path == null) {
      await recorder.cancel();
      return;
    }
    if (ms < 1000) {
      AppToast.show(context, '说话时间太短');
      return;
    }
    widget.onSendVoice(path, ms);
  }
```

60 秒自动停:在 `_startRecording` 里起 `Timer(const Duration(seconds: 60), _finishRecording)`,
`_finishRecording` 开头 `_autoStop?.cancel()`。

录音浮层(`voice_record_overlay.dart`):居中半透明卡片,显示 `Stopwatch` 秒数与
`_cancelArmed ? '松开取消' : '松开发送,上滑取消'`(用 `ValueListenableBuilder` 或
200ms `Timer.periodic` 刷新)。

会话行:`chats_page.dart` 里 last message 文案处加 `ChatMessageKind.voice => '[语音]'`。

- [ ] **Step 7: 跑测试确认通过**

Run: `cd app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test`
Expected: analyze 零告警,测试全绿。

- [ ] **Step 8: 提交**

```bash
git add app
git commit -m "feat(app): 按住说话录音、语音气泡与播放"
```

---

### Task 6: Web 录音、上传、播放与气泡

**Files:**
- Modify: `web/src/im/types.ts`、`web/src/im/self/map.ts`、`web/src/im/self/client.ts`、`web/src/im/routing.ts`
- Create: `web/src/im/self/voice.ts`、`web/src/im/voicePlayer.ts`
- Create: `web/src/features/chat/MessageVoice.vue`
- Modify: `web/src/features/chat/MessageBubble.vue`、`ChatPage.vue`、`web/src/stores/chat.ts`、`web/src/features/chat/ChatsPage.vue`
- Test: `web/tests/unit/im-voice.spec.ts`、`web/tests/unit/im-map.spec.ts`(追加)、`web/tests/component/chat-page.spec.ts`(追加)

**Interfaces:**
- Consumes: Task 3 的 `kind=voice` 帧;Task 1 的 `/im/voices`。
- Produces: `uploadChatVoice(blob, durationMs)`;`sendVoice(peerId, blob, durationMs)`;`MessageVoice.vue`。

- [ ] **Step 1: 写失败测试**

`web/tests/unit/im-voice.spec.ts`:

```ts
import { describe, expect, it, vi } from 'vitest'
import { pickMimeType } from '@/im/self/voice'

describe('voice mime 选择', () => {
  it('优先 webm/opus', () => {
    const isSupported = vi.fn((type: string) => type.startsWith('audio/webm'))
    expect(pickMimeType(isSupported)).toBe('audio/webm;codecs=opus')
  })

  it('都不支持时返回 null', () => {
    expect(pickMimeType(() => false)).toBeNull()
  })
})
```

`web/tests/unit/im-map.spec.ts` 追加:

```ts
it('解析 voice 消息', () => {
  const message = messageFromJson({
    msg_id: '9', from: 'u9', to: 'u2', kind: 'voice', seq: 4, ts: 1,
    voice: { url: 'http://cdn/v.m4a', duration_ms: 12500, size: 48000 },
  }, 'u2')
  expect(message.kind).toBe(ChatMessageKind.voice)
  expect(message.voiceUrl).toBe('http://cdn/v.m4a')
  expect(message.voiceDurationMs).toBe(12500)
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test:run -- tests/unit/im-voice.spec.ts`
Expected: FAIL(模块不存在)。

- [ ] **Step 3: 类型与映射**

`types.ts`:枚举加 `voice = 'voice'`;`ChatMessage` 加 `voiceUrl: string | null`、`voiceDurationMs: number`;`ImCapabilities` 加 `voice: boolean`;`ImClient` 加 `sendVoice(peerId: string, blob: Blob, durationMs: number): Promise<ChatMessage>`。

`self/map.ts`:`const voice = (json.voice ?? {}) as Record<string, unknown>;`,
`if (kind === 'voice') messageKind = ChatMessageKind.voice;`,返回对象加
`voiceUrl: (voice.url as string | undefined) ?? null, voiceDurationMs: Number(voice.duration_ms ?? 0),`。

`routing.ts` 默认 capabilities 改 `{ image: false, search: false, voice: false }`。

`web/src/stores/chat.ts`:两处能力位同步加 `voice`——`const capabilities = ref<ImCapabilities>({ image: false, search: false, voice: false })` 与退出时的 `capabilities.value = { image: false, search: false, voice: false }`。

- [ ] **Step 4: 录音与上传**

`web/src/im/self/voice.ts`:

```ts
import { http } from '@/api/http'

export interface UploadedVoice {
  id: number
  url: string
  duration_ms: number
  size: number
}

const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4']

/** 选一个当前浏览器能录的 MIME;都不支持返回 null。 */
export function pickMimeType(
  isSupported: (type: string) => boolean = (type) => MediaRecorder.isTypeSupported(type),
): string | null {
  return MIME_CANDIDATES.find((type) => isSupported(type)) ?? null
}

export async function uploadChatVoice(blob: Blob, durationMs: number): Promise<UploadedVoice> {
  const form = new FormData()
  form.append('file', blob, 'voice.m4a')
  form.append('duration_ms', String(durationMs))
  const response = await http.post('/im/voices', form)
  return response.data as UploadedVoice
}
```

`client.ts`:

- `capabilities = { image: true, search: true, voice: true }`;
- `PendingSend` 加 `voice?: UploadedVoice`;
- ack 分支:kind 按 `voice ? voice : image ? image : text`,并带 `voiceUrl` / `voiceDurationMs`;
- 新增:

```ts
  async sendVoice(peerId: string, blob: Blob, durationMs: number): Promise<ChatMessage> {
    const voice = await this.uploadVoice(blob, durationMs)
    const id = `local-${Date.now()}${Math.floor(Math.random() * 1000)}`
    for (let attempt = 0; attempt < 3; attempt++) {
      const promise = new Promise<ChatMessage>((resolve, reject) => {
        this.pending.set(id, { peerId, text: '', voice, resolve, reject })
      })
      this.transport?.send(JSON.stringify({
        v: 1, type: 'send', id,
        data: {
          client_msg_id: id, to: peerId, kind: 'voice',
          voice: { url: voice.url, duration_ms: voice.duration_ms, size: voice.size },
        },
      }))
      try {
        return await Promise.race([promise, timeout()])
      } catch { this.pending.delete(id) }
    }
    throw new Error('发送失败,请重试')
  }
```

构造参数加 `private readonly uploadVoice = uploadChatVoice`。

- [ ] **Step 5: 播放器与气泡**

`web/src/im/voicePlayer.ts`:

```ts
let current: HTMLAudioElement | null = null

/** 单例播放:切歌先停上一条,结束回调用于复位图标。 */
export function playVoice(url: string, onEnd: () => void): void {
  stopVoice()
  current = new Audio(url)
  current.addEventListener('ended', onEnd)
  void current.play()
}

export function stopVoice(): void {
  current?.pause()
  current = null
}
```

`MessageVoice.vue`:`props.message`,`playing` ref,宽度 `60 + seconds * 2`(上限 180),
点击 `playing ? stopVoice() : playVoice(url, () => playing = false)`,图标 `▶/❚❚` + `12″`。

`MessageBubble.vue`:加 `const isVoice = computed(() => props.message.kind === ChatMessageKind.voice)`,
模板加 `<MessageVoice v-if="isVoice" :message="props.message" />`。

- [ ] **Step 6: 聊天页录音交互**

`ChatPage.vue`:

- 麦克风按钮放在图片按钮旁,`v-if="capabilities.voice"`(从 `chatStore.capabilities` 读,store 暴露);
- `pointerdown` → `startRecording()`:`navigator.mediaDevices.getUserMedia({audio:true})`,
  `new MediaRecorder(stream, { mimeType: pickMimeType()! })`,`ondataavailable` 收集 chunks,
  `start()`;记录 `startedAt = performance.now()`;
- `pointerup` → `stopRecording(send: true)`:停 `MediaRecorder`、停 tracks、拼 `Blob`,
  `duration = performance.now() - startedAt`,<1000ms 提示「说话时间太短」,否则
  `await chatStore.sendVoice(peerId, blob, duration)`;
- `pointermove` 上移 60px → `cancelArmed = true`,浮层文案切「松开取消」;
- 浮层用固定定位卡片显示秒数与提示;
- `onBeforeUnmount` 停止录音与播放。

`web/src/stores/chat.ts`:

```ts
async function sendVoice(peerId: string, blob: Blob, durationMs: number): Promise<ChatMessage> {
  await ensureConnected()
  const client = getImClient()
  const message = await client.sendVoice(peerId, blob, durationMs)
  ...
}
```

(照 `sendImage` 的占位/替换逻辑;`resend` 对 voice 目前不重发,直接提示。)

会话行 `ChatsPage.vue` 的摘要:加 `voice => '[语音]'`。

- [ ] **Step 7: 跑测试与静态检查**

Run: `cd web && npm run type-check && npm run lint && npm run test:run`
Expected: 零错误、零告警、全绿(覆盖率门槛 `npm run test:coverage` 也要过)。

- [ ] **Step 8: 提交**

```bash
git add web
git commit -m "feat(web): 语音录制、上传、播放与气泡"
```

---

### Task 7: 接口文档、踩坑册、部署核对与全量验证

**Files:**
- Modify: `docs/api/im.md`(新增 `/im/voices`)、`docs/api/README.md`(42 → 43)
- Modify: `docs/pitfalls/im.md`、`docs/ops/imserver.md`
- Modify: `CLAUDE.md`(接口表、下一步)
- Modify: `docs/superpowers/specs/2026-10-27-im-voice-messages-design.md`(状态改为「已交付」)

**Interfaces:**
- 无代码产出;`ApiDocsCoverageTests` 双向门禁必须绿。

- [ ] **Step 1: 补接口文档**

`docs/api/im.md` 新增一节,信息行格式与现有接口一致:

```markdown
## 上传聊天语音

`POST /api/v1/im/voices` · 需登录
```

参数表:`file`(必填,音频,≤5MB,M4A/AAC/WebM/OGG)、`duration_ms`(必填,1000–60000);
响应示例用真实响应(签名 query 打码);错误:`400` 参数不合法、`42901` 限流、`50302` 语音暂不可用。

`docs/api/README.md` 的总数改成 **43**,并在分册索引里补一条。

- [ ] **Step 2: 跑文档门禁**

Run: `cd chatapp && python manage.py test im.tests.ApiDocsCoverageTests -v 2`
Expected: PASS(若失败,按提示补/删条目)。

- [ ] **Step 3: 补踩坑与部署文档**

`docs/pitfalls/im.md` 追加两条:
- 「语音上传 503」= 服务器没装 ffmpeg/ffprobe(`which ffmpeg` 验证,宝塔软件商店安装);
- 「语音文件被当孤儿删掉」= `im_media_cleanup` 的 `known` 集合漏了 `ChatVoice.file`。

`docs/ops/imserver.md` 的部署核对单加:安装 ffmpeg、`ffprobe -version`、灰度手测清单
(Web→App 播放、上滑取消、60s 上限、ops 试听)。

- [ ] **Step 4: 更新 CLAUDE.md**

- 接口表加 `POST /im/voices`;
- 「下一步」段落改成:语音消息已交付,剩余上线切换与配置项(保留原文其余待办)。

- [ ] **Step 5: 全量验证**

```bash
cd chatapp && python manage.py test
cd ../app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test
cd ../web && npm run type-check && npm run lint && npm run test:coverage
docker compose -f ../imserver/docker-compose.test.yml run --rm test bash /src/scripts/test.sh
docker compose -f ../imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_integration.sh
```

Expected: 四端全绿;任何红先修再提交。

- [ ] **Step 6: 提交**

```bash
git add docs CLAUDE.md
git commit -m "docs(im): 语音消息接口、踩坑与部署核对"
```

---

## 交付后

- 服务器按 `docs/ops/imserver.md` 装 ffmpeg、重建 imserver 镜像、跑灰度 7/8 手测;
- 语音与图片一并记为「无机器审核 → 上线阻断项」;
- 探针加「语音可用」检查项(记待办,不阻塞本期)。
