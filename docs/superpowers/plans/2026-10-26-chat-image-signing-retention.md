# 聊天图片签名 URL 与容量清理 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **本项目约定:内联执行,不派子 agent。**

**Goal:** 让聊天图片只能通过带有效签名的 URL 访问,并给聊天图片加 30 天保留期清理与运维用量报表。

**Architecture:** 签名 = HMAC-SHA256(共享密钥, 路径 + "\n" + 过期时间),过期时间按整点对齐 + 24h。
Django 在上传响应里签名、并提供 nginx `auth_request` 用的验签接口(生产 nginx 没编译
`secure_link`,实测只有 `auth_request`);imserver 落库存规范 URL(去 query)、在推送/历史/
会话列表里读时现签。清理走 Django 管理命令(默认 dry-run)+ 宝塔计划任务。

**Tech Stack:** Django 5.2 + DRF / C++20 + Boost.Beast + OpenSSL / MySQL / nginx(auth_request)。

## Global Constraints

- 设计文档:`docs/superpowers/specs/2026-10-26-chat-image-signing-retention-design.md`,一切取舍以它为准。
- 签名算法与共享测试向量必须两端一致:`secret="test-media-secret"`,
  `path="/media/chat/2026/10/12-abc.jpg"`,`exp=1761782400` →
  `sig=2b46b854b31a88877e318e3d12cb743fe76fccb2977e2d7ced879d7b3547d419`。
- 所有新增/修改的 `.py` 文件必须写模块 docstring + 函数/类 docstring,公开函数带参数写 `Args:`
  (`python manage.py test` 的 `CommentCoverageTests` 会拦)。
- 任何 `/api/v1` 接口的增删改,必须在同一次改动内更新 `docs/api/<分册>.md`
  (`ApiDocsCoverageTests` 双向比对)。
- 每步全绿再进下一步;提交前缀:`feat(im):` / `feat(imserver):` / `test(imserver):` / `docs(im):`。
- 后端测试前置:Redis 在跑(`docker compose -f chatapp/docker-compose.dev.yml up -d`);
  Python 用 conda 环境 `Django`(`conda run -n Django python manage.py test`)。
- 生产 nginx **没有** `secure_link` 模块,不要写 `secure_link` 指令。

---

## Task 1: Django 签名模块与配置

**Files:**
- Create: `chatapp/im/media_sign.py`
- Modify: `chatapp/config/settings.py`(在 `CHAT_IMAGE_THUMB_SIDE` 之后追加三项)
- Modify: `chatapp/.env.example`
- Test: `chatapp/im/tests.py`(新增 `MediaSignTests`)

**Interfaces:**
- Produces: `media_sign.sign_url(url: str, *, now: int | None = None) -> str`,
  `media_sign.verify(path: str, expires: str, signature: str, *, now: int | None = None) -> bool`,
  `media_sign.signature(path: str, expires: int, secret: str | None = None) -> str`,
  `media_sign.expires_at(now: int | None = None) -> int`,
  `media_sign.SIGN_PATH_PREFIX = "/media/chat/"`。
- 后续任务只用 `sign_url` / `verify` / `signature` / `SIGN_PATH_PREFIX`。

- [ ] **Step 1: 写失败测试**

在 `chatapp/im/tests.py` 末尾追加:

```python
class MediaSignTests(SimpleTestCase):
    """聊天图片签名:共享向量、过期、篡改、路径白名单、未配置密钥时的放行。"""

    def test_shared_vector_matches_imserver(self):
        self.assertEqual(
            media_sign.signature("/media/chat/2026/10/12-abc.jpg", 1761782400,
                                 secret="test-media-secret"),
            "2b46b854b31a88877e318e3d12cb743fe76fccb2977e2d7ced879d7b3547d419")

    def test_expiry_is_bucket_aligned(self):
        # 1761779999 落在 1761778800 这个整点桶里,加 24h
        with override_settings(IM_MEDIA_SIGN_TTL=86400):
            self.assertEqual(media_sign.expires_at(1761779999), 1761865200)

    def test_sign_url_replaces_existing_query(self):
        with override_settings(IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=86400):
            signed = media_sign.sign_url("http://cdn.test/media/chat/a.jpg?e=1&s=old", now=1761782400)
        self.assertTrue(signed.startswith("http://cdn.test/media/chat/a.jpg?e="))
        self.assertNotIn("s=old", signed)

    def test_verify_accepts_valid_and_rejects_tampered(self):
        with override_settings(IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=86400):
            signed = media_sign.sign_url("/media/chat/a.jpg", now=1761782400)
            query = parse_qs(urlsplit(signed).query)
            self.assertTrue(media_sign.verify("/media/chat/a.jpg", query["e"][0], query["s"][0],
                                              now=1761782400))
            self.assertFalse(media_sign.verify("/media/chat/b.jpg", query["e"][0], query["s"][0],
                                               now=1761782400))
            self.assertFalse(media_sign.verify("/media/chat/a.jpg", query["e"][0], "0" * 64,
                                               now=1761782400))

    def test_verify_rejects_expired_and_foreign_path(self):
        with override_settings(IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=60):
            signed = media_sign.sign_url("/media/chat/a.jpg", now=1761782400)
            query = parse_qs(urlsplit(signed).query)
            self.assertFalse(media_sign.verify("/media/chat/a.jpg", query["e"][0], query["s"][0],
                                               now=1761868800))
            self.assertFalse(media_sign.verify("/media/photos/a.jpg", query["e"][0],
                                               query["s"][0], now=1761782400))

    def test_disabled_secret_passes_everything(self):
        with override_settings(IM_MEDIA_SIGN_SECRET=""):
            self.assertEqual(media_sign.sign_url("/media/chat/a.jpg"), "/media/chat/a.jpg")
            self.assertTrue(media_sign.verify("/media/chat/a.jpg", "0", "bad"))
```

同时把 `chatapp/im/tests.py` 顶部 import 区补上:

```python
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase, override_settings

from . import media_sign
```

(若已有 `override_settings` 导入则只补缺的。)

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && conda run -n Django python manage.py test im.tests.MediaSignTests -v 2`
Expected: FAIL —— `ModuleNotFoundError: No module named 'im.media_sign'`

- [ ] **Step 3: 实现 `chatapp/im/media_sign.py`**

```python
"""聊天图片的限时签名 URL。

签名规则与 imserver 的 ``src/util/media_sign.cpp`` **逐字节一致**,任何一侧改算法
都必须先让两侧的共享测试向量变红:

    signing_string = path + "\\n" + str(exp)
    sig            = hmac_sha256(secret, signing_string).hexdigest()

设计要点:
    1. ``exp`` 按整点对齐(``now - now % 3600 + ttl``):同一小时内同一张图给出同一个
       URL,客户端与浏览器缓存不会因为「每次刷新历史都换 URL」而全部失效;
    2. 只签 ``/media/chat/`` 下的路径 —— 用户照片、广场图片仍走公开直出,不在此列;
    3. 密钥为空时不签名、验签恒真:本地 ``runserver`` 没有 nginx 验签,不能把开发环境
       的图片全打成 403;生产由部署核对单保证配置。
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlsplit

from django.conf import settings

SIGN_PATH_PREFIX = "/media/chat/"
BUCKET_SECONDS = 3600


def _secret() -> str:
    """当前生效的签名密钥;空串表示不签名。

    Returns:
        ``settings.IM_MEDIA_SIGN_SECRET``,未配置时为 ``""``。
    """
    return getattr(settings, "IM_MEDIA_SIGN_SECRET", "") or ""


def _ttl() -> int:
    """签名有效期(秒)。

    Returns:
        ``settings.IM_MEDIA_SIGN_TTL``,非法值回落到 86400。
    """
    try:
        return int(getattr(settings, "IM_MEDIA_SIGN_TTL", 86400) or 86400)
    except (TypeError, ValueError):
        return 86400


def expires_at(now: int | None = None) -> int:
    """按整点对齐后的过期时间戳。

    Args:
        now: 当前 Unix 秒;``None`` 表示取系统时间。

    Returns:
        过期时间戳(秒)。
    """
    moment = int(time.time() if now is None else now)
    return moment - moment % BUCKET_SECONDS + _ttl()


def path_of(url: str) -> str:
    """从绝对 URL 或相对路径里取出不含 query 的路径。

    Args:
        url: 绝对 URL 或 ``/media/...`` 形式的路径。

    Returns:
        路径部分,保证以 ``/`` 开头。
    """
    return urlsplit(url).path or "/"


def signature(path: str, expires: int, secret: str | None = None) -> str:
    """计算签名(小写 hex)。

    Args:
        path: 规范化路径,如 ``/media/chat/2026/10/x.jpg``。
        expires: 过期时间戳。
        secret: 显式密钥;``None`` 表示取配置。

    Returns:
        64 位小写十六进制签名。
    """
    key = _secret() if secret is None else secret
    message = f"{path}\n{expires}".encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()


def sign_query(path: str, *, now: int | None = None) -> str:
    """生成 ``e=..&s=..`` 查询串。

    Args:
        path: 规范化路径。
        now: 当前 Unix 秒;``None`` 表示取系统时间。

    Returns:
        查询串;未配置密钥时返回空串。
    """
    if not _secret():
        return ""
    expires = expires_at(now)
    return f"e={expires}&s={signature(path, expires)}"


def sign_url(url: str, *, now: int | None = None) -> str:
    """给 URL 加上签名 query;已有 query 会被替换。

    Args:
        url: 绝对 URL 或路径。
        now: 当前 Unix 秒;``None`` 表示取系统时间。

    Returns:
        带签名的 URL;未配置密钥时返回去掉 query 的原 URL。
    """
    clean = url.split("?", 1)[0]
    query = sign_query(path_of(clean), now=now)
    return f"{clean}?{query}" if query else clean


def verify(path: str, expires: str, signature_value: str, *, now: int | None = None) -> bool:
    """校验路径白名单、有效期与签名。

    Args:
        path: 请求的规范化路径(nginx 传来的 ``X-Original-URI`` 的 path 部分)。
        expires: 查询参数 ``e``。
        signature_value: 查询参数 ``s``。
        now: 当前 Unix 秒;``None`` 表示取系统时间。

    Returns:
        是否放行;未配置密钥时恒为 ``True``。
    """
    if not path.startswith(SIGN_PATH_PREFIX):
        return False
    if not _secret():
        return True
    try:
        moment_expires = int(expires)
    except (TypeError, ValueError):
        return False
    moment = int(time.time() if now is None else now)
    if moment_expires <= moment:
        return False
    return hmac.compare_digest(signature(path, moment_expires), signature_value or "")
```

- [ ] **Step 4: 配置三项**

`chatapp/config/settings.py` 在 `CHAT_IMAGE_THUMB_SIDE = 240` 之后追加:

```python
# --- 聊天图片签名 URL(与 imserver 的 IM_MEDIA_SIGN_* 必须一致)---
IM_MEDIA_SIGN_SECRET = os.getenv("IM_MEDIA_SIGN_SECRET", "")
IM_MEDIA_SIGN_TTL = int(os.getenv("IM_MEDIA_SIGN_TTL", "86400"))
# 聊天图片保留期(天);0 表示只清孤儿文件与删除残留
CHAT_IMAGE_RETENTION_DAYS = int(os.getenv("CHAT_IMAGE_RETENTION_DAYS", "30"))
```

`chatapp/.env.example` 在 `# MEDIA_BASE_URL=...` 之前追加:

```bash
# --- 聊天图片签名 URL(生产必填;与 imserver 的同名变量必须完全一致)---
IM_MEDIA_SIGN_SECRET=
IM_MEDIA_SIGN_TTL=86400
CHAT_IMAGE_RETENTION_DAYS=30
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd chatapp && conda run -n Django python manage.py test im.tests.MediaSignTests -v 2`
Expected: PASS(6 个用例)

- [ ] **Step 6: 提交**

```bash
git add chatapp/im/media_sign.py chatapp/im/tests.py chatapp/config/settings.py chatapp/.env.example
git commit -m "feat(im): 聊天图片签名 URL 工具与配置"
```

---

## Task 2: ChatImage 过期状态与签名属性

**Files:**
- Modify: `chatapp/im/models.py`
- Create: `chatapp/im/migrations/0002_chatimage_expired_at.py`(由 `makemigrations` 生成)
- Test: `chatapp/im/tests.py`(新增 2 个用例到 `ChatImageModelTests`)

**Interfaces:**
- Produces: `ChatImageStatus.EXPIRED`, `ChatImage.expired_at`,
  `ChatImage.signed_file_url` / `ChatImage.signed_thumb_url`(Task 3 运营台用)。

- [ ] **Step 1: 写失败测试**

在 `chatapp/im/tests.py::ChatImageModelTests` 里追加:

```python
    def test_signed_urls_are_absolute_and_signed(self):
        with override_settings(IM_MEDIA_SIGN_SECRET="s", MEDIA_BASE_URL="http://cdn.test"):
            image = ChatImage.objects.create(
                owner=self.user,
                file=SimpleUploadedFile("a.jpg", PNG_1PX, content_type="image/jpeg"),
                thumb=SimpleUploadedFile("a_thumb.jpg", PNG_1PX, content_type="image/jpeg"),
                width=10, height=20, bytes=len(PNG_1PX))
            self.assertTrue(image.signed_file_url.startswith("http://cdn.test/media/chat/"))
            self.assertIn("?e=", image.signed_file_url)
            self.assertIn("&s=", image.signed_thumb_url)

    def test_expired_status_and_timestamp_exist(self):
        image = ChatImage.objects.create(
            owner=self.user,
            file=SimpleUploadedFile("b.jpg", PNG_1PX, content_type="image/jpeg"),
            thumb=SimpleUploadedFile("b_thumb.jpg", PNG_1PX, content_type="image/jpeg"),
            width=1, height=1, bytes=len(PNG_1PX),
            status=ChatImageStatus.EXPIRED)
        self.assertIsNone(image.expired_at)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && conda run -n Django python manage.py test im.tests.ChatImageModelTests -v 2`
Expected: FAIL —— `AttributeError: 'ChatImage' object has no attribute 'signed_file_url'`

- [ ] **Step 3: 改模型**

`chatapp/im/models.py`:

```python
class ChatImageStatus(models.TextChoices):
    """聊天图片的状态。"""

    VISIBLE = "visible", "正常"
    DELETED = "deleted", "已删除"
    EXPIRED = "expired", "已过期清理"
```

在 `deleted_at` 之后加字段:

```python
    expired_at = models.DateTimeField("过期清理时间", null=True, blank=True)
```

在 `__str__` 之前加两个属性:

```python
    @property
    def signed_file_url(self) -> str:
        """运营台预览用:带签名的原图绝对地址。

        Returns:
            ``MEDIA_BASE_URL + 文件路径`` 并附签名 query。
        """
        return media_sign.sign_url(f"{settings.MEDIA_BASE_URL.rstrip('/')}{self.file.url}")

    @property
    def signed_thumb_url(self) -> str:
        """运营台预览用:带签名的缩略图绝对地址。

        Returns:
            ``MEDIA_BASE_URL + 缩略图路径`` 并附签名 query。
        """
        return media_sign.sign_url(f"{settings.MEDIA_BASE_URL.rstrip('/')}{self.thumb.url}")
```

顶部 import 增加:

```python
from . import media_sign
```

- [ ] **Step 4: 生成并检查迁移**

Run: `cd chatapp && conda run -n Django python manage.py makemigrations im`
Expected: 生成 `0002_chatimage_expired_at.py`,内容含 `AddField expired_at` 与 `AlterField status`。

Run: `cd chatapp && conda run -n Django python manage.py migrate`
Expected: `Applying im.0002... OK`

- [ ] **Step 5: 跑测试确认通过**

Run: `cd chatapp && conda run -n Django python manage.py test im.tests.ChatImageModelTests -v 2`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add chatapp/im/models.py chatapp/im/migrations/0002_chatimage_expired_at.py chatapp/im/tests.py
git commit -m "feat(im): ChatImage 增加过期状态与签名 URL 属性"
```

---

## Task 3: 上传响应签名 + 运营台预览改用签名 URL

**Files:**
- Modify: `chatapp/im/views.py::upload_image`
- Modify: `chatapp/ops/templates/ops/partials/chat_images_table.html`
- Test: `chatapp/im/tests.py::ChatImageUploadTests`

**Interfaces:**
- Consumes: `media_sign.sign_url`(Task 1)、`ChatImage.signed_*_url`(Task 2)。
- Produces: 上传响应 `url` / `thumb_url` 为签名 URL(客户端协议不变)。

- [ ] **Step 1: 写失败测试**

把 `ChatImageUploadTests.setUp` 的 `override` 改成同时覆盖密钥:

```python
        override = self.settings(MEDIA_ROOT=self.media_dir, MEDIA_BASE_URL="http://cdn.test",
                                 IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=86400)
```

把 `test_upload_returns_urls_and_dimensions` 里的两行断言改成:

```python
        self.assertTrue(data["url"].startswith("http://cdn.test/media/chat/"))
        self.assertIn("?e=", data["url"])
        self.assertIn("&s=", data["url"])
        thumb_path = urlsplit(data["thumb_url"]).path
        self.assertTrue(thumb_path.endswith("_thumb.jpg"))
        self.assertIn("&s=", data["thumb_url"])
```

新增一个用例:

```python
    def test_uploaded_url_verifies_with_auth_helper(self):
        data = self.upload().data
        parts = urlsplit(data["url"])
        query = parse_qs(parts.query)
        self.assertTrue(media_sign.verify(parts.path, query["e"][0], query["s"][0]))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && conda run -n Django python manage.py test im.tests.ChatImageUploadTests -v 2`
Expected: FAIL —— `AssertionError: '?e=' not found in 'http://cdn.test/media/chat/...jpg'`

- [ ] **Step 3: 上传响应改为签名 URL**

`chatapp/im/views.py::upload_image` 的返回段替换为:

```python
    base = settings.MEDIA_BASE_URL.rstrip("/")
    return Response({
        "id": chat_image.id,
        "url": media_sign.sign_url(f"{base}{chat_image.file.url}"),
        "thumb_url": media_sign.sign_url(f"{base}{chat_image.thumb.url}"),
        "width": chat_image.width,
        "height": chat_image.height,
        "size": chat_image.bytes,
    }, status=201)
```

顶部 import 增加:

```python
from . import media_sign
```

- [ ] **Step 4: 运营台模板改用签名 URL**

`chatapp/ops/templates/ops/partials/chat_images_table.html` 中:

```html
        <a href="{{ image.signed_file_url }}" target="_blank" rel="noopener">
          <img src="{{ image.signed_thumb_url }}" alt="聊天图片 {{ image.id }}" width="120">
        </a>
```

- [ ] **Step 5: 跑测试确认通过**

Run: `cd chatapp && conda run -n Django python manage.py test im.tests.ChatImageUploadTests ops -v 2`
Expected: PASS(含既有 ops 抽审用例)

- [ ] **Step 6: 提交**

```bash
git add chatapp/im/views.py chatapp/im/tests.py chatapp/ops/templates/ops/partials/chat_images_table.html
git commit -m "feat(im): 上传响应与运营台预览改用签名 URL"
```

---

## Task 4: 验签接口(nginx auth_request)

**Files:**
- Modify: `chatapp/im/views.py`(新增 `image_auth`)
- Modify: `chatapp/im/urls.py`
- Modify: `docs/api/im.md`(新增 6.3 节)
- Test: `chatapp/im/tests.py`(新增 `ChatImageAuthTests`)

**Interfaces:**
- Produces: `GET /api/v1/im/images/auth`,读请求头 `X-Original-URI`,
  通过 204、拒绝 403 + `{"code":403,"message":"图片链接已失效"}`。

- [ ] **Step 1: 写失败测试**

在 `chatapp/im/tests.py` 追加:

```python
class ChatImageAuthTests(APITestCase):
    """nginx 子请求验签:有效 204、缺头/过期/篡改 403、无需 JWT。"""

    def setUp(self):
        self.url = "/api/v1/im/images/auth"
        self.media = "/media/chat/2026/10/12-abc.jpg"

    def auth(self, original):
        return self.client.get(self.url, HTTP_X_ORIGINAL_URI=original)

    def signed(self):
        with override_settings(IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=86400):
            return media_sign.sign_url(self.media, now=int(time.time()))

    def test_valid_signature_passes_without_jwt(self):
        self.assertEqual(self.auth(self.signed()).status_code, 204)

    def test_missing_header_is_forbidden(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], 403)

    def test_expired_signature_is_forbidden(self):
        with override_settings(IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=60):
            stale = media_sign.sign_url(self.media, now=1)
        self.assertEqual(self.auth(stale).status_code, 403)

    def test_non_chat_path_is_forbidden(self):
        with override_settings(IM_MEDIA_SIGN_SECRET="s"):
            signed = media_sign.sign_url("/media/photos/a.jpg", now=int(time.time()))
        self.assertEqual(self.auth(signed).status_code, 403)

    def test_heavy_banned_user_can_still_view(self):
        user = User.objects.create_user(phone="13900139009")
        profile = get_profile(user)
        profile.status = ProfileStatus.BANNED_HEAVY
        profile.save(update_fields=["status"])
        self.assertEqual(self.auth(self.signed()).status_code, 204)
```

顶部补 `import time`(若无)。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && conda run -n Django python manage.py test im.tests.ChatImageAuthTests -v 2`
Expected: FAIL —— 404(路由不存在)

- [ ] **Step 3: 实现视图**

`chatapp/im/views.py` 追加(放在 `upload_image` 之后):

```python
@api_view(["GET"])
@authentication_classes([])
@permission_classes([AllowAny])
def image_auth(request):
    """nginx ``auth_request`` 子请求:校验聊天图片签名(GET /api/v1/im/images/auth)。

    这条路径**不校验登录态**:nginx 的内部子请求不会带 Authorization,而图片本身
    已经是「谁拿到链接谁能看」的语义,靠签名与有效期兜底。

    Args:
        request: DRF 请求对象,nginx 通过 ``X-Original-URI`` 传入原始 URI
            (含 ``?e=&s=``)。

    Returns:
        通过返回 204;缺头、路径不在 ``/media/chat/`` 下、过期或签名不符返回 403。
    """
    original = request.headers.get("X-Original-URI", "")
    parts = urlsplit(original)
    query = parse_qs(parts.query)
    expires = (query.get("e") or [""])[0]
    signature_value = (query.get("s") or [""])[0]
    if not original or not media_sign.verify(parts.path, expires, signature_value):
        return Response({"code": 403, "message": "图片链接已失效"}, status=403)
    return Response(status=204)
```

顶部 import 增加:

```python
from urllib.parse import parse_qs, urlsplit

from rest_framework.decorators import api_view, authentication_classes, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
```

- [ ] **Step 4: 挂路由**

`chatapp/im/urls.py` 的 `urlpatterns` 改为:

```python
urlpatterns = [
    path("user_sig", views.user_sig),
    path("images", views.upload_image),
    path("images/auth", views.image_auth),
]
```

- [ ] **Step 5: 补接口文档**

`docs/api/im.md` 在 6.2 之后新增一节:

````markdown
---

### 6.3 聊天图片验签(nginx 内部)

> `GET` `/api/v1/im/images/auth` · 无需鉴权 · 无额外限流

**接口描述**

生产 nginx 对 `/media/chat/` 的请求先做一次内部子请求(`auth_request`),由本接口
校验 URL 上的签名与有效期:通过返回 204(nginx 放行静态文件),失败返回 403。
**不是给客户端调的**:请求头 `X-Original-URI` 由 nginx 注入,客户端直接调用只会拿到 403。

- 签名规则:`HMAC-SHA256(IM_MEDIA_SIGN_SECRET, path + "\n" + e)`,小写 hex
- 有效期:`e` 为过期时间戳,由服务端按整点对齐 + `IM_MEDIA_SIGN_TTL`(默认 24h)生成
- 只接受 `/media/chat/` 下的路径;用户照片与广场图片不在此列

**请求参数**(请求头)

| 参数名称 | 类型 | 必填 | 描述 |
|----------|------|------|------|
| X-Original-URI | String | 是 | 原始 URI,形如 `/media/chat/2026/10/7-a1b2.jpg?e=1761782400&s=...` |

**响应参数**

通过:HTTP 204,无响应体。

**错误码**

| 错误码 | HTTP | 描述 | 处理建议 |
|--------|------|------|----------|
| 403 | 403 | 缺 `X-Original-URI` / 路径越界 / 已过期 / 签名不符 | 重新进入聊天页刷新历史以拿到新链接 |
````

- [ ] **Step 6: 跑测试确认通过**

Run: `cd chatapp && conda run -n Django python manage.py test im.tests.ChatImageAuthTests config.tests.ApiDocsCoverageTests -v 2`
Expected: PASS

- [ ] **Step 7: 提交**

```bash
git add chatapp/im/views.py chatapp/im/urls.py chatapp/im/tests.py docs/api/im.md
git commit -m "feat(im): 聊天图片验签接口(nginx auth_request)"
```

---

## Task 5: `im_media_cleanup` 清理命令

**Files:**
- Create: `chatapp/im/management/commands/im_media_cleanup.py`
- Test: `chatapp/im/tests.py`(新增 `ChatImageCleanupTests`)

**Interfaces:**
- Consumes: `ChatImageStatus.EXPIRED`、`ChatImage.expired_at`(Task 2)。
- Produces: `manage.py im_media_cleanup [--apply] [--retention-days N] [--orphan-hours N] [--batch-size N]`。

- [ ] **Step 1: 写失败测试**

```python
class ChatImageCleanupTests(TestCase):
    """清理命令:保留期删文件并改状态、默认 dry-run、孤儿文件按 mtime、删除残留补删。"""

    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir, CHAT_IMAGE_RETENTION_DAYS=30)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(phone="13900139003")

    def make_image(self, name="a.jpg", days_old=0, status=ChatImageStatus.VISIBLE):
        image = ChatImage.objects.create(
            owner=self.user,
            file=SimpleUploadedFile(name, PNG_1PX, content_type="image/jpeg"),
            thumb=SimpleUploadedFile(name.replace(".jpg", "_thumb.jpg"), PNG_1PX,
                                     content_type="image/jpeg"),
            width=1, height=1, bytes=len(PNG_1PX), status=status)
        ChatImage.objects.filter(pk=image.pk).update(
            created_at=timezone.now() - timedelta(days=days_old))
        image.refresh_from_db()
        return image

    def run_cleanup(self, *args):
        out = StringIO()
        call_command("im_media_cleanup", *args, stdout=out)
        return out.getvalue()

    def test_retention_removes_files_and_marks_expired(self):
        image = self.make_image(days_old=31)
        names = (image.file.name, image.thumb.name)
        self.run_cleanup("--apply")
        image.refresh_from_db()
        self.assertEqual(image.status, ChatImageStatus.EXPIRED)
        self.assertIsNotNone(image.expired_at)
        for name in names:
            self.assertFalse(default_storage.exists(name))

    def test_dry_run_keeps_files(self):
        image = self.make_image(days_old=31)
        output = self.run_cleanup()
        image.refresh_from_db()
        self.assertEqual(image.status, ChatImageStatus.VISIBLE)
        self.assertTrue(default_storage.exists(image.file.name))
        self.assertIn("dry-run", output)

    def test_fresh_image_is_kept(self):
        image = self.make_image(days_old=1)
        self.run_cleanup("--apply")
        image.refresh_from_db()
        self.assertEqual(image.status, ChatImageStatus.VISIBLE)

    def test_orphan_file_is_deleted_after_grace(self):
        orphan_dir = Path(self.media_dir) / "chat" / "2026" / "10"
        orphan_dir.mkdir(parents=True)
        orphan = orphan_dir / "999-dead.jpg"
        orphan.write_bytes(PNG_1PX)
        old = time.time() - 48 * 3600
        os.utime(orphan, (old, old))
        self.run_cleanup("--apply")
        self.assertFalse(orphan.exists())

    def test_recent_orphan_is_kept(self):
        orphan_dir = Path(self.media_dir) / "chat" / "2026" / "10"
        orphan_dir.mkdir(parents=True)
        orphan = orphan_dir / "999-live.jpg"
        orphan.write_bytes(PNG_1PX)
        self.run_cleanup("--apply")
        self.assertTrue(orphan.exists())

    def test_deleted_row_leftover_file_is_removed(self):
        image = self.make_image(status=ChatImageStatus.DELETED)
        self.run_cleanup("--apply")
        self.assertFalse(default_storage.exists(image.file.name))

    def test_zero_retention_skips_retention_pass(self):
        image = self.make_image(days_old=365)
        self.run_cleanup("--apply", "--retention-days", "0")
        image.refresh_from_db()
        self.assertEqual(image.status, ChatImageStatus.VISIBLE)
```

顶部 import 补:

```python
import os
from io import StringIO
from pathlib import Path

from django.core.files.storage import default_storage
from django.core.management import call_command
from django.utils import timezone
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && conda run -n Django python manage.py test im.tests.ChatImageCleanupTests -v 2`
Expected: FAIL —— `CommandError: Unknown command: 'im_media_cleanup'`

- [ ] **Step 3: 实现命令**

```python
"""清理聊天图片:保留期、孤儿文件、删除残留。

默认 dry-run(只打印将要删除的内容),``--apply`` 才真正删文件 —— 删文件不可逆,
定时任务必须显式带 ``--apply``。

三类动作互相独立:
    1. 保留期:可见且早于保留期的图片 → 删原图/缩略图,行改 ``expired``;
    2. 孤儿文件:磁盘上有、库里没有对应行、且 mtime 早于宽限期的文件;
    3. 删除残留:行已 ``deleted`` 但文件还在(上次存储删除失败)→ 补删。
"""

import os
import time
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management.base import BaseCommand
from django.utils import timezone

from im.models import ChatImage, ChatImageStatus

CHAT_DIR = "chat"


class Command(BaseCommand):
    """清理聊天图片的磁盘占用(默认 dry-run)。"""

    help = "清理聊天图片:保留期过期、孤儿文件、删除残留(默认 dry-run,--apply 才删)"

    def add_arguments(self, parser):
        """注册命令行参数。

        Args:
            parser: argparse 解析器。
        """
        parser.add_argument("--apply", action="store_true", help="真正删除;默认只打印")
        parser.add_argument("--retention-days", type=int, default=None,
                            help="保留期(天);默认取 CHAT_IMAGE_RETENTION_DAYS,0 表示不清理")
        parser.add_argument("--orphan-hours", type=int, default=24,
                            help="孤儿文件的宽限期(小时);0 表示不扫孤儿文件")
        parser.add_argument("--batch-size", type=int, default=200, help="每批处理的行数")

    def handle(self, *args, **options):
        """执行三类清理并打印汇总。

        Args:
            *args: 位置参数(未使用)。
            **options: 命令行选项。

        Returns:
            None。
        """
        apply = bool(options["apply"])
        retention_days = options["retention_days"]
        if retention_days is None:
            retention_days = getattr(settings, "CHAT_IMAGE_RETENTION_DAYS", 30)
        batch_size = max(int(options["batch_size"]), 1)

        mode = "apply" if apply else "dry-run"
        self.stdout.write(f"[im_media_cleanup] mode={mode}")

        expired = self._expire_old(retention_days, batch_size, apply)
        removed_files = self._delete_leftovers(batch_size, apply)
        orphans = self._delete_orphans(int(options["orphan_hours"]), apply)
        self.stdout.write(
            f"保留期({retention_days} 天):{expired} 张;"
            f"删除残留:{removed_files} 个文件;孤儿文件:{orphans} 个")
        if not apply:
            self.stdout.write("dry-run:未删除任何文件,确认无误后加 --apply")

    def _expire_old(self, retention_days: int, batch_size: int, apply: bool) -> int:
        """把早于保留期的可见图片删文件并标记过期。

        Args:
            retention_days: 保留天数;``0`` 表示跳过。
            batch_size: 每批处理行数。
            apply: 是否真正删除。

        Returns:
            处理的图片数量。
        """
        if retention_days <= 0:
            return 0
        cutoff = timezone.now() - timedelta(days=retention_days)
        total = 0
        while True:
            rows = list(ChatImage.objects.filter(
                status=ChatImageStatus.VISIBLE, created_at__lt=cutoff
            ).order_by("id")[:batch_size])
            if not rows:
                return total
            for image in rows:
                if apply:
                    self._delete_files(image)
                    image.status = ChatImageStatus.EXPIRED
                    image.expired_at = timezone.now()
                    image.save(update_fields=["status", "expired_at"])
            total += len(rows)

    def _delete_leftovers(self, batch_size: int, apply: bool) -> int:
        """补删「行已删除但文件还在」的残留文件。

        Args:
            batch_size: 每批处理行数。
            apply: 是否真正删除。

        Returns:
            处理的文件数量。
        """
        total = 0
        for image in ChatImage.objects.filter(status=ChatImageStatus.DELETED).iterator(
                chunk_size=batch_size):
            if self._delete_files(image, apply=apply):
                total += 1
        return total

    def _delete_orphans(self, orphan_hours: int, apply: bool) -> int:
        """删除磁盘上没有数据库行、且超过宽限期的聊天图片文件。

        Args:
            orphan_hours: 宽限期(小时);``0`` 表示跳过。
            apply: 是否真正删除。

        Returns:
            删除(或将要删除)的文件数量。
        """
        if orphan_hours <= 0:
            return 0
        root = Path(settings.MEDIA_ROOT) / CHAT_DIR
        if not root.exists():
            return 0
        known = set(ChatImage.objects.values_list("file", flat=True))
        known |= set(ChatImage.objects.values_list("thumb", flat=True))
        cutoff = time.time() - orphan_hours * 3600
        total = 0
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            name = path.relative_to(settings.MEDIA_ROOT).as_posix()
            if name in known or path.stat().st_mtime > cutoff:
                continue
            total += 1
            if apply:
                path.unlink(missing_ok=True)
        return total

    def _delete_files(self, image: ChatImage, apply: bool = True) -> bool:
        """删除一张图片的原图与缩略图文件。

        Args:
            image: 聊天图片行。
            apply: 是否真正删除。

        Returns:
            是否至少有一个文件存在(即「本来需要删」)。
        """
        existed = False
        for field in (image.file, image.thumb):
            if not field:
                continue
            try:
                if not default_storage.exists(field.name):
                    continue
                existed = True
                if apply:
                    default_storage.delete(field.name)
            except Exception:
                self.stderr.write(f"删除失败: {field.name}")
        return existed
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && conda run -n Django python manage.py test im.tests.ChatImageCleanupTests -v 2`
Expected: PASS(7 个用例)

- [ ] **Step 5: 提交**

```bash
git add chatapp/im/management/commands/im_media_cleanup.py chatapp/im/tests.py
git commit -m "feat(im): 聊天图片清理命令(保留期/孤儿/残留,dry-run 默认)"
```

---

## Task 6: `im_media_stats` 用量报表

**Files:**
- Create: `chatapp/im/management/commands/im_media_stats.py`
- Test: `chatapp/im/tests.py`(新增 `ChatImageStatsTests`)

**Interfaces:**
- Produces: `manage.py im_media_stats`(只读,无参数)。

- [ ] **Step 1: 写失败测试**

```python
class ChatImageStatsTests(TestCase):
    """用量报表:打印各状态条数、字节数与磁盘文件数。"""

    def test_reports_status_counts_and_disk(self):
        media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_dir, ignore_errors=True)
        with self.settings(MEDIA_ROOT=media_dir):
            user = User.objects.create_user(phone="13900139004")
            ChatImage.objects.create(
                owner=user,
                file=SimpleUploadedFile("s.jpg", PNG_1PX, content_type="image/jpeg"),
                thumb=SimpleUploadedFile("s_thumb.jpg", PNG_1PX, content_type="image/jpeg"),
                width=1, height=1, bytes=len(PNG_1PX))
            out = StringIO()
            call_command("im_media_stats", stdout=out)
        text = out.getvalue()
        self.assertIn("visible=1", text)
        self.assertIn("磁盘文件=2", text)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd chatapp && conda run -n Django python manage.py test im.tests.ChatImageStatsTests -v 2`
Expected: FAIL —— `Unknown command: 'im_media_stats'`

- [ ] **Step 3: 实现命令**

```python
"""聊天图片用量报表:各状态条数/字节、磁盘占用与剩余空间、Top 发送者。"""

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.models import Count, Sum

from im.models import ChatImage

CHAT_DIR = "chat"


class Command(BaseCommand):
    """打印聊天图片的数据库与磁盘用量(只读)。"""

    help = "聊天图片用量报表:各状态条数/字节、磁盘占用与剩余空间、Top 5 发送者"

    def handle(self, *args, **options):
        """收集并打印用量信息。

        Args:
            *args: 位置参数(未使用)。
            **options: 命令行选项(未使用)。

        Returns:
            None。
        """
        root = Path(settings.MEDIA_ROOT) / CHAT_DIR
        files = [path for path in root.rglob("*") if path.is_file()] if root.exists() else []
        disk_bytes = sum(path.stat().st_size for path in files)

        for row in ChatImage.objects.values("status").annotate(
                count=Count("id"), total=Sum("bytes")).order_by("status"):
            self.stdout.write(
                f"{row['status']}={row['count']} 字节={row['total'] or 0}")

        usage = shutil.disk_usage(settings.MEDIA_ROOT)
        self.stdout.write(f"磁盘文件={len(files)} 磁盘字节={disk_bytes}")
        self.stdout.write(
            f"分区:总={usage.total // (1024 * 1024)}MB "
            f"已用={usage.used // (1024 * 1024)}MB "
            f"剩余={usage.free // (1024 * 1024)}MB")

        top = ChatImage.objects.values("owner_id").annotate(
            count=Count("id"), total=Sum("bytes")).order_by("-total")[:5]
        for row in top:
            self.stdout.write(
                f"top owner={row['owner_id']} 张数={row['count']} 字节={row['total'] or 0}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd chatapp && conda run -n Django python manage.py test im.tests.ChatImageStatsTests -v 2`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add chatapp/im/management/commands/im_media_stats.py chatapp/im/tests.py
git commit -m "feat(im): 聊天图片用量报表命令"
```

---

## Task 7: imserver 签名工具与配置

**Files:**
- Create: `imserver/src/util/media_sign.h`、`imserver/src/util/media_sign.cpp`
- Modify: `imserver/src/config.h`、`imserver/src/config.cpp`
- Modify: `imserver/src/service/message_service.h`、`imserver/src/service/message_service.cpp`(仅构造与成员)
- Modify: `imserver/CMakeLists.txt`(加入新源文件)
- Test: `imserver/tests/media_sign_test.cpp`、`imserver/tests/CMakeLists.txt`

**Interfaces:**
- Produces: `class MediaSigner`(`sign_image`, `sign_url`, `canonical`, `path_prefix`, `enabled`)、
  `Config::media_sign_secret`、`Config::media_sign_ttl`、
  `MessageService::signer() const -> const MediaSigner&`。

- [ ] **Step 1: 写失败测试**

`imserver/tests/media_sign_test.cpp`:

```cpp
#include <gtest/gtest.h>

#include "util/media_sign.h"

TEST(MediaSignerTest, MatchesSharedVector) {
  // 与 Django im/media_sign.py 的共享测试向量必须一致
  MediaSigner signer("test-media-secret", 86400, "http://cdn/media/chat/");
  const auto signed_url =
      signer.sign_url("http://cdn/media/chat/2026/10/12-abc.jpg", 1761782400);
  EXPECT_EQ(signed_url,
            "http://cdn/media/chat/2026/10/12-abc.jpg?e=1761868800&s="
            "b57407845446ea5b208d43263f9b8d1a404ee807c8f77aeadaf02d6ab8aba718");
}

TEST(MediaSignerTest, CanonicalStripsQueryAndRejectsForeignUrl) {
  MediaSigner signer("s", 86400, "http://cdn/media/chat/");
  EXPECT_EQ(signer.canonical("http://cdn/media/chat/a.jpg?e=1&s=2"),
            std::optional<std::string>("http://cdn/media/chat/a.jpg"));
  EXPECT_FALSE(signer.canonical("http://evil/a.jpg").has_value());
}

TEST(MediaSignerTest, DisabledSignerLeavesUrlUntouched) {
  MediaSigner signer("", 86400, "http://cdn/media/chat/");
  EXPECT_FALSE(signer.enabled());
  const auto url = "http://cdn/media/chat/a.jpg";
  EXPECT_EQ(signer.sign_url(url, 1761782400), url);
}

TEST(MediaSignerTest, SignsImageObjectInPlace) {
  MediaSigner signer("test-media-secret", 86400, "http://cdn/media/chat/");
  nlohmann::json image = {{"url", "http://cdn/media/chat/a.jpg?e=1&s=old"},
                          {"thumb_url", "http://cdn/media/chat/a_thumb.jpg"}};
  signer.sign_image(image, 1761782400);
  EXPECT_EQ(image["url"].get<std::string>().find("s=old"), std::string::npos);
  EXPECT_NE(image["thumb_url"].get<std::string>().find("?e="), std::string::npos);
}
```

`imserver/tests/CMakeLists.txt` 把 `media_sign_test.cpp` 加进 `im_unit_tests`。

- [ ] **Step 2: 跑测试确认失败**

Run: `cd imserver && docker compose -f docker-compose.test.yml run --rm test bash /src/scripts/test.sh`
Expected: 编译失败 —— `util/media_sign.h: No such file or directory`

- [ ] **Step 3: 实现头文件**

`imserver/src/util/media_sign.h`:

```cpp
#pragma once
#include <cstdint>
#include <nlohmann/json.hpp>
#include <optional>
#include <string>

// 聊天图片的限时签名:与 Django 的 im/media_sign.py 逐字节一致。
//
// 签名串 = path + "\n" + exp;签名 = HMAC-SHA256(secret, 签名串) 的小写 hex。
// exp 按整点对齐(now - now % 3600 + ttl),保证同一小时内同一张图给出同一个 URL。
class MediaSigner {
 public:
  MediaSigner(std::string secret, int ttl, std::string media_prefix);

  // 是否启用签名(密钥为空 = 不签,开发环境)
  bool enabled() const { return !secret_.empty(); }
  // IM_MEDIA_PREFIX 的路径部分(如 /media/chat/),用于从绝对 URL 里取 path
  const std::string& path_prefix() const { return path_prefix_; }

  // 去掉 query 并校验属于 media_prefix;不合法返回 nullopt
  std::optional<std::string> canonical(const std::string& url) const;

  // 给 URL 加 ?e=&s=(先规范化);未启用时原样返回
  std::string sign_url(const std::string& url, int64_t now = 0) const;

  // 就地给 image 对象的 url / thumb_url 签名
  void sign_image(nlohmann::json& image, int64_t now = 0) const;

 private:
  std::string secret_;
  std::string media_prefix_;
  std::string path_prefix_;
  int ttl_;
};
```

- [ ] **Step 4: 实现源文件**

`imserver/src/util/media_sign.cpp`:

```cpp
#include "util/media_sign.h"

#include <chrono>

#include "util/hmac.h"

namespace {

int64_t now_seconds() {
  return std::chrono::duration_cast<std::chrono::seconds>(
             std::chrono::system_clock::now().time_since_epoch())
      .count();
}

// 从 "http://host/media/chat/" 里取出 "/media/chat/"
std::string path_prefix_of(const std::string& media_prefix) {
  const auto scheme = media_prefix.find("://");
  const auto start = scheme == std::string::npos ? 0 : scheme + 3;
  const auto slash = media_prefix.find('/', start);
  return slash == std::string::npos ? media_prefix : media_prefix.substr(slash);
}

}  // namespace

MediaSigner::MediaSigner(std::string secret, int ttl, std::string media_prefix)
    : secret_(std::move(secret)),
      media_prefix_(std::move(media_prefix)),
      path_prefix_(path_prefix_of(media_prefix_)),
      ttl_(ttl > 0 ? ttl : 86400) {}

std::optional<std::string> MediaSigner::canonical(const std::string& url) const {
  const auto clean = url.substr(0, url.find('?'));
  if (media_prefix_.empty() || clean.rfind(media_prefix_, 0) != 0) {
    return std::nullopt;
  }
  return clean;
}

std::string MediaSigner::sign_url(const std::string& url, int64_t now) const {
  const auto clean = canonical(url);
  if (!clean.has_value() || !enabled()) {
    return url;
  }
  const auto path_at = clean->find(path_prefix_);
  if (path_at == std::string::npos) {
    return url;
  }
  const auto path = clean->substr(path_at);
  const int64_t moment = now > 0 ? now : now_seconds();
  const int64_t expires = moment - moment % 3600 + ttl_;
  const auto signature =
      hmac_sha256_hex(secret_, path + "\n" + std::to_string(expires));
  return *clean + "?e=" + std::to_string(expires) + "&s=" + signature;
}

void MediaSigner::sign_image(nlohmann::json& image, int64_t now) const {
  if (!enabled() || !image.is_object()) {
    return;
  }
  for (const char* key : {"url", "thumb_url"}) {
    if (!image.contains(key) || !image[key].is_string()) {
      continue;
    }
    image[key] = sign_url(image[key].get<std::string>(), now);
  }
}
```

`imserver/CMakeLists.txt` 的 `imcore` 源文件列表加 `src/util/media_sign.cpp`。

- [ ] **Step 5: 配置解析**

`imserver/src/config.h` 在 `media_prefix` 之后加:

```cpp
  // 聊天图片签名密钥与有效期;密钥为空 = 不签名(仅开发环境)
  std::string media_sign_secret;
  int media_sign_ttl = 86400;
```

`imserver/src/config.cpp::from_map` 在 `cfg.media_prefix = ...` 之后加:

```cpp
  cfg.media_sign_secret = get_or(env, "IM_MEDIA_SIGN_SECRET");
  cfg.media_sign_ttl = get_int(env, "IM_MEDIA_SIGN_TTL", cfg.media_sign_ttl);
```

`from_env` 的白名单数组补 `"IM_MEDIA_SIGN_SECRET"`, `"IM_MEDIA_SIGN_TTL"`。

- [ ] **Step 6: MessageService 持有 signer**

`imserver/src/service/message_service.h`:

```cpp
#include "util/media_sign.h"
...
  MessageService(MysqlPool& pool, UserRepo& users, ConversationRepo& conversations,
                 MessageRepo& messages, BlacklistRepo& blacklist,
                 std::size_t text_max = 2000, std::string media_prefix = "",
                 std::string media_sign_secret = "", int media_sign_ttl = 86400);
...
  const MediaSigner& signer() const { return signer_; }
...
  std::string media_prefix_;
  MediaSigner signer_;
```

`imserver/src/service/message_service.cpp` 构造函数:

```cpp
MessageService::MessageService(MysqlPool& pool, UserRepo& users,
                               ConversationRepo& conversations, MessageRepo& messages,
                               BlacklistRepo& blacklist, std::size_t text_max,
                               std::string media_prefix, std::string media_sign_secret,
                               int media_sign_ttl)
    : pool_(pool),
      users_(users),
      conversations_(conversations),
      messages_(messages),
      blacklist_(blacklist),
      text_max_(text_max),
      media_prefix_(std::move(media_prefix)),
      signer_(std::move(media_sign_secret), media_sign_ttl, media_prefix_) {
```

`src/main.cpp` 构造 `MessageService` 时把 `cfg.media_sign_secret, cfg.media_sign_ttl` 传进去。

- [ ] **Step 7: 跑单测确认通过**

Run: `cd imserver && docker compose -f docker-compose.test.yml run --rm test bash /src/scripts/test.sh`
Expected: PASS(含新增 4 个 `MediaSignerTest`)

- [ ] **Step 8: 提交**

```bash
git add imserver/src/util/media_sign.h imserver/src/util/media_sign.cpp imserver/CMakeLists.txt \
        imserver/src/config.h imserver/src/config.cpp imserver/src/service/message_service.h \
        imserver/src/service/message_service.cpp imserver/src/main.cpp \
        imserver/tests/media_sign_test.cpp imserver/tests/CMakeLists.txt
git commit -m "feat(imserver): 聊天图片签名工具与配置"
```

---

## Task 8: imserver 写时规范化 + 读时签名

**Files:**
- Modify: `imserver/src/service/message_service.cpp::send`(kind=3 分支)
- Modify: `imserver/src/net/frames.h`、`imserver/src/net/ws_server.cpp`、`imserver/src/net/http_api.cpp`
- Modify: `imserver/docker-compose.test.yml`(加签名环境变量)
- Test: `imserver/tests/integration/test_image.py`、`imserver/scripts/test_http.sh`

**Interfaces:**
- Consumes: `MediaSigner`(Task 7)、`MessageService::signer()`。
- Produces: 历史/会话 `last_message`/WS 推送里的 `image.url`、`image.thumb_url` 均带 `?e=&s=`;
  落库 body 无 query。

- [ ] **Step 1: 写失败测试**

`imserver/tests/integration/test_image.py`:

```python
"""图片消息:落库存规范 URL、推送与历史里读时签名、签名可被独立复算。"""

import asyncio
import hashlib
import hmac
import json
import os
import time
import urllib.request
from urllib.parse import parse_qs, urlsplit

import jwt
import websockets

SECRET = os.environ["IM_JWT_SECRET"]
SIGN_SECRET = os.environ["IM_MEDIA_SIGN_SECRET"]
MEDIA_PREFIX = os.environ["IM_MEDIA_PREFIX"]
WS = os.environ.get("IM_TEST_WS", "ws://127.0.0.1:19100/im/ws")
HTTP = os.environ.get("IM_TEST_HTTP", "http://127.0.0.1:19101/im/api")


def token(uid: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {"sub": f"u{uid}", "uid": uid, "iat": now, "exp": now + 3600, "jti": "test"},
        SECRET,
        algorithm="HS256",
    )


def get(path: str, uid: int):
    request = urllib.request.Request(
        HTTP + path, headers={"Authorization": f"Bearer {token(uid)}"}
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        return json.loads(response.read())


async def auth(uid: int):
    ws = await websockets.connect(WS)
    await ws.send(json.dumps({"v": 1, "type": "auth", "data": {"token": token(uid)}}))
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == "auth_ok":
            return ws


async def recv(ws, type_):
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 3))
        if message["type"] == type_:
            return message


def assert_signed(url: str) -> None:
    parts = urlsplit(url)
    query = parse_qs(parts.query)
    expires = int(query["e"][0])
    expected = hmac.new(
        SIGN_SECRET.encode(), f"{parts.path}\n{expires}".encode(), hashlib.sha256
    ).hexdigest()
    assert query["s"][0] == expected, (url, expected)
    assert expires > time.time()


async def main():
    base = 300000 + (int(time.time() * 1000) + os.getpid()) % 100000
    sender_uid, receiver_uid = base, base + 1
    sender = await auth(sender_uid)
    receiver = await auth(receiver_uid)
    image = {
        "url": MEDIA_PREFIX + "2026/10/12-abc.jpg?e=1&s=stale",
        "thumb_url": MEDIA_PREFIX + "2026/10/12-abc_thumb.jpg",
        "width": 100,
        "height": 200,
        "size": 1024,
    }
    await sender.send(json.dumps({
        "v": 1, "type": "send", "id": "img-1",
        "data": {"to": f"u{receiver_uid}", "kind": "image", "image": image},
    }))
    pushed = await recv(receiver, "message")
    assert_signed(pushed["data"]["image"]["url"])
    assert_signed(pushed["data"]["image"]["thumb_url"])
    assert "stale" not in pushed["data"]["image"]["url"]

    history = get(f"/messages?peer=u{sender_uid}&limit=50", receiver_uid)["items"]
    assert_signed(history[0]["image"]["url"])
    assert history[0]["image"]["url"].count("?") == 1

    conversations = get("/conversations", receiver_uid)["items"]
    assert_signed(conversations[0]["last_message"]["image"]["url"])

    await sender.close()
    await receiver.close()


asyncio.run(main())
```

`imserver/scripts/test_http.sh` 在 `test_internal.py` 之后加:

```bash
python3 /src/tests/integration/test_image.py
```

`imserver/docker-compose.test.yml` 的 `test.environment` 加:

```yaml
      IM_MEDIA_SIGN_SECRET: test-media-secret
      IM_MEDIA_SIGN_TTL: "86400"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd imserver && docker compose -f docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh`
Expected: FAIL —— `assert_signed` 断言失败(URL 里没有 `e/s`)

- [ ] **Step 3: 写时规范化**

`imserver/src/service/message_service.cpp::send` 的 kind=3 分支替换为:

```cpp
    } else if (request.kind == 3) {
      // 图片只接受本服务媒体前缀下的 URL,并落**规范 URL**(去掉 query):
      // 客户端带上来的签名是上传那一刻的,存下来会在过期后变成死链,
      // 读的时候由 MediaSigner 现签(见 frames.h / http_api.cpp)。
      const auto& image = request.image;
      if (!image.is_object()) {
        return 42201;
      }
      const auto canonical_url = signer_.canonical(image.value("url", std::string()));
      const auto canonical_thumb = signer_.canonical(image.value("thumb_url", std::string()));
      if (!canonical_url.has_value() || !canonical_thumb.has_value()) {
        return 42201;
      }
      const auto width = image.value("width", 0ULL);
      const auto height = image.value("height", 0ULL);
      const auto size = image.value("size", 0ULL);
      if (canonical_url->size() > 512 || canonical_thumb->size() > 512 || width == 0 ||
          height == 0 || width > 4096 || height > 4096 || size == 0 ||
          size > 5 * 1024 * 1024) {
        return 42201;
      }
      nlohmann::json stored = image;
      stored["url"] = *canonical_url;
      stored["thumb_url"] = *canonical_thumb;
      body = {{"image", stored}};
    } else {
```

- [ ] **Step 4: 读时签名(WS 推送)**

`imserver/src/net/frames.h`:函数签名与实现改为

```cpp
inline std::string build_message_frame(const SendResult& result, const SendRequest& request,
                                       const MediaSigner& signer) {
  ...
  } else if (request.kind == 3) {
    data["image"] = request.image;
    signer.sign_image(data["image"]);
  } else {
```

并在文件顶部 `#include "util/media_sign.h"`。

`imserver/src/net/ws_server.cpp:394` 改为:

```cpp
    registry_.send_to(request.to, build_message_frame(*ok, request, messages_.signer()));
```

`imserver/src/net/http_api.cpp:319` 同理:

```cpp
        registry_.send_to(request.to, build_message_frame(*ok, request, messages_.signer()));
```

- [ ] **Step 5: 读时签名(历史与会话)**

`imserver/src/net/http_api.cpp::message_json` 签名改为:

```cpp
nlohmann::json message_json(const MessageRow& row, UserRepo& users, const MediaSigner& signer) {
```

`kind == 3` 分支改为:

```cpp
    if (row.kind == 3) {
      data["kind"] = "image";
      data["image"] = body.value("image", nlohmann::json::object());
      signer.sign_image(data["image"]);
    } else if (row.kind == 2) {
```

两处调用改为 `message_json(view.last, messages_.users(), messages_.signer())` 与
`message_json(row, messages_.users(), messages_.signer())`。

- [ ] **Step 6: 跑集成测试确认通过**

Run: `cd imserver && docker compose -f docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh`
Expected: PASS(test_history / test_internal / test_image / e2e)

Run: `cd imserver && docker compose -f docker-compose.test.yml run --rm test bash /src/scripts/test_integration.sh`
Expected: PASS(db 测试,`MessageService` 构造函数默认参数保证旧用例仍编译)

- [ ] **Step 7: 提交**

```bash
git add imserver/src imserver/tests imserver/scripts/test_http.sh imserver/docker-compose.test.yml
git commit -m "feat(imserver): 图片消息读时签名与落库规范化"
```

---

## Task 9: 文档、部署与全量回归

**Files:**
- Modify: `docs/ops/imserver.md`(环境变量、nginx、cron、清理命令)
- Modify: `docs/pitfalls/im.md`(两个新坑)
- Modify: `docs/api/im.md`(6.2 节补签名说明与示例 URL)
- Modify: `CLAUDE.md`(接口表补 `/im/images/auth`;里程碑补一行)
- Modify: `imserver/deploy/nginx-im.conf`(如包含 media 段则同步;否则只写文档)

**Interfaces:**
- Consumes: 前面全部任务的产物。
- Produces: 可照着做的部署核对单。

- [ ] **Step 1: 更新运维手册**

`docs/ops/imserver.md` 追加:

````markdown
## 聊天图片签名 URL(2026-10-26)

### 环境变量(两端必须一致)

| 变量 | Django | imserver | 说明 |
|---|---|---|---|
| `IM_MEDIA_SIGN_SECRET` | 必填 | 必填 | ≥32 字节随机串;不一致的表现是**所有聊天图片 403** |
| `IM_MEDIA_SIGN_TTL` | 86400 | 86400 | 签名有效期(秒),按整点对齐 |

### nginx(站点 `server{}`,必须放在 `location ^~ /media/` 之前)

生产 nginx **没有** `secure_link` 模块(实测只有 `--with-http_auth_request_module`),
所以用内部子请求验签:

```nginx
location ^~ /media/chat/ {
    auth_request /_im_media_auth;
    alias /www/wwwroot/chatapp/chatapp/media/;
    expires 1h;
    add_header Cache-Control "private, max-age=3600";
}

location = /_im_media_auth {
    internal;
    proxy_pass http://127.0.0.1:8000/api/v1/im/images/auth;
    proxy_pass_request_body off;
    proxy_set_header Content-Length "";
    proxy_set_header X-Original-URI $request_uri;
}
```

验证:复制图片地址去掉 `?e=&s=` 应 403;带上应 200;把 `e` 改成过去时间应 403。

### 清理(宝塔计划任务,每天 04:00)

```bash
cd /www/wwwroot/chatapp/chatapp && /www/wwwroot/chatapp-venv/bin/python manage.py im_media_cleanup --apply
```

- 默认 dry-run;第一次上线先手动跑一次不带 `--apply` 看汇总;
- 保留期 `CHAT_IMAGE_RETENTION_DAYS`(默认 30 天);`0` = 只清孤儿与残留;
- 用量:`manage.py im_media_stats`。
````

- [ ] **Step 2: 更新踩坑册**

`docs/pitfalls/im.md` 追加两条:

````markdown
## 聊天图片签名(2026-10-26)

- **生产 nginx 没有 `secure_link`**:宝塔编译参数只有 `--with-http_auth_request_module`。
  不要照抄网上的 `secure_link` 配置,`nginx -t` 会报 unknown directive。用 `auth_request`。
- **签名必须在读时生成**:写进 `im_message.body` 的 URL 一旦带签名,24h 后历史消息永久 403。
  imserver 落库前统一去 query(`MediaSigner::canonical`),推送/历史/会话列表再现签。
- **两端密钥不一致的表现**:所有聊天图片 403、`/media/chat/` 之外的图正常 ——
  先比对 `.env` 与容器环境变量,别去查 nginx。
````

- [ ] **Step 3: 更新接口文档的 6.2 节**

在 `docs/api/im.md` 6.2 的「响应参数」说明里补一句:

```markdown
> `url` / `thumb_url` 是**带签名**的限时地址(默认 24 小时,按整点对齐),
> 直接使用即可;签名过期或被运营删除后返回 403/404,客户端按加载失败占位处理。
> 签名规则见 6.3。
```

并把「响应示例」里的两个 URL 改成带 `?e=...&s=...` 的形态。

- [ ] **Step 4: 更新 CLAUDE.md**

- 接口表 `POST /im/images` 下加一行:`GET /im/images/auth`(nginx 子请求验签);
- 里程碑表加一行:`2026-10-26 | 聊天图片签名 URL + 30 天保留期清理(...)`。

- [ ] **Step 5: 全量回归**

```bash
cd chatapp && conda run -n Django python manage.py test
cd imserver && docker compose -f docker-compose.test.yml run --rm test bash /src/scripts/test.sh
cd imserver && docker compose -f docker-compose.test.yml run --rm test bash /src/scripts/test_integration.sh
cd imserver && docker compose -f docker-compose.test.yml run --rm test bash /src/scripts/test_http.sh
```

Expected:全部 PASS;`ApiDocsCoverageTests` 与 `CommentCoverageTests` 绿。

- [ ] **Step 6: 提交**

```bash
git add docs CLAUDE.md
git commit -m "docs(im): 聊天图片签名与清理的部署/接口/坑册"
```

---

## Task 10: 生产部署与验收

**Files:** 无代码改动;服务器上:`.env`、容器环境、nginx、cron。

**Interfaces:**
- Consumes: Task 9 的核对单。

- [ ] **Step 1: 本地构建并上传镜像**

```bash
cd D:/pycharmproject/chat_app
git rev-parse --short HEAD          # 记下 <sha>
docker build -t imserver:<sha> imserver
docker save -o imserver-image.tar imserver:<sha>
gzip -f imserver-image.tar
scp imserver-image.tar.gz root@47.116.114.110:/tmp/
```

- [ ] **Step 2: 服务器加载镜像并配环境变量**

```bash
ssh root@47.116.114.110
cd /tmp && gunzip -f imserver-image.tar.gz && docker load -i imserver-image.tar
# Django .env 追加(值用 openssl rand -hex 32 生成)
IM_MEDIA_SIGN_SECRET=<32+ 字节>
IM_MEDIA_SIGN_TTL=86400
CHAT_IMAGE_RETENTION_DAYS=30
# 容器环境(compose 文件或 docker run -e)加同样两个 IM_MEDIA_SIGN_*
```

- [ ] **Step 3: 迁移 + 重启 + nginx**

```bash
cd /www/wwwroot/chatapp/chatapp && /www/wwwroot/chatapp-venv/bin/python manage.py migrate
supervisorctl restart 'chatapp-web:*' 'chatapp-celery:*'
# nginx 加 Task 9 的两段 location,放在 ^~ /media/ 之前
nginx -t && nginx -s reload
# 起新容器(compose up -d 或 docker run,带新环境变量)
```

- [ ] **Step 4: 验收**

```bash
# 1) 无签名 403
curl -s -o /dev/null -w '%{http_code}\n' http://47.116.114.110/media/chat/<任一已存在文件>
# 2) 上传一张图拿签名 URL,原样 200
curl -s -o /dev/null -w '%{http_code}\n' '<带 ?e=&s= 的地址>'
# 3) 改 e 为过去时间 → 403
# 4) 两端发一张图,App/Web 都能看到;历史重进仍在
# 5) 干跑清理
cd /www/wwwroot/chatapp/chatapp && /www/wwwroot/chatapp-venv/bin/python manage.py im_media_cleanup
```

- [ ] **Step 5: 记录**

把实际结果补进 `docs/ops/imserver.md` 的部署记录表(镜像 sha、验收结论、遗留)。

---

## 自查记录

- 规格覆盖:签名(D1–D4/Task 1–4、7–8)、清理(D5–D7/Task 5–6)、部署(§9/Task 10)、
  运营台(Task 3)、文档(Task 4/9)均有对应任务。
- 类型一致:`sign_url` / `verify` / `signature` / `expires_at` 在 Task 1 定义,后续任务与
  imserver 的 `sign_url` / `sign_image` / `canonical` 命名一致。
- 共享向量:`2b46...d419`(exp 1761782400)与 `b574...a718`(exp 1761868800)分别用于
  Django 与 C++ 测试,均由同一算法算出。

---

## 执行记录(2026-10-26)

| Task | 状态 | 备注 |
|---|---|---|
| 1 Django 签名模块与配置 | ✅ | `im/media_sign.py`,共享向量两侧一致 |
| 2 ChatImage 过期状态与签名属性 | ✅ | 迁移 `0002_chatimage_expired_at_alter_chatimage_status` |
| 3 上传响应签名 + 运营台预览 | ✅ | 既有断言改为解析 path 后再比对 |
| 4 验签接口 + 路由 + 接口文档 | ✅ | `GET /api/v1/im/images/auth` |
| 5 `im_media_cleanup` | ✅ | 默认 dry-run,7 个用例 |
| 6 `im_media_stats` | ✅ | |
| 7 imserver `MediaSigner` + 配置 | ✅ | unit 17 全过(含共享向量) |
| 8 写时规范化 + 读时签名 | ✅ | 新增 `tests/integration/test_image.py`;`tools/im_e2e.py` 改为断言签名 URL |
| 9 文档 + 全量回归 | ✅ | 后端 486 绿;imserver unit 17 / db 10 / http 集成全过 |
| 10 生产部署 | ⏸ 待用户确认 | 服务器仓库仍停在 `9c327e9`,**图片二期本身也没部署**;本轮部署会把两批一起推上去,需先配 `IM_MEDIA_PREFIX`/`IM_MEDIA_SIGN_SECRET`/nginx/cron |
