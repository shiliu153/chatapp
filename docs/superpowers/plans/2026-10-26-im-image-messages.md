# 自建 IM 图片消息(图片二期)实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让自建 IM 支持单聊图片消息(上传、发送、历史、会话列表、撤回、失败重发、运营抽审),补齐全量切换的最后一项功能门槛。

**Architecture:** 图片文件与元数据落在 Django(`POST /api/v1/im/images` + `im.ChatImage` 表,复用 JWT/限流/Pillow/媒体目录);imserver 只扩协议(`kind=3` + `image` 载荷 + `IM_MEDIA_PREFIX` 前缀校验);两端 IM 抽象层填 `sendImage` 实现;ops 照抄照片审核形态加一节抽审页。

**Tech Stack:** Django 5.2 + DRF、Pillow、C++20 + Beast + nlohmann/json、Flutter(image_picker)、Vue 3 + axios + canvas。

## Global Constraints

- 后端测试:`cd chatapp && python manage.py test`(前置 Redis 容器在跑),必须全绿。
- 注释规范:`docs/standards/python.md` —— 新增/修改 `.py` 必须补模块 docstring 与函数/类 docstring,公开函数带参数必须写 `Args:`。
- 接口文档:`docs/api/` 同一次改动内同步,`ApiDocsCoverageTests` 双向门禁(信息行格式 `> \`POST\` \`/api/v1/...\``)。
- App:`../flutter/bin/flutter.bat analyze` 零告警 + `test` 全绿。
- Web:`npm run type-check` 零错误、`npm run lint` 零告警(`--max-warnings 0`)、`npm run test:run` 全绿。
- imserver:`docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test.sh`(unit)与 `... bash /src/scripts/test_integration.sh`(db)全绿。
- 错误契约:失败一律 `{"code":<HTTP 状态码>,"message":"<中文>","request_id":...}`。
- 响应路径禁止第三方网络调用;IM 副作用一律走 Celery(`im/tasks.py`)。
- 文案与注释一律中文;不要新增裸 hex / 裸字号(本计划不涉及 UI 视觉改动)。

---

## 文件结构

| 文件 | 职责 |
|---|---|
| `chatapp/im/models.py` | `ChatImage`(文件元数据 + 删除审计) |
| `chatapp/im/serializers.py`(新) | 上传入参校验(大小/格式) |
| `chatapp/im/throttles.py`(新) | `ChatImageThrottle`(30/小时/用户) |
| `chatapp/im/views.py` | `upload_image`:落盘 + 缩略图 + 返回 URL |
| `chatapp/im/urls.py` | `POST /im/images` |
| `chatapp/users/services.py` | 注销时收集并删除聊天图片文件 |
| `chatapp/ops/{views,urls}.py` + 模板 | 聊天图片抽审列表 / 删除 / 举报详情区块 |
| `imserver/src/config.*` | `IM_MEDIA_PREFIX`(必填) |
| `imserver/src/service/message_service.*` | `SendRequest` 的 kind/image/custom + 分 kind 校验与落库 |
| `imserver/src/net/{ws_server,http_api}.cpp`、`frames.h` | 收发 image 帧、历史/会话返回 image、灰条按 kind=2 落库 |
| `app/lib/im/self_image_uploader.dart`(新) | 上传器抽象 + Django 实现 |
| `app/lib/im/self_im_client.dart` | `sendImage`、解析 image、`capabilities.image=true` |
| `app/lib/im/routing_im_client.dart`、`im_manager.dart` | 注入上传器 |
| `app/lib/core/image_pick.dart` | 聊天选图 1920 参数 |
| `web/src/im/self/image.ts`(新) | canvas 压缩 + 上传 |
| `web/src/im/self/{client.ts,map.ts}` | `sendImage`、解析 image、capabilities |
| `docs/api/im.md` 等 | 接口/协议/部署文档同步 |

---

### Task 1: `ChatImage` 模型与迁移

**Files:**
- Modify: `chatapp/im/models.py`
- Create: `chatapp/im/migrations/0001_initial.py`(由 `makemigrations` 生成)
- Test: `chatapp/im/tests.py`

**Interfaces:**
- Produces: `ChatImage(owner, file, thumb, width, height, bytes, status, deleted_by, deleted_at, created_at)`;`ChatImageStatus.VISIBLE/DELETED`;`ChatImage.objects`。

- [x] **Step 1: 写失败的模型测试**

在 `chatapp/im/tests.py` 顶部导入区补 `import tempfile`、`import shutil`、`from django.core.files.uploadedfile import SimpleUploadedFile`,并在文件末尾追加:

```python
class ChatImageModelTests(TestCase):
    """聊天图片元数据:默认状态、可读表示、随用户级联删除。"""

    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(phone="13900139001")

    def test_defaults_to_visible_and_str_is_readable(self):
        image = ChatImage.objects.create(
            owner=self.user,
            file=SimpleUploadedFile("a.jpg", PNG_1PX, content_type="image/jpeg"),
            thumb=SimpleUploadedFile("a_thumb.jpg", PNG_1PX, content_type="image/jpeg"),
            width=10, height=20, bytes=len(PNG_1PX))
        self.assertEqual(image.status, ChatImageStatus.VISIBLE)
        self.assertIn("chat_image#", str(image))

    def test_cascade_deletes_rows_with_user(self):
        ChatImage.objects.create(
            owner=self.user,
            file=SimpleUploadedFile("a.jpg", PNG_1PX, content_type="image/jpeg"),
            thumb=SimpleUploadedFile("a_thumb.jpg", PNG_1PX, content_type="image/jpeg"),
            width=10, height=20, bytes=len(PNG_1PX))
        self.user.delete()
        self.assertEqual(ChatImage.objects.count(), 0)
```

`PNG_1PX` 在 `chatapp/im/tests.py` 里还没有,补一个模块级常量(与 `users/tests.py` 同款):

```python
# 1×1 透明 PNG:最小合法图片,用于上传类用例
PNG_1PX = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
           b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
           b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")
```

同时补导入:`from .models import ChatImage, ChatImageStatus`。

- [x] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test im.tests.ChatImageModelTests -v 2`
Expected: FAIL —— `ImportError: cannot import name 'ChatImage'`。

- [x] **Step 3: 写模型**

把 `chatapp/im/models.py` 整体替换为:

```python
"""IM 应用的本地数据模型:聊天图片元数据。

消息本身仍存在自建 imserver 的库(或腾讯云侧),Django 这边只落**图片文件**
的元数据,用于运营抽审、删除审计与注销清理。

设计要点:
    1. 文件名带随机 uuid(由视图生成),不用自增主键 —— 防止顺着 URL 遍历别人的私聊图;
    2. 运营删除只改 ``status`` 并留 ``deleted_by/deleted_at``,不删行 —— 审计可查;
    3. ``width/height`` 存的是**显示尺寸**(已按 EXIF 方向校正),不是文件原始像素。
"""

from django.conf import settings
from django.db import models


class ChatImageStatus(models.TextChoices):
    """聊天图片的状态。"""

    VISIBLE = "visible", "正常"
    DELETED = "deleted", "已删除"


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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        """后台与日志中的可读表示。

        Returns:
            ``chat_image#主键(owner=发送者 id)``。
        """
        return f"chat_image#{self.pk}(owner={self.owner_id})"
```

- [x] **Step 4: 生成迁移并跑测试**

Run:
```
cd chatapp && python manage.py makemigrations im && python manage.py migrate
cd chatapp && python manage.py test im.tests.ChatImageModelTests -v 2
```
Expected: `0001_initial.py` 生成;测试 2 个全 PASS。

- [x] **Step 5: 提交**

```bash
git add chatapp/im/models.py chatapp/im/migrations/0001_initial.py chatapp/im/tests.py
git commit -m "feat(im): 聊天图片元数据表 ChatImage"
```

---

### Task 2: 上传接口 `POST /api/v1/im/images`

**Files:**
- Create: `chatapp/im/serializers.py`、`chatapp/im/throttles.py`
- Modify: `chatapp/im/views.py`、`chatapp/im/urls.py`、`chatapp/config/settings.py`
- Test: `chatapp/im/tests.py`
- Docs: `docs/api/im.md`(信息行,否则 `ApiDocsCoverageTests` 红)

**Interfaces:**
- Produces: `POST /api/v1/im/images` → `{id,url,thumb_url,width,height,size}`;`ChatImageUploadSerializer`;`ChatImageThrottle`。
- 依赖 Task 1 的 `ChatImage`。

- [x] **Step 1: 写失败的接口测试**

在 `chatapp/im/tests.py` 追加:

```python
class ChatImageUploadTests(APITestCase):
    """聊天图片上传:成功返回四元组、大小/格式/尺寸校验、限流、重封禁拦截。"""

    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir, MEDIA_BASE_URL="http://cdn.test",
                                 CHAT_IMAGE_RATE="2/hour")
        override.enable()
        self.addCleanup(override.disable)
        cache.clear()   # 限流计数按用户缓存在 Redis,用例间必须清
        self.user = User.objects.create_user(phone="13900139002")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")
        self.url = "/api/v1/im/images"

    def upload(self, name="a.png", content=PNG_1PX, content_type="image/png"):
        """上传一张图片。

        Args:
            name: 文件名。
            content: 文件字节内容。
            content_type: MIME 类型。

        Returns:
            DRF 测试客户端的响应对象。
        """
        return self.client.post(
            self.url, {"file": SimpleUploadedFile(name, content, content_type=content_type)},
            format="multipart")

    def test_upload_returns_urls_and_dimensions(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.data)
        data = response.data
        self.assertTrue(data["url"].startswith("http://cdn.test/media/chat/"))
        self.assertTrue(data["thumb_url"].endswith("_thumb.jpg"))
        self.assertEqual((data["width"], data["height"]), (1, 1))
        self.assertEqual(data["size"], len(PNG_1PX))
        image = ChatImage.objects.get()
        self.assertEqual(image.owner_id, self.user.id)
        self.assertTrue(image.file.storage.exists(image.file.name))
        self.assertTrue(image.thumb.storage.exists(image.thumb.name))

    def test_rejects_non_image(self):
        response = self.upload(name="a.txt", content=b"not an image", content_type="text/plain")
        self.assertEqual(response.status_code, 400)

    def test_rejects_oversized_file(self):
        with override_settings(CHAT_IMAGE_MAX_BYTES=10):
            response = self.upload()
        self.assertEqual(response.status_code, 400)
        self.assertIn("5MB", str(response.data))

    def test_rejects_too_large_side(self):
        with override_settings(CHAT_IMAGE_MAX_SIDE=0):
            response = self.upload()
        self.assertEqual(response.status_code, 400)

    def test_throttled_after_rate(self):
        self.assertEqual(self.upload().status_code, 201)
        self.assertEqual(self.upload().status_code, 201)
        self.assertEqual(self.upload().status_code, 429)

    def test_heavy_banned_user_is_forbidden(self):
        profile = get_profile(self.user)          # 资料行是懒创建的,不能直接 user.profile
        profile.status = ProfileStatus.BANNED_HEAVY
        profile.save(update_fields=["status"])
        self.assertEqual(self.upload().status_code, 403)

    def test_exif_orientation_swaps_dimensions_and_reencodes(self):
        content = _jpeg_with_orientation()
        response = self.upload(name="rotated.jpg", content=content, content_type="image/jpeg")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data["width"], response.data["height"]), (20, 40))
        self.assertTrue(response.data["url"].endswith(".jpg"))
```

`_jpeg_with_orientation` 与 `ProfileStatus` 需要导入;在 `chatapp/im/tests.py` 追加模块级辅助函数与导入:

```python
from io import BytesIO

from PIL import Image

from users.models import ProfileStatus
from users.services import get_profile


def _jpeg_with_orientation(size=(40, 20), orientation=6):
    """生成一张带 EXIF 方向标签的 JPEG(6 = 顺时针 90°,显示时宽高互换)。

    Args:
        size: 原始像素尺寸(宽, 高)。
        orientation: EXIF Orientation 值。

    Returns:
        JPEG 字节内容。
    """
    buffer = BytesIO()
    image = Image.new("RGB", size, (200, 30, 30))
    exif = image.getexif()
    exif[0x0112] = orientation
    image.save(buffer, "JPEG", exif=exif)
    return buffer.getvalue()
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test im.tests.ChatImageUploadTests -v 2`
Expected: FAIL —— 404(路由不存在)。

- [x] **Step 3: 写序列化器、限流、视图、路由与配置**

新建 `chatapp/im/serializers.py`:

```python
"""IM 接口的入参校验:聊天图片上传。"""

from django.conf import settings
from rest_framework import serializers

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


class ChatImageUploadSerializer(serializers.Serializer):
    """聊天图片上传入参(multipart 字段 ``file``)。"""

    file = serializers.ImageField()

    def validate_file(self, value):
        """校验大小与格式。

        Args:
            value: 上传的图片文件(DRF 已用 Pillow 校验过是真实图片)。

        Returns:
            通过校验的文件对象。

        Raises:
            serializers.ValidationError: 超过大小上限,或格式不在白名单。
        """
        if value.size > settings.CHAT_IMAGE_MAX_BYTES:
            raise serializers.ValidationError("图片不能超过 5MB")
        if value.content_type not in ALLOWED_CONTENT_TYPES:
            raise serializers.ValidationError("只支持 JPG/PNG/WebP")
        return value
```

新建 `chatapp/im/throttles.py`:

```python
"""IM 接口的限流:聊天图片上传。"""

from rest_framework.throttling import SimpleRateThrottle


class ChatImageThrottle(SimpleRateThrottle):
    """按用户限流聊天图片上传;额度在 settings.DEFAULT_THROTTLE_RATES["chat_image"]。"""

    scope = "chat_image"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该用户在 ``chat_image`` 作用域下的缓存键。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
```

`chatapp/im/views.py` 追加(导入区补 `io`、`uuid`、`PIL`、`django.core.files.base.ContentFile`、`django.utils.timezone`、`rest_framework.decorators.throttle_classes`、`.models`、`.serializers`、`.throttles`):

```python
SUFFIX_BY_CONTENT_TYPE = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}


@api_view(["POST"])
@throttle_classes([ChatImageThrottle])
def upload_image(request):
    """上传一张聊天图片(POST /api/v1/im/images)。

    同步落盘 + 生成缩略图,不进 Celery:这条路径没有第三方调用,
    符合「响应路径禁止外部调用」纪律。文件名带随机 uuid,不可枚举。

    Args:
        request: DRF 请求对象,multipart 字段为 ``file``。

    Returns:
        201 + ``{id, url, thumb_url, width, height, size}``;URL 用
        ``settings.MEDIA_BASE_URL`` 拼绝对地址(与 IM 头像同步同一套)。
    """
    serializer = ChatImageUploadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    upload = serializer.validated_data["file"]
    raw = upload.read()
    try:
        image = Image.open(io.BytesIO(raw))
        orientation = image.getexif().get(0x0112, 1)
        display = ImageOps.exif_transpose(image)
        width, height = display.size
    except Exception:
        return Response({"code": 400, "message": "请上传图片文件"}, status=400)

    if max(width, height) > settings.CHAT_IMAGE_MAX_SIDE:
        return Response({"code": 400, "message": "图片尺寸过大,请先压缩"}, status=400)

    stem = f"{request.user.id}-{uuid.uuid4().hex}"
    month = timezone.localtime().strftime("%Y/%m")
    if orientation == 1:
        data, suffix = raw, SUFFIX_BY_CONTENT_TYPE[upload.content_type]
    else:
        buffer = io.BytesIO()
        display.convert("RGB").save(buffer, "JPEG", quality=85)
        data, suffix = buffer.getvalue(), ".jpg"

    chat_image = ChatImage(owner=request.user, width=width, height=height, bytes=len(data))
    chat_image.file.save(f"chat/{month}/{stem}{suffix}", ContentFile(data), save=False)

    thumb = display.copy()
    thumb.thumbnail((settings.CHAT_IMAGE_THUMB_SIDE, settings.CHAT_IMAGE_THUMB_SIDE),
                    Image.Resampling.LANCZOS)
    thumb_buffer = io.BytesIO()
    thumb.convert("RGB").save(thumb_buffer, "JPEG", quality=80)
    chat_image.thumb.save(f"chat/{month}/{stem}_thumb.jpg",
                          ContentFile(thumb_buffer.getvalue()), save=False)
    chat_image.save()

    base = settings.MEDIA_BASE_URL.rstrip("/")
    return Response({
        "id": chat_image.id,
        "url": f"{base}{chat_image.file.url}",
        "thumb_url": f"{base}{chat_image.thumb.url}",
        "width": chat_image.width,
        "height": chat_image.height,
        "size": chat_image.bytes,
    }, status=201)
```

`chatapp/im/urls.py` 加一行:

```python
urlpatterns = [
    path("user_sig", views.user_sig),
    path("images", views.upload_image),
]
```

`chatapp/config/settings.py` 在「照片」段后追加:

```python
# --- 聊天图片(图片二期)---
CHAT_IMAGE_MAX_BYTES = 5 * 1024 * 1024
CHAT_IMAGE_MAX_SIDE = 4096
CHAT_IMAGE_THUMB_SIDE = 240
CHAT_IMAGE_RATE = os.getenv("CHAT_IMAGE_RATE", "30/hour")
```

并在 `DEFAULT_THROTTLE_RATES` 里加 `"chat_image": CHAT_IMAGE_RATE,`。

`docs/api/im.md` 补信息行(放在文件里 `POST /api/v1/im/user_sig` 那条附近):

```markdown
> `POST` `/api/v1/im/images` · 上传一张聊天图片(自建 IM 发图前置步骤)
```

- [x] **Step 4: 跑测试**

Run:
```
cd chatapp && python manage.py test im -v 2
cd chatapp && python manage.py test config.tests.ApiDocsCoverageTests -v 2
```
Expected: 全 PASS;文档门禁绿。

- [x] **Step 5: 提交**

```bash
git add chatapp/im/serializers.py chatapp/im/throttles.py chatapp/im/views.py chatapp/im/urls.py chatapp/config/settings.py chatapp/im/tests.py docs/api/im.md
git commit -m "feat(im): 聊天图片上传接口(缩略图/限流/EXIF 校正)"
```

---

### Task 3: 注销账号时清理聊天图片文件

**Files:**
- Modify: `chatapp/users/services.py:99-116`
- Test: `chatapp/users/tests.py`

**Interfaces:**
- Consumes: Task 1 的 `ChatImage`。
- Produces: `delete_account()` 收集并删除 `ChatImage.file` / `.thumb` 两个文件。

- [x] **Step 1: 写失败的测试**

在 `chatapp/users/tests.py` 的账号注销用例类里追加(类内已有 `self.media_dir` 与登录设施):

```python
def test_deletes_chat_image_files_on_disk(self):
    from im.models import ChatImage
    image = ChatImage.objects.create(
        owner=self.user,
        file=SimpleUploadedFile("c.jpg", PNG_1PX, content_type="image/jpeg"),
        thumb=SimpleUploadedFile("c_thumb.jpg", PNG_1PX, content_type="image/jpeg"),
        width=1, height=1, bytes=len(PNG_1PX))
    paths = [image.file.path, image.thumb.path]
    with patch("im.tasks.delete_account.delay"):
        response = self.client.delete("/api/v1/users/me", {"phone": self.user.phone},
                                      format="json")
    self.assertEqual(response.status_code, 204)
    for path in paths:
        self.assertFalse(os.path.exists(path), path)
```

(若该用例类没有 `os` / `SimpleUploadedFile` / `PNG_1PX`,按文件顶部现有导入补齐。)

- [x] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test users.tests.AccountDeletionTests -v 2`
Expected: FAIL —— 文件仍在磁盘上。

- [x] **Step 3: 实现**

`chatapp/users/services.py::delete_account` 里,`file_names` 收集段改为:

```python
    from feed.models import PostImage   # 延迟导入,避免 app 加载顺序问题(同 im/tasks.py)
    from im.models import ChatImage

    file_names = list(user.photos.values_list("file", flat=True))
    file_names += list(PostImage.objects.filter(post__author=user).values_list("file", flat=True))
    file_names += list(ChatImage.objects.filter(owner=user).values_list("file", flat=True))
    file_names += list(ChatImage.objects.filter(owner=user).values_list("thumb", flat=True))
```

其余逻辑不动(仍在 `on_commit` 里逐个 `default_storage.delete`)。

- [x] **Step 4: 跑测试**

Run: `cd chatapp && python manage.py test users.tests.AccountDeletionTests -v 2`
Expected: PASS。

- [x] **Step 5: 提交**

```bash
git add chatapp/users/services.py chatapp/users/tests.py
git commit -m "feat(users): 注销账号时清理聊天图片文件"
```

---

### Task 4: imserver 配置 + `SendRequest` 分 kind 校验 + WS 发图

**Files:**
- Modify: `imserver/src/config.{h,cpp}`、`imserver/src/service/message_service.{h,cpp}`、`imserver/src/net/frames.h`、`imserver/src/net/ws_server.cpp`、`imserver/src/main.cpp`、`imserver/deploy/imserver.env.example`、`imserver/docker-compose.test.yml`、`imserver/scripts/{test,test_http,test_integration}.sh`
- Test: `imserver/tests/config_test.cpp`、`imserver/tests/message_service_test.cpp`

**Interfaces:**
- Produces: `Config::media_prefix`;`SendRequest{from,to,client_msg_id,text,kind,image,custom}`;`MessageService::send` 支持 kind=3;`build_message_frame(result, request)`。
- 后续 Task 5 依赖 `request.kind` / `request.image` / `request.custom`。

- [x] **Step 1: 写失败的测试**

`imserver/tests/config_test.cpp` 里给两个「只有必填键」的用例补上 `IM_MEDIA_PREFIX`,并新增断言:

```cpp
TEST(ConfigTest, RequiresMediaPrefix) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_JWT_SECRET", "jwt"},
      {"IM_INTERNAL_SECRET", "internal"}};
  EXPECT_THROW(Config::from_map(env), std::runtime_error);
}

TEST(ConfigTest, ReadsMediaPrefix) {
  std::map<std::string, std::string> env{
      {"IM_MYSQL_DSN", "mysql://u:p@127.0.0.1:3306/db"},
      {"IM_JWT_SECRET", "jwt"},
      {"IM_INTERNAL_SECRET", "internal"},
      {"IM_MEDIA_PREFIX", "http://127.0.0.1:8000/media/chat/"}};
  EXPECT_EQ(Config::from_map(env).media_prefix, "http://127.0.0.1:8000/media/chat/");
}
```

`imserver/tests/message_service_test.cpp` 追加:

```cpp
TEST(MessageServiceTest, SendsImageMessage) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");

  SendRequest request;
  request.from = 1;
  request.to = 2;
  request.client_msg_id = "img-1";
  request.kind = 3;
  request.image = {{"url", "http://cdn/media/chat/a.jpg"},
                   {"thumb_url", "http://cdn/media/chat/a_thumb.jpg"},
                   {"width", 1080}, {"height", 1440}, {"size", 345678}};
  const auto result = svc.send(request);
  ASSERT_TRUE(std::holds_alternative<SendResult>(result));

  const auto rows = svc.list_messages(2, 1, 0, 10);
  ASSERT_EQ(rows.size(), 1u);
  EXPECT_EQ(rows[0].kind, 3);
  EXPECT_NE(rows[0].body.find("\"image\""), std::string::npos);
}

TEST(MessageServiceTest, RejectsImageWithForeignUrl) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");

  SendRequest request;
  request.from = 1;
  request.to = 2;
  request.client_msg_id = "img-2";
  request.kind = 3;
  request.image = {{"url", "http://evil.example/a.jpg"},
                   {"thumb_url", "http://cdn/media/chat/a_thumb.jpg"},
                   {"width", 1080}, {"height", 1440}, {"size", 345678}};
  const auto result = svc.send(request);
  ASSERT_TRUE(std::holds_alternative<int>(result));
  EXPECT_EQ(std::get<int>(result), 42201);
}

TEST(MessageServiceTest, RejectsImageWithBadDimensions) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");

  SendRequest request;
  request.from = 1;
  request.to = 2;
  request.client_msg_id = "img-3";
  request.kind = 3;
  request.image = {{"url", "http://cdn/media/chat/a.jpg"},
                   {"thumb_url", "http://cdn/media/chat/a_thumb.jpg"},
                   {"width", 0}, {"height", 1440}, {"size", 345678}};
  const auto result = svc.send(request);
  ASSERT_TRUE(std::holds_alternative<int>(result));
  EXPECT_EQ(std::get<int>(result), 42201);
}
```

测试里的 `http://cdn/media/chat/` 必须等于测试环境配置的 `IM_MEDIA_PREFIX` —— 在 `imserver/docker-compose.test.yml` 的 `test.environment` 里加:

```yaml
      IM_MEDIA_PREFIX: http://cdn/media/chat/
```

- [x] **Step 2: 跑测试确认失败**

Run: `docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test.sh`
Expected: FAIL —— `Config` 无 `media_prefix`、`SendRequest` 无 `kind`(编译失败)。

- [x] **Step 3: 实现**

`imserver/src/config.h` 的 `Config` 里加:

```cpp
  std::string media_prefix;   // 例:https://<host>/media/chat/(聊天图片 URL 前缀,必填)
```

`imserver/src/config.cpp` 的 `from_map` 里加读取与必填校验,并把新键加进 `from_env` 的 key 列表:

```cpp
  cfg.media_prefix = get_or(env, "IM_MEDIA_PREFIX");
  ...
  if (cfg.media_prefix.empty()) {
    throw std::runtime_error("missing IM_MEDIA_PREFIX");
  }
```

`imserver/src/service/message_service.h` 的 `SendRequest` 改为:

```cpp
struct SendRequest {
  uint64_t from = 0;
  uint64_t to = 0;
  std::string client_msg_id;
  std::string text;
  int kind = 1;                    // 1=text 2=custom 3=image
  nlohmann::json image;            // kind=3 的载荷
  nlohmann::json custom;           // kind=2 的载荷
};
```

(文件顶部补 `#include <nlohmann/json.hpp>`。)

构造函数与成员:

```cpp
  MessageService(MysqlPool& pool, UserRepo& users, ConversationRepo& conversations,
                 MessageRepo& messages, BlacklistRepo& blacklist,
                 std::size_t text_max = 2000, std::string media_prefix = "");
  ...
  std::string media_prefix_;
```

`imserver/src/service/message_service.cpp`:

```cpp
MessageService::MessageService(MysqlPool& pool, UserRepo& users,
                               ConversationRepo& conversations, MessageRepo& messages,
                               BlacklistRepo& blacklist, std::size_t text_max,
                               std::string media_prefix)
    : pool_(pool), users_(users), conversations_(conversations), messages_(messages),
      blacklist_(blacklist), text_max_(text_max), media_prefix_(std::move(media_prefix)) { ... }
```

`send()` 开头的校验与 `body` 构造替换为:

```cpp
  const auto text = trim(request.text);
  if (request.to == 0 || request.from == request.to || !valid_client_id(request.client_msg_id)) {
    return 42201;
  }
  nlohmann::json body;
  try {
    if (request.kind == 1) {
      if (text.empty() || utf8_length(text) > text_max_) {
        return 42201;
      }
      body = {{"text", text}};
    } else if (request.kind == 2) {
      if (!request.custom.is_object() || request.custom.value("type", "").empty()) {
        return 42201;
      }
      body = request.custom;
    } else if (request.kind == 3) {
      const auto& image = request.image;
      if (!image.is_object()) {
        return 42201;
      }
      const auto url = image.value("url", std::string());
      const auto thumb = image.value("thumb_url", std::string());
      const auto width = image.value("width", 0ULL);
      const auto height = image.value("height", 0ULL);
      const auto size = image.value("size", 0ULL);
      const bool prefixed = !media_prefix_.empty() && url.rfind(media_prefix_, 0) == 0 &&
                            thumb.rfind(media_prefix_, 0) == 0;
      if (!prefixed || url.size() > 512 || thumb.size() > 512 || width == 0 || height == 0 ||
          width > 4096 || height > 4096 || size == 0 || size > 5 * 1024 * 1024) {
        return 42201;
      }
      body = {{"image", image}};
    } else {
      return 42201;
    }
  } catch (const std::exception&) {
    return 42201;
  }
```

事务内的 `const std::string body = nlohmann::json{{"text", text}}.dump();` 改为使用上面构造好的 `body.dump()`,并把 `messages_.insert(..., 1, body, ...)` 的 kind 改为 `request.kind`。

`imserver/src/net/frames.h` 整体替换为:

```cpp
#pragma once
#include <nlohmann/json.hpp>

#include <string>

#include "service/message_service.h"

inline std::string kind_name(int kind) {
  switch (kind) {
    case 2:
      return "custom";
    case 3:
      return "image";
    default:
      return "text";
  }
}

inline std::string build_message_frame(const SendResult& result, const SendRequest& request) {
  nlohmann::json data = {
      {"msg_id", std::to_string(result.msg_id)},
      {"seq", result.seq},
      {"from", "u" + std::to_string(request.from)},
      {"to", "u" + std::to_string(request.to)},
      {"kind", kind_name(request.kind)},
      {"ts", result.ts},
      {"revoked", false},
      {"from_profile",
       {{"nickname", result.from_nickname}, {"avatar", result.from_avatar}}}};
  if (request.kind == 2) {
    data["custom"] = request.custom;
  } else if (request.kind == 3) {
    data["image"] = request.image;
  } else {
    data["text"] = request.text;
  }
  return nlohmann::json{{"v", 1}, {"type", "message"}, {"data", data}}.dump();
}
```

`imserver/src/net/ws_server.cpp::handle_send` 中「只允许 text」那段替换为:

```cpp
    SendRequest request;
    request.from = uid_;
    request.to = to_uid;
    request.client_msg_id = data.value("client_msg_id", frame.value("id", std::string()));
    const auto kind = data.value("kind", std::string("text"));
    if (kind == "image") {
      request.kind = 3;
      request.image = data.at("image");
    } else if (kind == "text") {
      request.kind = 1;
      request.text = data.value("text", std::string());
    } else {
      send_raw(error_frame(42201, "暂不支持该消息类型"));
      return;
    }
```

`on_send_result` 里的推送改为 `build_message_frame(*ok, request)`(删掉旧的 `"text"` / `text` / 空 custom 三个实参)。

`imserver/src/main.cpp`:

```cpp
    MessageService message_service(mysql, users, conversations, messages, blacklist,
                                   cfg.text_max, cfg.media_prefix);
```

`imserver/deploy/imserver.env.example` 加一行(带注释):

```
# 聊天图片 URL 前缀:必须与 Django 的 MEDIA_BASE_URL + /media/chat/ 一致,缺失则启动失败
IM_MEDIA_PREFIX=https://<your-host>/media/chat/
```

`imserver/scripts/test.sh`、`test_http.sh`、`test_integration.sh` 顶部各加(保证脱离 compose 单独跑时也有值):

```bash
export IM_MEDIA_PREFIX="${IM_MEDIA_PREFIX:-http://cdn/media/chat/}"
```

- [x] **Step 4: 跑测试**

Run:
```
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test.sh
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_integration.sh
```
Expected: 两个脚本全 PASS(含新增的 3 个 image 用例与 2 个 config 用例)。

- [x] **Step 5: 提交**

```bash
git add imserver/src imserver/tests imserver/deploy/imserver.env.example imserver/docker-compose.test.yml imserver/scripts
git commit -m "feat(imserver): 图片消息 kind=3 + IM_MEDIA_PREFIX 前缀校验"
```

---

### Task 5: 历史/会话返回 image + 灰条按 kind=2 落库

**Files:**
- Modify: `imserver/src/net/http_api.cpp`、`tools/im_e2e.py`
- Test: `imserver/tests/message_service_test.cpp`(db 层)+ `tools/im_e2e.py`(端到端)

**Interfaces:**
- Consumes: Task 4 的 `SendRequest.kind/custom`、`kind_name()`。
- Produces: `GET /im/api/messages`、`GET /im/api/conversations` 的 `kind:"image"` 载荷;`/internal/send` 的 custom 以 `kind=2` 落库。

- [x] **Step 1: 写失败的测试**

`imserver/tests/message_service_test.cpp` 追加:

```cpp
TEST(MessageServiceTest, StoresCustomAsKindTwo) {
  reset();
  auto& svc = make_service();
  svc.users().ensure(1, "A");
  svc.users().ensure(2, "B");

  SendRequest request;
  request.from = 1;
  request.to = 2;
  request.client_msg_id = "sys-1";
  request.kind = 2;
  request.custom = {{"type", "match_notice"}, {"desc", "你们已互相喜欢"}, {"data", {}}};
  ASSERT_TRUE(std::holds_alternative<SendResult>(svc.send(request)));

  const auto rows = svc.list_messages(2, 1, 0, 10);
  ASSERT_EQ(rows.size(), 1u);
  EXPECT_EQ(rows[0].kind, 2);
  EXPECT_NE(rows[0].body.find("match_notice"), std::string::npos);
}
```

`tools/im_e2e.py` 的 `main()` 在文本消息循环后追加(并在文件顶部加 `IM_MEDIA_PREFIX = os.environ["IM_MEDIA_PREFIX"]`):

```python
    image_url = IM_MEDIA_PREFIX + "2026/10/e2e.jpg"
    await a.send(json.dumps({
        "v": 1,
        "type": "send",
        "id": "e2e-image",
        "data": {
            "client_msg_id": "e2e-image",
            "to": f"u{b_uid}",
            "kind": "image",
            "image": {"url": image_url,
                      "thumb_url": IM_MEDIA_PREFIX + "2026/10/e2e_thumb.jpg",
                      "width": 1080, "height": 1440, "size": 345678},
        },
    }))
    ack = await recv(a, "ack")
    pushed = await recv(b, "message")
    assert pushed["data"]["kind"] == "image"
    assert pushed["data"]["image"]["url"] == image_url
    history = get(f"/messages?peer=u{a_uid}", b_uid)["items"]
    assert any(item["kind"] == "image" for item in history)
```

- [x] **Step 2: 跑测试确认失败**

Run:
```
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_integration.sh
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
```
Expected: 前者 FAIL(`kind` 仍是 1);后者 FAIL(`kind` 断言不成立,推送里没有 image)。

- [x] **Step 3: 实现**

`imserver/src/net/http_api.cpp::message_json` 的分支替换为:

```cpp
  if (row.revoked_at.has_value()) {
    data["kind"] = "text";
  } else {
    const auto body = nlohmann::json::parse(row.body);
    if (row.kind == 3) {
      data["kind"] = "image";
      data["image"] = body.value("image", nlohmann::json::object());
    } else if (row.kind == 2) {
      data["kind"] = "custom";
      data["custom"] = body;
    } else {
      data["kind"] = "text";
      data["text"] = body.value("text", "");
    }
  }
```

`internal_route` 的 `/internal/send` 段替换为:

```cpp
    if (target.path == "/internal/send") {
      SendRequest request;
      request.from = body.at("from").get<uint64_t>();
      request.to = body.at("to").get<uint64_t>();
      request.client_msg_id = "sys-" + random_uuid();
      const auto kind = body.value("kind", std::string("text"));
      if (kind == "text") {
        request.kind = 1;
        request.text = body.value("text", std::string());
      } else {
        request.kind = 2;
        request.custom = body.at("custom");
      }
      const auto result = messages_.send(request);
      if (const auto* ok = std::get_if<SendResult>(&result)) {
        registry_.send_to(request.to, build_message_frame(*ok, request));
        return json_response(req, http::status::ok,
                             {{"ok", true},
                              {"msg_id", std::to_string(ok->msg_id)},
                              {"seq", ok->seq}});
      }
      return error_response(req, http::status::bad_request, std::get<int>(result),
                            "发送失败");
    }
```

- [x] **Step 4: 跑测试**

Run:
```
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_integration.sh
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
```
Expected: 全 PASS(端到端含 image 推送与历史)。

- [x] **Step 5: 提交**

```bash
git add imserver/src/net/http_api.cpp imserver/tests/message_service_test.cpp tools/im_e2e.py
git commit -m "feat(imserver): 历史与会话返回 image,灰条按 kind=2 落库"
```

---

### Task 6: App —— 上传器 + `sendImage` + 解析 + capabilities

**Files:**
- Create: `app/lib/im/self_image_uploader.dart`
- Modify: `app/lib/im/self_im_client.dart`、`app/lib/im/routing_im_client.dart`、`app/lib/im/im_manager.dart`
- Test: `app/test/im/self_im_client_test.dart`

**Interfaces:**
- Produces: `ChatImageUpload{id,url,thumbUrl,width,height,size}`、`SelfImageUploader` 抽象、`ApiImageUploader`;`SelfImClient({transportFactory, httpClient, imageUploader})`。
- Consumes: Task 2 的 `POST /api/v1/im/images`。

- [x] **Step 1: 写失败的测试**

`app/test/im/self_im_client_test.dart` 追加(文件顶部补 `import 'package:chatapp_app/im/self_image_uploader.dart';`):

```dart
class FakeUploader implements SelfImageUploader {
  FakeUploader({this.failure});
  final Object? failure;
  final uploaded = <String>[];

  @override
  Future<ChatImageUpload> upload(String localPath) async {
    uploaded.add(localPath);
    if (failure != null) throw failure!;
    return const ChatImageUpload(
      id: 1,
      url: 'http://cdn/media/chat/a.jpg',
      thumbUrl: 'http://cdn/media/chat/a_thumb.jpg',
      width: 1080,
      height: 1440,
      size: 345678,
    );
  }
}
```

并在 `main()` 里追加用例:

```dart
  test('self client advertises image capability', () {
    expect(SelfImClient().capabilities.image, isTrue);
  });

  test('sendImage uploads then sends an image frame and resolves on ack', () async {
    final transport = FakeTransport();
    final uploader = FakeUploader();
    final client = SelfImClient(
        transportFactory: () => transport, imageUploader: uploader);
    await client.init(bootstrap);
    final login = client.login(userId: 'u9', userSig: 'tok');
    await pumpEventQueue();
    transport.emit(jsonEncode({
      'v': 1, 'type': 'auth_ok', 'data': {'uid': 9, 'heartbeat_sec': 25},
    }));
    await login;

    final pending = client.sendImage(peerId: 'u2', imagePath: '/tmp/a.jpg');
    await pumpEventQueue();
    expect(uploader.uploaded, ['/tmp/a.jpg']);
    final frame = jsonDecode(transport.sent.last) as Map<String, dynamic>;
    expect(frame['type'], 'send');
    expect(frame['data']['kind'], 'image');
    expect(frame['data']['image']['thumb_url'], 'http://cdn/media/chat/a_thumb.jpg');

    transport.emit(jsonEncode({
      'v': 1, 'type': 'ack', 'id': frame['id'],
      'data': {'msg_id': '42', 'seq': 1, 'ts': 1700000000000},
    }));
    final sent = await pending;
    expect(sent.kind, ChatMessageKind.image);
    expect(sent.imageUrl, 'http://cdn/media/chat/a_thumb.jpg');
    expect(sent.imageLargeUrl, 'http://cdn/media/chat/a.jpg');
  });

  test('sendImage surfaces upload failure as ImException', () async {
    final transport = FakeTransport();
    final client = SelfImClient(
        transportFactory: () => transport,
        imageUploader: FakeUploader(failure: const ImException(400, '图片不能超过 5MB')));
    await client.init(bootstrap);
    final login = client.login(userId: 'u9', userSig: 'tok');
    await pumpEventQueue();
    transport.emit(jsonEncode({
      'v': 1, 'type': 'auth_ok', 'data': {'uid': 9, 'heartbeat_sec': 25},
    }));
    await login;

    expect(
      () => client.sendImage(peerId: 'u2', imagePath: '/tmp/a.jpg'),
      throwsA(isA<ImException>()),
    );
  });

  test('parses incoming image message', () async {
    final transport = FakeTransport();
    final client = SelfImClient(transportFactory: () => transport);
    await client.init(bootstrap);
    final login = client.login(userId: 'u9', userSig: 'tok');
    await pumpEventQueue();
    transport.emit(jsonEncode({
      'v': 1, 'type': 'auth_ok', 'data': {'uid': 9, 'heartbeat_sec': 25},
    }));
    await login;

    final events = <ImEvent>[];
    client.events.listen(events.add);
    transport.emit(jsonEncode({
      'v': 1, 'type': 'message',
      'data': {
        'msg_id': '7', 'seq': 2, 'from': 'u2', 'to': 'u9', 'kind': 'image',
        'ts': 1700000000000, 'revoked': false,
        'image': {'url': 'http://cdn/media/chat/b.jpg',
                  'thumb_url': 'http://cdn/media/chat/b_thumb.jpg',
                  'width': 10, 'height': 20, 'size': 100},
      },
    }));
    await pumpEventQueue();
    final message = (events.single as ImNewMessage).message;
    expect(message.kind, ChatMessageKind.image);
    expect(message.imageUrl, 'http://cdn/media/chat/b_thumb.jpg');
    expect(message.imageLargeUrl, 'http://cdn/media/chat/b.jpg');
  });
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/im/self_im_client_test.dart`
Expected: FAIL —— `SelfImageUploader` 未定义、`sendImage` 抛 42202。

- [x] **Step 3: 实现**

新建 `app/lib/im/self_image_uploader.dart`:

```dart
import 'dart:io';

import 'package:dio/dio.dart';

import '../core/api_client.dart';

/// 聊天图片上传结果,字段与 `POST /api/v1/im/images` 的响应一一对应。
class ChatImageUpload {
  const ChatImageUpload({
    required this.id,
    required this.url,
    required this.thumbUrl,
    required this.width,
    required this.height,
    required this.size,
  });

  final int id;
  final String url;
  final String thumbUrl;
  final int width;
  final int height;
  final int size;

  /// 组装 WS `send` 帧里的 `image` 载荷(与 imserver 约定同形)。
  Map<String, dynamic> toPayload() => {
        'url': url,
        'thumb_url': thumbUrl,
        'width': width,
        'height': height,
        'size': size,
      };
}

/// 上传器抽象:自建 IM 的图片要先经 Django 落盘,再发 WS 消息。
abstract class SelfImageUploader {
  Future<ChatImageUpload> upload(String localPath);
}

/// 走 Django 的上传实现(复用 ApiClient 的 JWT 与刷新通道)。
class ApiImageUploader implements SelfImageUploader {
  ApiImageUploader(this._api);

  final ApiClient _api;

  @override
  Future<ChatImageUpload> upload(String localPath) async {
    final bytes = await File(localPath).readAsBytes();
    final name = localPath.split(Platform.pathSeparator).last;
    final data = await _api.post('/im/images', data: FormData.fromMap({
      'file': MultipartFile.fromBytes(bytes, filename: name),
    })) as Map<String, dynamic>;
    return ChatImageUpload(
      id: data['id'] as int,
      url: data['url'] as String,
      thumbUrl: data['thumb_url'] as String,
      width: data['width'] as int,
      height: data['height'] as int,
      size: data['size'] as int,
    );
  }
}
```

`app/lib/im/self_im_client.dart`:

1. 构造参数加 `SelfImageUploader? imageUploader`,字段 `final SelfImageUploader? _uploader;`
2. `capabilities` 改为 `const ImCapabilities(image: true)`;
3. `_PendingSend` 扩展:

```dart
class _PendingSend {
  _PendingSend(this.peerId, this.completer, {this.text = '', this.image});
  final String peerId;
  final String text;
  final ChatImageUpload? image;
  final Completer<ChatMessage> completer;
}
```

4. `_onAck` 里返回的消息按是否有 image 分支:

```dart
    final image = pending.image;
    pending.completer.complete(ChatMessage(
      msgId: '${data['msg_id'] ?? ''}',
      peerId: pending.peerId,
      isSelf: true,
      timestamp: (data['ts'] as num?)?.toInt() ?? DateTime.now().millisecondsSinceEpoch,
      kind: image == null ? ChatMessageKind.text : ChatMessageKind.image,
      text: pending.text,
      imageUrl: image?.thumbUrl,
      imageLargeUrl: image?.url,
    ));
```

5. `sendText` 里 `_PendingSend(peerId, text, completer)` 改为 `_PendingSend(peerId, completer, text: text)`;
6. `sendImage` 实现:

```dart
  @override
  Future<ChatMessage> sendImage({required String peerId, required String imagePath}) async {
    final uploader = _uploader;
    if (uploader == null) {
      throw const ImException(42202, '当前聊天服务暂不支持图片');
    }
    final image = await uploader.upload(imagePath);
    final id = 'local-${DateTime.now().microsecondsSinceEpoch}';
    final completer = Completer<ChatMessage>();
    _pendingSends[id] = _PendingSend(peerId, completer, image: image);
    for (var attempt = 0; attempt < 3; attempt++) {
      _transport?.send(jsonEncode({
        'v': 1,
        'type': 'send',
        'id': id,
        'data': {
          'client_msg_id': id,
          'to': peerId,
          'kind': 'image',
          'image': image.toPayload(),
        },
      }));
      try {
        return await completer.future.timeout(const Duration(seconds: 10));
      } on TimeoutException {
        if (attempt == 2) break;
      }
    }
    _pendingSends.remove(id);
    throw const ImException(50001, '发送失败,请重试');
  }
```

7. `_messageFromJson` 加 image 分支:

```dart
    final image = (json['image'] as Map?)?.cast<String, dynamic>() ?? const {};
    final messageKind = switch (kind) {
      'custom' when customType == 'match_notice' => ChatMessageKind.matchNotice,
      'custom' when customType.isNotEmpty => ChatMessageKind.banNotice,
      'custom' => ChatMessageKind.other,
      'image' => ChatMessageKind.image,
      _ => ChatMessageKind.text,
    };
    ...
      imageUrl: image['thumb_url'] as String?,
      imageLargeUrl: image['url'] as String?,
```

`app/lib/im/routing_im_client.dart`:构造参数加 `SelfImageUploader? imageUploader`,并在 `init` 里传给 `SelfImClient(imageUploader: imageUploader)`。

`app/lib/im/im_manager.dart:12`:

```dart
final imClientProvider = Provider<ImClient>(
    (ref) => RoutingImClient(imageUploader: ApiImageUploader(ref.watch(apiClientProvider))));
```

- [x] **Step 4: 跑测试与静态检查**

Run:
```
cd app && ../flutter/bin/flutter.bat test test/im/self_im_client_test.dart
cd app && ../flutter/bin/flutter.bat analyze
```
Expected: 4 个新用例 PASS;analyze 零告警。

- [x] **Step 5: 提交**

```bash
git add app/lib/im app/test/im/self_im_client_test.dart
git commit -m "feat(app): 自建 IM 图片上传与发送(sendImage)"
```

---

### Task 7: App —— 聊天选图参数与 UI 回归

**Files:**
- Modify: `app/lib/core/image_pick.dart`、`app/lib/features/chat/chat_page.dart:40,127`
- Test: `app/test/features/chat/chat_page_test.dart`(若无则新建)

**Interfaces:**
- Consumes: Task 6 的 `sendImage`。
- Produces: `pickChatImageFromGallery()`(长边 1920 / q80)。

- [x] **Step 1: 写失败的测试**

在 `app/test/features/chat/` 下新建 `chat_image_test.dart`:

```dart
import 'package:flutter_test/flutter_test.dart';

import 'package:chatapp_app/core/image_pick.dart';

void main() {
  test('聊天选图使用 1920 长边与 0.8 质量的压缩参数', () {
    // 参数常量集中在 image_pick.dart,这里防止后续被误改成资料照的 1080/0.85
    expect(chatImageMaxSide, 1920);
    expect(chatImageQuality, 80);
    expect(pickChatImageFromGallery, isNotNull);
  });
}
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd app && ../flutter/bin/flutter.bat test test/features/chat/chat_image_test.dart`
Expected: FAIL —— `chatImageMaxSide` 未定义。

- [x] **Step 3: 实现**

`app/lib/core/image_pick.dart` 追加:

```dart
/// 聊天图片压缩参数:长边 1920、质量 80(与资料照的 1080/85 分开,聊天图要看细节)。
const int chatImageMaxSide = 1920;
const int chatImageQuality = 80;

/// 聊天选图:单张,按聊天图片参数压缩。
Future<XFile?> pickChatImageFromGallery() => ImagePicker().pickImage(
      source: ImageSource.gallery,
      maxWidth: chatImageMaxSide.toDouble(),
      maxHeight: chatImageMaxSide.toDouble(),
      imageQuality: chatImageQuality,
    );
```

`app/lib/features/chat/chat_page.dart` 的构造默认值 `this.pickImage = pickImageFromGallery` 改为 `this.pickImage = pickChatImageFromGallery`。

- [x] **Step 4: 跑测试与静态检查**

Run:
```
cd app && ../flutter/bin/flutter.bat test test/features/chat
cd app && ../flutter/bin/flutter.bat analyze
```
Expected: 全 PASS,analyze 零告警。

- [x] **Step 5: 提交**

```bash
git add app/lib/core/image_pick.dart app/lib/features/chat/chat_page.dart app/test/features/chat/chat_image_test.dart
git commit -m "feat(app): 聊天选图使用 1920/80 压缩参数"
```

---

### Task 8: Web —— canvas 压缩 + 上传 + 解析 + capabilities

**Files:**
- Create: `web/src/im/self/image.ts`
- Modify: `web/src/im/self/client.ts`、`web/src/im/self/map.ts`
- Test: `web/tests/unit/im-self.spec.ts`、`web/tests/unit/im-image.spec.ts`(新)

**Interfaces:**
- Produces: `compressImage(file, maxSide?, quality?)`、`uploadChatImage(file)`、`SelfImClient({uploadImage?})`。
- Consumes: Task 2 的上传接口。

- [x] **Step 1: 写失败的测试**

新建 `web/tests/unit/im-image.spec.ts`:

```ts
import { describe, expect, it } from 'vitest'

import { compressImage } from '@/im/self/image'

describe('compressImage', () => {
  it('画布不可用时原样返回文件(jsdom 无 canvas)', async () => {
    const file = new File([new Uint8Array([1, 2, 3])], 'a.jpg', { type: 'image/jpeg' })
    const result = await compressImage(file)
    expect(result).toBe(file)
  })
})
```

`web/tests/unit/im-self.spec.ts` 追加(文件里已有 `FakeTransport` 与 `bootstrap`,直接复用;顶部补
`import { messageFromJson } from '@/im/self/map'`)。**同时把现有用例第 47 行的
`expect(client.capabilities.image).toBe(false)` 改成 `true`** —— 这是本任务要翻的行为:

```ts
  it('capabilities 声明支持图片', () => {
    expect(new SelfImClient().capabilities.image).toBe(true)
  })

  it('sendImage 先上传再发 image 帧,ack 后返回图片消息', async () => {
    const transport = new FakeTransport()
    const uploads: File[] = []
    const client = new SelfImClient(() => transport, async (file: File) => {
      uploads.push(file)
      return {
        id: 1,
        url: 'http://cdn/media/chat/a.jpg',
        thumb_url: 'http://cdn/media/chat/a_thumb.jpg',
        width: 1080,
        height: 1440,
        size: 345678,
      }
    })
    await client.init(bootstrap)
    const login = client.login('u9', 'tok')
    transport.emit(JSON.stringify({ v: 1, type: 'auth_ok', data: { uid: 9 } }))
    await login

    const file = new File([new Uint8Array([1])], 'a.jpg', { type: 'image/jpeg' })
    const pending = client.sendImage('u2', file)
    await Promise.resolve()
    const frame = JSON.parse(transport.sent[transport.sent.length - 1])
    expect(frame.data.kind).toBe('image')
    expect(frame.data.image.thumb_url).toBe('http://cdn/media/chat/a_thumb.jpg')

    transport.emit(JSON.stringify({
      v: 1, type: 'ack', id: frame.id, data: { msg_id: '42', seq: 1, ts: 1700000000000 },
    }))
    const message = await pending
    expect(message.kind).toBe('image')
    expect(message.imageUrl).toBe('http://cdn/media/chat/a_thumb.jpg')
    expect(message.imageLargeUrl).toBe('http://cdn/media/chat/a.jpg')
    expect(uploads).toHaveLength(1)
  })

  it('解析收到的 image 消息', () => {
    const message = messageFromJson({
      msg_id: '7', seq: 2, from: 'u2', to: 'u9', kind: 'image', ts: 1, revoked: false,
      image: { url: 'http://cdn/b.jpg', thumb_url: 'http://cdn/b_thumb.jpg', width: 10, height: 20, size: 100 },
    }, 'u9')
    expect(message.kind).toBe('image')
    expect(message.imageUrl).toBe('http://cdn/b_thumb.jpg')
    expect(message.imageLargeUrl).toBe('http://cdn/b.jpg')
  })
```

- [x] **Step 2: 跑测试确认失败**

Run: `cd web && npm run test:run -- im-image im-self`
Expected: FAIL —— `@/im/self/image` 不存在、`capabilities.image` 仍是 false。

- [x] **Step 3: 实现**

新建 `web/src/im/self/image.ts`:

```ts
/**
 * 聊天图片的浏览器侧处理:canvas 压缩 + 上传到 Django。
 *
 * 为什么在客户端压:2C2G 服务器不替客户端转码;长边 1920 / JPEG 0.8
 * 与原图相比通常小一个数量级,聊天页只展示缩略图。
 */

import { http } from '@/api/http'

export interface UploadedImage {
  id: number
  url: string
  thumb_url: string
  width: number
  height: number
  size: number
}

export const CHAT_IMAGE_MAX_SIDE = 1920
export const CHAT_IMAGE_QUALITY = 0.8

/** 压到长边 1920 的 JPEG;环境不支持 canvas 时原样返回。 */
export async function compressImage(
  file: File,
  maxSide = CHAT_IMAGE_MAX_SIDE,
  quality = CHAT_IMAGE_QUALITY,
): Promise<Blob> {
  if (typeof document === 'undefined' || typeof createImageBitmap === 'undefined') {
    return file
  }
  const bitmap = await createImageBitmap(file)
  const scale = Math.min(1, maxSide / Math.max(bitmap.width, bitmap.height))
  const canvas = document.createElement('canvas')
  canvas.width = Math.max(1, Math.round(bitmap.width * scale))
  canvas.height = Math.max(1, Math.round(bitmap.height * scale))
  const context = canvas.getContext('2d')
  if (!context) return file
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)
  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, 'image/jpeg', quality))
  return blob ?? file
}

/** 压缩后上传,返回后端给的 URL 与尺寸。 */
export async function uploadChatImage(file: File): Promise<UploadedImage> {
  const blob = await compressImage(file)
  const form = new FormData()
  form.append('file', blob, 'chat.jpg')
  const response = await http.post('/im/images', form)
  return response.data as UploadedImage
}
```

`web/src/im/self/map.ts` 的 `messageFromJson` 加 image 分支:

```ts
  const image = (json.image ?? {}) as Record<string, unknown>
  ...
  let messageKind = ChatMessageKind.text
  if (kind === 'custom') { ... }
  if (kind === 'image') messageKind = ChatMessageKind.image
  ...
    imageUrl: (image.thumb_url as string | undefined) ?? null,
    imageLargeUrl: (image.url as string | undefined) ?? null,
```

`web/src/im/self/client.ts`:

1. 构造参数**保持第一个位置参数不变**(现有测试是 `new SelfImClient(() => transport)`),只在后面追加注入点:

```ts
  constructor(
    private readonly transportFactory: () => SelfTransport = () => new BrowserWebSocketTransport(),
    private readonly uploadImage: (file: File) => Promise<UploadedImage> = uploadChatImage,
  ) {}
```

(`login` 里 `this.transportFactory()` 的调用不变。)

2. `capabilities` 改 `{ image: true }`;
3. `PendingSend` 加 `image?: UploadedImage` 并让 ack 分支还原:

```ts
      const image = pending.image
      pending.resolve({
        ...,
        kind: image ? ChatMessageKind.image : ChatMessageKind.text,
        text: pending.text,
        imageUrl: image ? image.thumb_url : null,
        imageLargeUrl: image ? image.url : null,
      })
```

4. `sendImage` 实现:

```ts
  async sendImage(peerId: string, file: File): Promise<ChatMessage> {
    const image = await this.uploadImage(file)
    const id = `local-${Date.now()}${Math.floor(Math.random() * 1000)}`
    for (let attempt = 0; attempt < 3; attempt++) {
      const promise = new Promise<ChatMessage>((resolve, reject) => {
        this.pending.set(id, { peerId, text: '', image, resolve, reject })
      })
      this.transport?.send(JSON.stringify({
        v: 1,
        type: 'send',
        id,
        data: {
          client_msg_id: id,
          to: peerId,
          kind: 'image',
          image: {
            url: image.url,
            thumb_url: image.thumb_url,
            width: image.width,
            height: image.height,
            size: image.size,
          },
        },
      }))
      try {
        return await Promise.race([
          promise,
          new Promise<ChatMessage>((_, reject) =>
            setTimeout(() => reject(new Error('发送超时')), 10000)),
        ])
      } catch {
        this.pending.delete(id)
      }
    }
    throw new Error('发送失败,请重试')
  }
```

- [x] **Step 4: 跑测试与检查**

Run:
```
cd web && npm run test:run -- im-image im-self
cd web && npm run type-check && npm run lint
```
Expected: 新用例 PASS;type-check / lint 零错误。

- [x] **Step 5: 提交**

```bash
git add web/src/im/self web/tests/unit/im-image.spec.ts web/tests/unit/im-self.spec.ts
git commit -m "feat(web): 自建 IM 图片压缩、上传与发送"
```

---

### Task 9: ops 聊天图片抽审

**Files:**
- Modify: `chatapp/ops/views.py`、`chatapp/ops/urls.py`、`chatapp/ops/templates/ops/base.html`、`chatapp/ops/templates/ops/report_detail.html`
- Create: `chatapp/ops/templates/ops/chat_images.html`、`chatapp/ops/templates/ops/partials/chat_images_table.html`
- Test: `chatapp/ops/tests.py`

**Interfaces:**
- Consumes: Task 1 的 `ChatImage`。
- Produces: `GET /ops/chat-images/`、`POST /ops/chat-images/<id>/delete`;举报详情页上下文新增 `chat_images`。

- [x] **Step 1: 写失败的测试**

`chatapp/ops/tests.py` 追加:

```python
class ChatImageOpsTests(TestCase):
    """聊天图片抽审:列表可见、删除置 deleted 且删文件、举报详情带最近图片。"""

    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)
        self.staff = make_staff()
        self.client.force_login(self.staff)
        self.user = User.objects.create_user(phone="13900139003")
        self.image = ChatImage.objects.create(
            owner=self.user,
            file=SimpleUploadedFile("c.jpg", PNG_1PX, content_type="image/jpeg"),
            thumb=SimpleUploadedFile("c_thumb.jpg", PNG_1PX, content_type="image/jpeg"),
            width=1, height=1, bytes=len(PNG_1PX))

    def test_lists_chat_images(self):
        response = self.client.get("/ops/chat-images/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "聊天图片")
        self.assertContains(response, str(self.image.id))

    def test_delete_marks_status_and_removes_files(self):
        paths = [self.image.file.path, self.image.thumb.path]
        response = self.client.post(f"/ops/chat-images/{self.image.id}/delete")
        self.assertEqual(response.status_code, 200)
        self.image.refresh_from_db()
        self.assertEqual(self.image.status, ChatImageStatus.DELETED)
        self.assertEqual(self.image.deleted_by_id, self.staff.id)
        for path in paths:
            self.assertFalse(os.path.exists(path), path)

    def test_report_detail_shows_recent_chat_images(self):
        report = Report.objects.create(reporter=self.staff, target=self.user,
                                       type=ReportType.PORN)
        response = self.client.get(f"/ops/reports/{report.id}/")
        self.assertContains(response, "最近聊天图片")
```

(`ReportType.PORN` 是现有取值;`tempfile`/`shutil`/`os`/`SimpleUploadedFile`/`ChatImage`/`ChatImageStatus`/`PNG_1PX` 按需补导入。)

- [x] **Step 2: 跑测试确认失败**

Run: `cd chatapp && python manage.py test ops.tests.ChatImageOpsTests -v 2`
Expected: FAIL —— 404(路由不存在)。

- [x] **Step 3: 实现**

`chatapp/ops/views.py` 追加(导入 `ChatImage, ChatImageStatus`、`default_storage`、`timezone`、`timedelta`):

```python
@staff_required
def chat_images(request):
    """聊天图片抽审列表,按时间倒序最多 120 条。

    Args:
        request: Django 请求对象,支持 ``user`` 查询参数(按发送者过滤)。

    Returns:
        渲染后的聊天图片表格页。
    """
    qs = ChatImage.objects.select_related("owner").filter(
        status=ChatImageStatus.VISIBLE).order_by("-created_at")
    user_id = request.GET.get("user")
    if user_id:
        qs = qs.filter(owner_id=user_id)
    return render(request, "ops/chat_images.html", {"images": qs[:120]})


@require_POST
@staff_required
def chat_image_delete(request, image_id):
    """删除一张聊天图片:删原图与缩略图文件,行保留并记审计。

    Args:
        request: Django 请求对象。
        image_id: 聊天图片主键。

    Returns:
        刷新后的表格局部片段。
    """
    image = get_object_or_404(ChatImage, pk=image_id)
    for field in (image.file, image.thumb):
        if field:
            default_storage.delete(field.name)
    image.status = ChatImageStatus.DELETED
    image.deleted_by = request.user
    image.deleted_at = timezone.now()
    image.save(update_fields=["status", "deleted_by", "deleted_at"])
    qs = ChatImage.objects.select_related("owner").filter(
        status=ChatImageStatus.VISIBLE).order_by("-created_at")
    return render(request, "ops/partials/chat_images_table.html", {"images": qs[:120]})
```

`chatapp/ops/urls.py` 追加:

```python
    path("chat-images/", views.chat_images, name="chat_images"),
    path("chat-images/<int:image_id>/delete", views.chat_image_delete,
         name="chat_image_delete"),
```

`_report_context(report)` 里追加(让举报详情能看证据):

```python
        "chat_images": ChatImage.objects.select_related("owner").filter(
            owner=report.target,
            created_at__gte=timezone.now() - timedelta(days=7),
        ).order_by("-created_at")[:12],
```

`chatapp/ops/templates/ops/base.html` 导航里 `photos` 那项后追加:

```html
      <a href="{% url 'ops:chat_images' %}" class="{% if '/ops/chat-images' in request.path %}active{% endif %}">
        <span>聊天图片</span>
      </a>
```

新建 `chatapp/ops/templates/ops/chat_images.html`:

```html
{% extends "ops/base.html" %}
{% block content %}
<h1>聊天图片</h1>
<p class="hint">按时间倒序展示最近 120 张正常状态的聊天图片,删除后消息里显示占位图。</p>
{% include "ops/partials/chat_images_table.html" %}
{% endblock %}
```

新建 `chatapp/ops/templates/ops/partials/chat_images_table.html`:

```html
<table id="chat-images-table">
  <thead>
    <tr><th>预览</th><th>发送者</th><th>时间</th><th>大小</th><th>操作</th></tr>
  </thead>
  <tbody>
    {% for image in images %}
    <tr>
      <td>
        <a href="{{ image.file.url }}" target="_blank" rel="noopener">
          <img src="{{ image.thumb.url }}" alt="聊天图片 {{ image.id }}" width="120">
        </a>
      </td>
      <td>{{ image.owner_id }}</td>
      <td>{{ image.created_at|date:"Y-m-d H:i" }}</td>
      <td>{{ image.bytes }}</td>
      <td>
        <form hx-post="{% url 'ops:chat_image_delete' image.id %}"
              hx-target="#chat-images-table" hx-swap="outerHTML">
          <button type="submit" class="danger">删除</button>
        </form>
      </td>
    </tr>
    {% empty %}
    <tr><td colspan="5">暂无聊天图片</td></tr>
    {% endfor %}
  </tbody>
</table>
```

`chatapp/ops/templates/ops/report_detail.html` 末尾追加:

```html
<h2>最近聊天图片</h2>
<div class="chat-images">
  {% for image in chat_images %}
    <a href="{{ image.file.url }}" target="_blank" rel="noopener">
      <img src="{{ image.thumb.url }}" alt="聊天图片 {{ image.id }}" width="120">
    </a>
  {% empty %}
    <p class="hint">该用户最近 7 天没有聊天图片</p>
  {% endfor %}
</div>
```

- [x] **Step 4: 跑测试**

Run: `cd chatapp && python manage.py test ops -v 2`
Expected: 全 PASS。

- [x] **Step 5: 提交**

```bash
git add chatapp/ops
git commit -m "feat(ops): 聊天图片抽审列表与删除"
```

---

### Task 10: 文档、全量门禁与部署核对单

**Files:**
- Modify: `docs/api/im.md`、`docs/pitfalls/im.md`、`docs/ops/imserver.md`、`docs/superpowers/plans/2026-10-20-self-hosted-im-rollout.md`、`CLAUDE.md`

**Interfaces:**
- 无新代码;把本计划交付的能力写进文档,并跑四端门禁。

- [x] **Step 1: 补接口与协议文档**

`docs/api/im.md` 在 `POST /im/user_sig` 之后新增一节(含请求/响应/错误码):

```markdown
## 上传聊天图片

> `POST` `/api/v1/im/images` · 上传一张聊天图片(自建 IM 发图前置步骤)

自建 IM(`backend=self`)发图分两步:先调本接口拿到 `url`/`thumb_url`,再把它们
放进 WS 的 `send` 帧(`kind=image`)。腾讯分支不需要调本接口。

**请求**:`multipart/form-data`,字段 `file`(jpg/png/webp,≤5MB,长边 ≤4096)。

**响应 201**:

```json
{"id": 123, "url": "https://<host>/media/chat/2026/10/7-a1b2.jpg",
 "thumb_url": "https://<host>/media/chat/2026/10/7-a1b2_thumb.jpg",
 "width": 1080, "height": 1440, "size": 345678}
```

**错误**:400(非图片 / 超 5MB / 长边超限 / 格式不支持)、403(重封禁)、429(30 次/小时)。
```

`docs/pitfalls/im.md` 追加一条自建 IM 图片坑:

```markdown
- **自建 IM 图片要两步**:先 `POST /api/v1/im/images` 拿 URL,再发 WS `send` 帧
  (`kind=image`);服务端会校验 URL 必须带 `IM_MEDIA_PREFIX` 前缀,前缀不一致直接 42201。
  部署时 `IM_MEDIA_PREFIX` 必须与 Django 的 `MEDIA_BASE_URL + /media/chat/` 一致,
  且它是**必填项**——没配 imserver 起不来。
```

`docs/ops/imserver.md` 的配置表加 `IM_MEDIA_PREFIX`(必填,示例值,与 Django 对齐的要求)。

- [x] **Step 2: 勾掉核对单并更新项目文档**

`docs/superpowers/plans/2026-10-20-self-hosted-im-rollout.md`:

- `- [ ] 图片二期已交付(否则不做全量)` → `- [x] 图片二期已交付(...)`,并在括号里写交付要点
  (上传接口 / kind=3 / 双端 sendImage / ops 抽审 / 新配置 `IM_MEDIA_PREFIX`);
- 「全量门槛」下补一条遗留:图片**无机器审核**,靠人工抽审,列为上线阻断项。

`CLAUDE.md`:

- 里程碑表追加一行 `2026-10-26 | 自建 IM 图片二期交付(...)`,写明测试数;
- 「后端接口」表补 `POST /im/images` 一行;
- 「自建 IM」纪律条目补一句 `IM_MEDIA_PREFIX` 必须与 Django 媒体前缀一致。

- [x] **Step 3: 跑四端门禁**

Run:
```
cd chatapp && python manage.py test
cd app && ../flutter/bin/flutter.bat analyze && ../flutter/bin/flutter.bat test
cd web && npm run type-check && npm run lint && npm run test:run
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test.sh
docker compose -f imserver/docker-compose.test.yml run --rm test bash /src/scripts/test_integration.sh
```
Expected: 全绿(后端测试需 Redis 容器在跑:`docker compose -f chatapp/docker-compose.dev.yml up -d`)。

- [x] **Step 4: 提交**

```bash
git add docs CLAUDE.md
git commit -m "docs(im): 图片二期接口/协议/部署文档与核对单"
```

- [ ] **Step 5: 手测清单(交付给用户)**

按顺序在模拟器 + Web 各做一遍并记录结果:

1. 7/8 两个号互发图片(缩略图先出现,点开看原图);
2. 断网发图 → 失败红叹号 → 恢复网络点重发;
3. 2 分钟内撤回图片 → 双方变灰条;
4. 重进聊天页看历史里的图片;
5. 会话列表显示 `[图片]`;
6. ops 删一张图 → 双方聊天页该图变占位;
7. 超 5MB 图片被拒并提示。

---

## 自检记录

- **Spec 覆盖**:§4 数据/接口 → Task 1–2;§4.4 注销 → Task 3;§5 协议 → Task 4–5;§6 客户端 → Task 6–8;
  §7 灰条修复 → Task 5;§8 ops → Task 9;§9 安全(前缀校验/限流)→ Task 2、4;§10 测试 → 各 Task 的 Step 1;
  §11 部署 → Task 10;§12 待办 → Task 10 文档。
- **已知取舍**:历史里已存在的灰条(`kind=1` + `{"text":desc}`)无法还原 `custom.type`,
  修复只对新消息生效,不回填旧数据。
- **命名一致性**:`ChatImageUpload`(App)/`UploadedImage`(Web)/接口字段 `url/thumb_url/width/height/size`
  三处同名同义;`SelfImageUploader`(抽象)/`ApiImageUploader`(实现)与 Web 的 `uploadImage` 注入对应。
