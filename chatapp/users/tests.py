"""用户资料应用的测试:年龄换算、资料完善度、资料/照片/偏好、在线状态与账号注销。

覆盖场景:
    - 年龄换算:生日当天恰好 18 岁、差一天算 17;年龄区间换算成生日区间、闰日退化;
    - 资料完善度:新资料默认未完善、``refresh_status`` 不覆盖封禁状态;
    - 标签池由数据迁移写入;
    - 我的资料:鉴权、懒创建、``user_id`` 是账号 id 而非资料主键、标签池;
    - 编辑资料:局部更新、昵称变化才同步 IM、未满 18 拒绝、违禁词、非法标签与性别;
    - 照片:开发期上传即过审、过审同步头像、非图片拒绝、6 张上限、删自己的照片与文件、
      不能删别人的、状态随照片增减在完善/未完善间流转;
    - 资料语音:3 秒 201 + 签名地址、31 秒 400(提示 30 秒)、覆盖上传只剩一条且旧文件已删、
      我的/他人资料都返回 ``voice``、没录过为 ``null``、DELETE 幂等且删文件、
      配额超限 413+41301 且不落盘、缺 ffmpeg 503+50302、不进「资料完善」判定、限流;
    - 偏好:默认值、更新、区间非法、未满 18 下限、目标性别为空表示不限;
    - admin 审核动作:驳回与通过时的状态重算、记录审核人与时间;
    - 他人资料卡:只返回公开字段、重封禁不可见、轻封禁可见、拉黑双向不可见、404;
    - 共同标签:只返回交集且按 id 升序、无交集/我没标签时为空数组、查询条数不随标签数增长;
    - 资料卡关注态:默认未关注且计数为 0、关注后 ``is_followed`` 为真、粉丝/关注数正确、
      查询条数不随关注数增长;
    - 抓取监控:同目标一小时只计一次、跨目标累加、超阈值告警、Redis 故障不影响响应;
    - 在线状态服务:写入后在线、窗口边界、未知用户、本地时区 ISO、Redis 故障降级;
    - 在线状态接口:鉴权、返回在线与最后活跃、剔除拉黑/自己/未知/重封禁、去重保序、
      参数校验、限流、Redis 故障返回 null 而非 500;
    - 账号注销:鉴权、手机号不一致或缺失拒绝、重封禁禁止注销、删除全部关联数据与磁盘文件、
      清理在线状态与待踢标记、提交后按 im_user_id 入队删号、旧令牌失效、同号可重注册。
"""

import base64
import io
import os
import shutil
import tempfile
import time
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.test import SimpleTestCase, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from accounts import sms_codes
from config import storage
from discovery.models import Match, Swipe
from feed.models import Follow, Post, PostComment, PostImage
from im import tasks as im_tasks
from im.models import ChatImage, ChatImageStatus, ChatVoice, ChatVoiceStatus
from moderation.models import BanLog, Block, Report

from . import presence, services
from .models import (Photo, PhotoStatus, Profile, ProfileStatus, ProfileVisit, ProfileVoice,
                     Tag, birthday_bounds, calculate_age)

User = get_user_model()


class AgeTests(SimpleTestCase):
    """周岁换算:生日当天恰好满岁,差一天仍算上一岁。"""

    def test_calculate_age_boundary(self):
        today = date(2026, 9, 10)
        self.assertEqual(calculate_age(date(2008, 9, 11), today), 17)   # 差一天
        self.assertEqual(calculate_age(date(2008, 9, 10), today), 18)   # 生日当天刚好 18


class BirthdayBoundsTests(SimpleTestCase):
    """年龄区间换算成生日区间,含闰日退化的边界。"""

    def test_bounds(self):
        upper, lower = birthday_bounds(18, 30, today=date(2026, 9, 10))
        self.assertEqual(upper, date(2008, 9, 10))   # 生在这天 = 刚好 18 岁
        self.assertEqual(lower, date(1995, 9, 10))   # 生在更早 = 31 岁,排除

    def test_leap_day(self):
        upper, _ = birthday_bounds(1, 30, today=date(2024, 2, 29))
        self.assertEqual(upper, date(2023, 2, 28))


class ProfileModelTests(TestCase):
    """资料模型:默认未完善,重算状态时不会覆盖封禁状态。"""

    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")

    def test_new_profile_is_incomplete(self):
        profile = Profile.objects.create(user=self.user)
        self.assertEqual(profile.status, ProfileStatus.INCOMPLETE)
        self.assertIn("nickname", profile.missing_fields())
        self.assertIn("photos", profile.missing_fields())

    def test_refresh_status_does_not_override_ban(self):
        profile = Profile.objects.create(user=self.user, status=ProfileStatus.BANNED_HEAVY)
        profile.refresh_status()
        self.assertEqual(profile.status, ProfileStatus.BANNED_HEAVY)


class SeedTagTests(TestCase):
    """标签池:由数据迁移写入,数量不少于 10 个。"""

    def test_tags_seeded_by_migration(self):
        self.assertGreaterEqual(Tag.objects.count(), 10)


class AuthMixin:
    """接口用例公共设施:给测试客户端装上指定用户的令牌。"""

    def login(self, user):
        """把指定用户的 access token 装到测试客户端。

        Args:
            user: 目标用户。
        """
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


class MeTests(AuthMixin, APITestCase):
    """我的资料:鉴权、懒创建、``user_id`` 语义与标签池。"""

    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")

    def test_requires_auth(self):
        resp = self.client.get("/api/v1/users/me")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["code"], 401)

    def test_me_creates_profile_lazily(self):
        self.login(self.user)
        resp = self.client.get("/api/v1/users/me")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["phone"], "13800138000")
        self.assertEqual(data["status"], "incomplete")
        self.assertEqual(data["photos"], [])
        self.assertEqual(data["tags"], [])
        self.assertIn("nickname", data["missing_fields"])
        self.assertTrue(Profile.objects.filter(user=self.user).exists())

    def test_me_user_id_is_account_id_not_profile_pk(self):
        # 我的页「ID」行要显示账号 ID(u7),不是 profile 主键(u7 的资料是第 6 条)
        other = User.objects.create_user(phone="13800138001")
        Profile.objects.get_or_create(user=other)   # 先占掉 profile 自增 1
        self.login(self.user)
        data = self.client.get("/api/v1/users/me").json()
        self.assertEqual(data["user_id"], self.user.id)
        self.assertNotEqual(data["id"], data["user_id"])   # id 仍是 profile 主键,便于区分

    def test_tags_pool(self):
        self.login(self.user)
        resp = self.client.get("/api/v1/users/tags")
        self.assertEqual(resp.status_code, 200)
        self.assertGreaterEqual(len(resp.json()), 10)


class ProfileUpdateTests(AuthMixin, APITestCase):
    """编辑资料:局部更新、昵称变化才同步 IM、未满 18 与各类非法输入。"""

    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")
        self.login(self.user)
        self.url = "/api/v1/users/me"

    def _full_profile(self, **overrides):
        """拼一份完整的资料提交体。

        Args:
            **overrides: 需要覆盖的字段。

        Returns:
            可直接作为 PATCH body 的字典。
        """
        data = {
            "nickname": "小明",
            "gender": "male",
            "birthday": "2000-01-01",
            "city": "上海",
            "bio": "喜欢音乐",
        }
        data.update(overrides)
        return data

    def test_toggle_visits_hidden(self):
        resp = self.client.patch(self.url, {"visits_hidden": True}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["visits_hidden"])
        self.user.profile.refresh_from_db()
        self.assertTrue(self.user.profile.visits_hidden)

    def test_visits_hidden_defaults_false_in_me(self):
        self.assertFalse(self.client.get(self.url).json()["visits_hidden"])

    @patch("im.tasks.sync_profile.delay")
    def test_update_fields(self, delay):
        tag = Tag.objects.first()
        resp = self.client.patch(self.url, {**self._full_profile(), "tag_ids": [tag.id]}, format="json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["nickname"], "小明")
        self.assertEqual(data["age"], calculate_age(date(2000, 1, 1)))
        self.assertEqual([t["id"] for t in data["tags"]], [tag.id])
        self.assertEqual(data["status"], "incomplete")   # 还差照片

    @patch("im.tasks.sync_profile.delay")
    def test_partial_update_keeps_other_fields(self, delay):
        self.client.patch(self.url, {"nickname": "小明"}, format="json")
        resp = self.client.patch(self.url, {"city": "北京"}, format="json")
        self.assertEqual(resp.json()["nickname"], "小明")
        self.assertEqual(resp.json()["city"], "北京")

    @patch("im.tasks.sync_profile.delay")
    def test_patch_nickname_triggers_im_sync(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.client.patch(self.url, {"nickname": "新名字"}, format="json")
        self.assertEqual(resp.status_code, 200)
        delay.assert_called_once_with(self.user.id, "nick")

    @patch("im.tasks.sync_profile.delay")
    def test_patch_same_nickname_no_sync(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(self.url, {"nickname": "小明"}, format="json")
            self.client.patch(self.url, {"nickname": "小明"}, format="json")
        self.assertEqual(delay.call_count, 1)   # 只有第一次实际变化时同步

    @patch("im.tasks.sync_profile.delay")
    def test_patch_other_field_no_sync(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            self.client.patch(self.url, {"city": "杭州"}, format="json")
        delay.assert_not_called()

    def test_underage_rejected_and_not_saved(self):
        too_young = f"{timezone.localdate().year - 17}-01-01"
        resp = self.client.patch(self.url, {"birthday": too_young}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIsNone(Profile.objects.get(user=self.user).birthday)

    def test_blocked_word_in_nickname_rejected(self):
        resp = self.client.patch(self.url, {"nickname": "代开发票找我"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("message", resp.json())

    def test_unknown_tag_rejected(self):
        resp = self.client.patch(self.url, {"tag_ids": [999999]}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_invalid_gender_rejected(self):
        resp = self.client.patch(self.url, {"gender": "alien"}, format="json")
        self.assertEqual(resp.status_code, 400)


PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class PhotoTests(AuthMixin, APITestCase):
    """照片:开发期上传即过审、过审同步头像、上限与格式、删除与状态流转。"""

    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)   # 测试图片必须写入临时目录,不能落到真实 media/
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(phone="13800138000")
        self.login(self.user)
        self.url = "/api/v1/users/me/photos"

    def upload(self, name="a.png", content=PNG_1PX, content_type="image/png"):
        """上传一张图片到相册。

        Args:
            name: 文件名。
            content: 文件字节内容。
            content_type: MIME 类型。

        Returns:
            DRF 测试客户端的响应对象。
        """
        return self.client.post(self.url, {"file": SimpleUploadedFile(name, content, content_type=content_type)},
                                format="multipart")

    def fill_profile(self):
        """补全资料(会触发昵称同步任务,测试里挡掉)。

        Returns:
            PATCH 资料接口的响应对象。
        """
        # 补全资料会改昵称 → 触发 IM 同步任务,测试里一律挡掉
        with patch("im.tasks.sync_profile.delay"):
            return self.client.patch("/api/v1/users/me", {
                "nickname": "小明", "gender": "male", "birthday": "2000-01-01",
                "city": "上海", "bio": "喜欢音乐",
            }, format="json")

    def test_upload_auto_approved_in_dev(self):
        resp = self.upload()
        self.assertEqual(resp.status_code, 201)
        data = resp.json()
        self.assertEqual(data["status"], "approved")
        self.assertTrue(data["url"].startswith("http://testserver/media/"))

    @patch("im.tasks.sync_profile.delay")
    def test_upload_approved_photo_syncs_im_avatar(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self.upload()
        self.assertEqual(resp.status_code, 201)
        delay.assert_called_once_with(self.user.id, "avatar")

    def test_upload_rejects_non_image(self):
        resp = self.upload(name="a.txt", content=b"not an image", content_type="text/plain")
        self.assertEqual(resp.status_code, 400)

    def test_upload_rejects_gif(self):
        """资料图同样只接受 jpg/png/webp(L5)。"""
        buffer = io.BytesIO()
        Image.new("RGB", (1, 1), "red").save(buffer, "GIF")
        resp = self.upload(name="a.gif", content=buffer.getvalue(), content_type="image/gif")
        self.assertEqual(resp.status_code, 400)

    def test_upload_strips_exif(self):
        """资料图重编码后不保留原始 EXIF(M4)。"""
        exif = Image.Exif()
        exif[0x010F] = "TestCamera"
        buffer = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(buffer, "JPEG", exif=exif)
        resp = self.upload(name="a.jpg", content=buffer.getvalue(), content_type="image/jpeg")
        self.assertEqual(resp.status_code, 201, resp.json())
        with Image.open(Photo.objects.get().file.path) as stored:
            self.assertNotIn(0x010F, stored.getexif())

    def test_upload_limit_six(self):
        for i in range(6):
            self.assertEqual(self.upload(name=f"{i}.png").status_code, 201)
        self.assertEqual(self.upload(name="7.png").status_code, 400)

    def test_upload_throttled(self):
        """照片上传按用户限流,超限 429(M7)。"""
        from .throttles import PhotoUploadThrottle

        cache.clear()
        with patch.object(PhotoUploadThrottle, "rate", "2/hour", create=True):
            self.assertEqual(self.upload().status_code, 201)
            self.assertEqual(self.upload().status_code, 201)
            self.assertEqual(self.upload().status_code, 429)

    def test_delete_own_photo_removes_file(self):
        photo_id = self.upload().json()["id"]
        resp = self.client.delete(f"{self.url}/{photo_id}")
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(Photo.objects.filter(id=photo_id).exists())

    def test_cannot_delete_others_photo(self):
        other = User.objects.create_user(phone="13900139000")
        photo = Photo.objects.create(user=other, file="photos/x.png")
        resp = self.client.delete(f"{self.url}/{photo.id}")
        self.assertEqual(resp.status_code, 404)

    def test_status_becomes_complete_with_approved_photo(self):
        self.fill_profile()
        self.assertEqual(self.client.get("/api/v1/users/me").json()["status"], "incomplete")
        self.upload()
        self.assertEqual(self.client.get("/api/v1/users/me").json()["status"], "complete")

    def test_status_returns_to_incomplete_after_photo_delete(self):
        self.fill_profile()
        photo_id = self.upload().json()["id"]
        self.client.delete(f"{self.url}/{photo_id}")
        self.assertEqual(self.client.get("/api/v1/users/me").json()["status"], "incomplete")

    @override_settings(AUTO_APPROVE=False)
    def test_pending_photo_when_auto_approve_off(self):
        self.fill_profile()
        self.assertEqual(self.upload().json()["status"], "pending")
        self.assertEqual(self.client.get("/api/v1/users/me").json()["status"], "incomplete")

    def test_upload_records_file_bytes(self):
        """上传后把重编码字节数记进 ``bytes``,供配额统计(M7)。"""
        self.assertEqual(self.upload().status_code, 201)
        photo = Photo.objects.get()
        self.assertEqual(photo.bytes, photo.file.size)

    def test_upload_rejected_when_quota_exceeded(self):
        """配额已满时上传 413/41301,且不建行、不落盘(M7)。"""
        self.assertEqual(self.upload().status_code, 201)
        used = Photo.objects.get().bytes
        with self.settings(USER_STORAGE_QUOTA_BYTES=used):
            resp = self.upload(name="b.png")
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(resp.json()["code"], 41301)
        self.assertEqual(Photo.objects.count(), 1)

    def test_quota_zero_disables_limit(self):
        """``USER_STORAGE_QUOTA_BYTES=0`` 表示关闭配额(本地手测口径)。"""
        with self.settings(USER_STORAGE_QUOTA_BYTES=0):
            self.assertEqual(self.upload().status_code, 201)


class ProfileVoiceTests(AuthMixin, APITestCase):
    """资料语音自我介绍(批次 R):上传/覆盖/删除、30 秒上限、签名 URL、配额不落盘。"""

    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)
        cache.clear()
        self.user = User.objects.create_user(phone="13800138000")
        self.login(self.user)
        self.url = "/api/v1/users/me/voice"

    def upload(self, content=b"fake-m4a", name="a.m4a", content_type="audio/mp4"):
        """上传一段资料语音。

        Args:
            content: 文件字节。
            name: 文件名。
            content_type: MIME 类型。

        Returns:
            DRF 测试客户端的响应对象。
        """
        return self.client.post(
            self.url,
            {"file": SimpleUploadedFile(name, content, content_type=content_type)},
            format="multipart")

    def voice_files(self):
        """列出媒体目录里已落盘的语音文件。

        Returns:
            语音文件的 ``Path`` 列表(覆盖上传的断言用「只剩一个」)。
        """
        root = Path(self.media_dir) / "voices"
        return sorted(root.rglob("*.m4a")) if root.exists() else []

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"transcoded"))
    @patch("im.voice._probe_ms", return_value=3000)
    def test_upload_three_seconds_returns_public_url(self, _probe, _transcode, _ffmpeg):
        """3 秒语音:201 + 公开绝对地址(无 query)+ 实测时长,文件与行都落库。"""
        resp = self.upload()
        self.assertEqual(resp.status_code, 201, resp.json())
        data = resp.json()
        self.assertTrue(data["url"].startswith("http://testserver/media/voices/"))
        self.assertNotIn("?", data["url"])
        self.assertEqual(data["duration_ms"], 3000)
        record = ProfileVoice.objects.get()
        self.assertEqual(record.profile.user_id, self.user.id)
        self.assertEqual(record.bytes, len(b"transcoded"))
        self.assertRegex(record.file.name, r"^voices/\d{4}/\d{2}/\d+-[0-9a-f]{32}\.m4a$")
        self.assertTrue(record.file.storage.exists(record.file.name))

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"transcoded"))
    @patch("im.voice._probe_ms", return_value=31000)
    def test_rejects_over_thirty_seconds(self, _probe, _transcode, _ffmpeg):
        """31 秒 → 400,提示里写明上限是 30 秒,且不落库不落盘。"""
        resp = self.upload()
        self.assertEqual(resp.status_code, 400)
        self.assertIn("30 秒", resp.json()["message"])
        self.assertEqual(ProfileVoice.objects.count(), 0)
        self.assertEqual(self.voice_files(), [])

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"transcoded"))
    @patch("im.voice._probe_ms", return_value=3000)
    def test_second_upload_replaces_and_deletes_old_file(self, _probe, _transcode, _ffmpeg):
        """重复上传 = 覆盖:库里仍只有一条,旧文件已从磁盘删除。"""
        self.assertEqual(self.upload().status_code, 201)
        first = ProfileVoice.objects.get().file.name
        self.assertEqual(self.upload(content=b"second").status_code, 201)
        self.assertEqual(ProfileVoice.objects.count(), 1)
        current = ProfileVoice.objects.get()
        self.assertNotEqual(current.file.name, first)
        self.assertFalse(default_storage.exists(first))
        self.assertEqual(len(self.voice_files()), 1)

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"transcoded"))
    @patch("im.voice._probe_ms", return_value=3000)
    def test_me_and_public_profile_expose_voice_url(self, _probe, _transcode, _ffmpeg):
        """``GET /users/me`` 与他人资料卡都返回 ``voice``,URL 是公开绝对地址。"""
        self.assertEqual(self.upload().status_code, 201)
        mine = self.client.get("/api/v1/users/me").json()["voice"]
        self.assertIsNotNone(mine)
        self.assertEqual(mine["duration_ms"], 3000)

        viewer = User.objects.create_user(phone="13900139000")
        self.login(viewer)
        public = self.client.get(f"/api/v1/users/{self.user.id}")
        self.assertEqual(public.status_code, 200, public.json())
        voice = public.json()["voice"]
        self.assertEqual(voice["duration_ms"], 3000)
        for url in (mine["url"], voice["url"]):
            # 与照片完全同口径:公开绝对地址、**不带任何 query**。语音落在
            # /media/voices/,nginx 是裸静态直出,签 e/s 也没有人校验,所以干脆不签。
            self.assertTrue(url.startswith("http://testserver/media/voices/"))
            self.assertNotIn("?", url)

    def test_voice_is_null_without_upload(self):
        """没录过语音时字段是 ``null``,而不是报错或空对象。"""
        self.assertIsNone(self.client.get("/api/v1/users/me").json()["voice"])

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"transcoded"))
    @patch("im.voice._probe_ms", return_value=3000)
    def test_delete_is_idempotent_and_removes_file(self, _probe, _transcode, _ffmpeg):
        """DELETE 两次都 204;之后 ``voice`` 为 ``null`` 且磁盘文件已删。"""
        self.assertEqual(self.upload().status_code, 201)
        name = ProfileVoice.objects.get().file.name
        self.assertEqual(self.client.delete(self.url).status_code, 204)
        self.assertEqual(self.client.delete(self.url).status_code, 204)
        self.assertEqual(ProfileVoice.objects.count(), 0)
        self.assertFalse(default_storage.exists(name))
        self.assertIsNone(self.client.get("/api/v1/users/me").json()["voice"])

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"transcoded"))
    @patch("im.voice._probe_ms", return_value=3000)
    def test_quota_exceeded_returns_413_and_writes_nothing(self, _probe, _transcode, _ffmpeg):
        """配额超限:413 + ``41301``,既不建行**也不落盘**(检查在 ``file.save()`` 之前)。"""
        with self.settings(USER_STORAGE_QUOTA_BYTES=1):
            resp = self.upload()
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(resp.json()["code"], 41301)
        self.assertEqual(ProfileVoice.objects.count(), 0)
        self.assertEqual(self.voice_files(), [])

    @patch("im.voice.ffmpeg_available", return_value=False)
    def test_returns_503_without_ffmpeg(self, _ffmpeg):
        """服务器没装 ffmpeg/ffprobe:503 + ``50302``(不新增业务码)。"""
        resp = self.upload()
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["code"], 50302)

    def test_rejects_non_audio(self):
        resp = self.upload(name="a.png", content=b"png", content_type="image/png")
        self.assertEqual(resp.status_code, 400)

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 401)
        self.assertEqual(self.upload().status_code, 401)

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"x"))
    @patch("im.voice._probe_ms", return_value=3000)
    def test_voice_does_not_affect_profile_status(self, _probe, _transcode, _ffmpeg):
        """回归:语音**不进**「资料完善」判定 —— 有语音不改变状态,没有也不会退化。"""
        profile = services.get_profile(self.user)
        before = profile.status
        self.assertEqual(self.upload().status_code, 201)
        profile.refresh_from_db()
        self.assertEqual(profile.status, before)
        self.assertIn("nickname", profile.missing_fields())
        self.assertNotIn("voice", profile.missing_fields())

    @patch("users.throttles.ProfileVoiceThrottle.get_rate", return_value="1/hour")
    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"x"))
    @patch("im.voice._probe_ms", return_value=3000)
    def test_upload_is_throttled(self, _rate, _probe, _transcode, _ffmpeg):
        """上传按账号限流(默认 10 次/小时)。"""
        cache.clear()
        self.assertEqual(self.upload().status_code, 201)
        self.assertEqual(self.upload().status_code, 429)


class StorageUsageTests(TestCase):
    """存储用量口径:五类媒体相加,已删除/已过期的不计,按账号隔离(M7)。"""

    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")

    def _chat_image(self, size, status=ChatImageStatus.VISIBLE):
        """造一条聊天图元数据(不写磁盘,只落 ``bytes``)。

        Args:
            size: 字节数。
            status: 图片状态。

        Returns:
            新建的 ``ChatImage``。
        """
        return ChatImage.objects.create(
            owner=self.user, file="chat/a.jpg", thumb="chat/a_t.jpg",
            width=1, height=1, bytes=size, status=status)

    def test_usage_sums_all_media_types(self):
        Photo.objects.create(user=self.user, file="photos/a.png", bytes=10)
        post = Post.objects.create(author=self.user, text="x")
        PostImage.objects.create(post=post, file="posts/a.png", bytes=20)
        self._chat_image(30)
        ChatVoice.objects.create(owner=self.user, file="chat/voices/a.m4a",
                                 duration_ms=1000, bytes=40)
        ProfileVoice.objects.create(profile=services.get_profile(self.user),
                                    file="voices/a.m4a", duration_ms=1000, bytes=50)
        self.assertEqual(storage.usage_bytes(self.user.id), 150)

    def test_expired_or_deleted_media_not_counted(self):
        self._chat_image(30, status=ChatImageStatus.EXPIRED)
        self._chat_image(40, status=ChatImageStatus.DELETED)
        ChatVoice.objects.create(owner=self.user, file="chat/voices/a.m4a",
                                 duration_ms=1000, bytes=50,
                                 status=ChatVoiceStatus.EXPIRED)
        self.assertEqual(storage.usage_bytes(self.user.id), 0)

    def test_usage_is_per_user(self):
        other = User.objects.create_user(phone="13900139000")
        Photo.objects.create(user=other, file="photos/b.png", bytes=99)
        self.assertEqual(storage.usage_bytes(self.user.id), 0)


class MediaCommandTests(TestCase):
    """媒体管理命令:字节回填、孤儿清理、磁盘报表告警(M7)。"""

    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(phone="13800138000")

    def _write(self, relative, content=b"abc"):
        """在临时 MEDIA_ROOT 下写一个文件。

        Args:
            relative: 相对 ``MEDIA_ROOT`` 的路径。
            content: 文件内容。

        Returns:
            写入后的绝对路径。
        """
        path = Path(settings.MEDIA_ROOT) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def test_media_bytes_backfill_fills_sizes(self):
        photo = Photo.objects.create(user=self.user, file="photos/a.png")
        self._write("photos/a.png", b"12345")
        call_command("media_bytes_backfill", stdout=StringIO())
        photo.refresh_from_db()
        self.assertEqual(photo.bytes, 5)

    def test_media_bytes_backfill_dry_run_does_not_write(self):
        Photo.objects.create(user=self.user, file="photos/a.png")
        self._write("photos/a.png", b"12345")
        call_command("media_bytes_backfill", "--dry-run", stdout=StringIO())
        self.assertEqual(Photo.objects.get().bytes, 0)

    def test_media_cleanup_deletes_only_orphans_with_apply(self):
        Photo.objects.create(user=self.user, file="photos/keep.png")
        kept = self._write("photos/keep.png")
        orphan = self._write("photos/orphan.png")
        old = time.time() - 48 * 3600
        os.utime(orphan, (old, old))

        call_command("media_cleanup", stdout=StringIO())
        self.assertTrue(orphan.exists())          # dry-run 不删

        call_command("media_cleanup", "--apply", stdout=StringIO())
        self.assertFalse(orphan.exists())
        self.assertTrue(kept.exists())

    def test_media_disk_report_fails_over_threshold(self):
        self._write("photos/big.bin", b"x" * (2 * 1024 * 1024))
        with self.assertRaises(SystemExit):
            call_command("media_disk_report", "--warn-mb", "1", "--fail-over",
                         stdout=StringIO(), stderr=StringIO())


class PreferenceTests(AuthMixin, APITestCase):
    """择偶偏好:默认值、更新、区间与年龄下限校验、目标性别为空表示不限。"""

    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")
        self.login(self.user)
        self.url = "/api/v1/users/me/preference"

    def test_defaults(self):
        data = self.client.get(self.url).json()
        self.assertIsNone(data["target_gender"])
        self.assertEqual(data["age_min"], 18)
        self.assertEqual(data["age_max"], 99)
        self.assertEqual(data["city"], "")

    def test_update(self):
        resp = self.client.patch(self.url, {"target_gender": "female", "age_min": 22,
                                            "age_max": 30, "city": "上海"}, format="json")
        self.assertEqual(resp.status_code, 200)
        data = self.client.get(self.url).json()
        self.assertEqual(data["target_gender"], "female")
        self.assertEqual(data["age_min"], 22)
        self.assertEqual(data["age_max"], 30)
        self.assertEqual(data["city"], "上海")

    def test_invalid_range_rejected(self):
        resp = self.client.patch(self.url, {"age_min": 40, "age_max": 30}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_underage_range_rejected(self):
        resp = self.client.patch(self.url, {"age_min": 17}, format="json")
        self.assertEqual(resp.status_code, 400)

    def test_target_gender_null_means_any(self):
        self.client.patch(self.url, {"target_gender": "male"}, format="json")
        resp = self.client.patch(self.url, {"target_gender": None}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.json()["target_gender"])


class PhotoAdminActionTests(TestCase):
    """审核台批量动作:改照片状态,并重算用户的「资料完善」状态。"""

    def setUp(self):
        self.staff = User.objects.create_superuser(phone="13700137000", password="pw")
        self.user = User.objects.create_user(phone="13900139000")
        self.profile = Profile.objects.create(
            user=self.user, nickname="小红", gender="female", birthday="2000-01-01",
            city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        self.photo = Photo.objects.create(user=self.user, file="photos/x.png",
                                          status=PhotoStatus.APPROVED)
        self.client.force_login(self.staff)

    def _run_action(self, action, *photos):
        """通过 admin 的批量动作接口对指定照片执行审核。

        Args:
            action: admin action 名称(``approve_photos`` / ``reject_photos``)。
            *photos: 要处理的照片对象。

        Returns:
            admin 接口的响应对象。
        """
        return self.client.post("/admin/users/photo/", {
            "action": action,
            "_selected_action": [p.pk for p in photos],
        })

    def test_reject_action_marks_photo_and_profile_incomplete(self):
        resp = self._run_action("reject_photos", self.photo)
        self.assertEqual(resp.status_code, 302)
        self.photo.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.photo.status, PhotoStatus.REJECTED)
        self.assertEqual(self.profile.status, ProfileStatus.INCOMPLETE)

    def test_approve_action_completes_profile_again(self):
        Photo.objects.filter(pk=self.photo.pk).update(status=PhotoStatus.PENDING)
        Profile.objects.filter(pk=self.profile.pk).update(status=ProfileStatus.INCOMPLETE)
        self._run_action("approve_photos", self.photo)
        self.photo.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertEqual(self.photo.status, PhotoStatus.APPROVED)
        self.assertEqual(self.profile.status, ProfileStatus.COMPLETE)

    def test_action_records_reviewer_and_time(self):
        self._run_action("approve_photos", self.photo)
        self.photo.refresh_from_db()
        self.assertEqual(self.photo.reviewed_by, self.staff)
        self.assertIsNotNone(self.photo.reviewed_at)


class PublicProfileTests(AuthMixin, APITestCase):
    """他人资料卡:只返回公开字段、封禁与拉黑下的可见性、404 与鉴权。"""

    def setUp(self):
        self.me = User.objects.create_user(phone="13800138000")
        self.login(self.me)
        self.other = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.other, nickname="小红", gender="female",
                               birthday="1998-01-01", city="上海", bio="喜欢爬山",
                               status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=self.other, file="photos/a.png", status=PhotoStatus.APPROVED)
        Photo.objects.create(user=self.other, file="photos/b.png", status=PhotoStatus.PENDING)

    def _get(self):
        """请求他人资料卡。

        Returns:
            DRF 测试客户端的响应对象。
        """
        return self.client.get(f"/api/v1/users/{self.other.id}")

    def test_returns_public_fields_only(self):
        data = self._get().json()
        self.assertEqual(data["user_id"], self.other.id)
        self.assertEqual(data["nickname"], "小红")
        self.assertEqual(data["age"], calculate_age(date(1998, 1, 1)))
        self.assertEqual(len(data["photos"]), 1)          # 只有过审那张
        for hidden in ("phone", "birthday", "preference", "missing_fields"):
            self.assertNotIn(hidden, data)

    def test_public_profile_hides_visits_hidden(self):
        Profile.objects.filter(user=self.other).update(visits_hidden=True)
        self.assertNotIn("visits_hidden", self._get().json())

    def test_heavy_banned_target_is_invisible(self):
        Profile.objects.filter(user=self.other).update(status=ProfileStatus.BANNED_HEAVY)
        self.assertEqual(self._get().status_code, 404)

    def test_light_banned_target_still_visible(self):
        Profile.objects.filter(user=self.other).update(status=ProfileStatus.BANNED_LIGHT)
        self.assertEqual(self._get().status_code, 200)

    def test_blocked_relationship_hides_both_ways(self):
        Block.objects.create(blocker=self.me, blocked=self.other)
        self.assertEqual(self._get().status_code, 404)
        Block.objects.all().delete()
        Block.objects.create(blocker=self.other, blocked=self.me)
        self.assertEqual(self._get().status_code, 404)

    def test_unknown_user_returns_404(self):
        self.assertEqual(self.client.get("/api/v1/users/999999").status_code, 404)

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self._get().status_code, 401)


class SharedTagsTests(AuthMixin, APITestCase):
    """共同标签(``shared_tags``):交集口径、无交集兜底、查询条数不随标签数增长。"""

    def setUp(self):
        self.me = User.objects.create_user(phone="13800138001")
        self.login(self.me)
        self.other = User.objects.create_user(phone="13900139001")
        Profile.objects.create(user=self.other, nickname="小红", gender="female",
                               birthday="1998-01-01", city="上海", bio="喜欢爬山",
                               status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=self.other, file="photos/a.png", status=PhotoStatus.APPROVED)
        self.tags = list(Tag.objects.order_by("id")[:4])

    def _set_tags(self, user, tags):
        """给指定用户设置标签。

        Args:
            user: 目标用户。
            tags: 标签对象序列。
        """
        services.get_profile(user).tags.set(tags)

    def _shared_tags(self):
        """请求他人资料卡并取出 ``shared_tags``。

        Returns:
            ``shared_tags`` 列表。
        """
        response = self.client.get(f"/api/v1/users/{self.other.id}")
        self.assertEqual(response.status_code, 200, response.content[:200])
        return response.json()["shared_tags"]

    def test_returns_intersection_only(self):
        """只返回交集,且按标签 id 升序。"""
        self._set_tags(self.me, [self.tags[0], self.tags[2]])
        self._set_tags(self.other, [self.tags[1], self.tags[2], self.tags[0]])
        self.assertEqual([tag["id"] for tag in self._shared_tags()],
                         [self.tags[0].id, self.tags[2].id])

    def test_empty_when_no_overlap(self):
        """没有交集时是空数组,不是 404 也不是 null。"""
        self._set_tags(self.me, [self.tags[0]])
        self._set_tags(self.other, [self.tags[1]])
        self.assertEqual(self._shared_tags(), [])

    def test_empty_when_viewer_has_no_tags(self):
        """我没选标签时同样返回空数组(避免把对方的全部标签当成共同点)。"""
        self._set_tags(self.other, [self.tags[0], self.tags[1]])
        self.assertEqual(self._shared_tags(), [])

    def test_query_count_does_not_grow_with_tag_count(self):
        """共同标签只多一次 M2M 查询,不随标签数量线性增长(N+1 守卫)。"""
        self._set_tags(self.me, self.tags[:1])
        self._set_tags(self.other, [self.tags[0]])
        with CaptureQueriesContext(connection) as one_shared:
            self._shared_tags()
        self._set_tags(self.me, self.tags)
        self._set_tags(self.other, self.tags)
        with CaptureQueriesContext(connection) as many_shared:
            self._shared_tags()
        self.assertEqual(len(one_shared.captured_queries), len(many_shared.captured_queries))


class FollowStateTests(AuthMixin, APITestCase):
    """资料卡关注态:``is_followed`` 口径、粉丝/关注数、查询条数恒定。"""

    def setUp(self):
        self.me = User.objects.create_user(phone="13800138002")
        self.login(self.me)
        self.other = User.objects.create_user(phone="13900139002")
        Profile.objects.create(user=self.other, nickname="小红", gender="female",
                               birthday="1998-01-01", city="上海", bio="喜欢爬山",
                               status=ProfileStatus.COMPLETE)
        self.fan = User.objects.create_user(phone="13700137002")
        Profile.objects.create(user=self.fan, nickname="粉丝", status=ProfileStatus.COMPLETE)

    def _state(self):
        """请求他人资料卡并取出三个关注态字段。

        Returns:
            ``(is_followed, follower_count, following_count)`` 三元组。
        """
        response = self.client.get(f"/api/v1/users/{self.other.id}")
        self.assertEqual(response.status_code, 200, response.content[:200])
        data = response.json()
        return data["is_followed"], data["follower_count"], data["following_count"]

    def test_default_state_is_not_followed(self):
        """没人关注、我也没有关注时:三个字段都是默认值(不是缺字段)。"""
        self.assertEqual(self._state(), (False, 0, 0))

    def test_is_followed_true_after_following(self):
        Follow.objects.create(follower=self.me, followee=self.other)
        self.assertTrue(self._state()[0])

    def test_counts_are_directional(self):
        """粉丝数只算「关注对方的人」,关注数只算「对方关注的人」。"""
        Follow.objects.create(follower=self.me, followee=self.other)
        Follow.objects.create(follower=self.fan, followee=self.other)
        Follow.objects.create(follower=self.other, followee=self.fan)
        is_followed, follower_count, following_count = self._state()
        self.assertTrue(is_followed)
        self.assertEqual(follower_count, 2)     # 我 + 粉丝
        self.assertEqual(following_count, 1)    # 对方只关注了粉丝

    def test_query_count_does_not_grow_with_follow_count(self):
        """关注态固定只多一条聚合 SQL,不随关注数增长(N+1 守卫)。"""
        self._state()   # 预热:首次请求会触发偏好/访客等一次性懒创建
        with CaptureQueriesContext(connection) as few:
            self._state()
        for index in range(5):
            fan = User.objects.create_user(phone=f"1360013{index:04d}")
            Follow.objects.create(follower=fan, followee=self.other)
        with CaptureQueriesContext(connection) as many:
            self._state()
        self.assertEqual(len(few.captured_queries), len(many.captured_queries))


class ProfileScrapeMonitorTests(TestCase):
    """M2 抓取监控:同目标一小时只计一次、跨目标累加、超阈值告警、Redis 故障不影响响应。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.bucket = int(time.time()) // services.PROFILE_VIEW_TTL_SECONDS

    def _count(self, viewer_id):
        """读该浏览者当前小时的计数。

        Args:
            viewer_id: 浏览者账号 id。

        Returns:
            计数;没记录时为 ``None``。
        """
        return cache.get(f"profile_view_count:{viewer_id}:{self.bucket}")

    def test_same_target_counted_once_per_hour(self):
        services.record_profile_view(1, 2)
        services.record_profile_view(1, 2)
        self.assertEqual(self._count(1), 1)

    def test_distinct_targets_accumulate(self):
        for target in (2, 3, 4):
            services.record_profile_view(1, target)
        self.assertEqual(self._count(1), 3)

    @override_settings(PROFILE_SCRAPE_ALERT_PER_HOUR=2)
    def test_threshold_logs_warning_once(self):
        with self.assertLogs("users.services", "WARNING") as logs:
            for target in (2, 3, 4, 5):
                services.record_profile_view(1, target)
        self.assertEqual(len(logs.records), 1)
        self.assertIn("疑似资料抓取", logs.records[0].getMessage())

    def test_cache_failure_is_swallowed(self):
        with patch("users.services.cache.add", side_effect=RuntimeError("redis down")):
            services.record_profile_view(1, 2)   # 不抛异常即通过


class ProfileScrapeApiTests(AuthMixin, APITestCase):
    """看他人资料会写计数;接口本身不受计数失败影响。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.me = User.objects.create_user(phone="13800138001")
        self.login(self.me)
        self.other = User.objects.create_user(phone="13900139001")
        Profile.objects.create(user=self.other, nickname="小蓝", status=ProfileStatus.COMPLETE)

    def test_viewing_profile_writes_counter(self):
        self.client.get(f"/api/v1/users/{self.other.id}")
        bucket = int(time.time()) // services.PROFILE_VIEW_TTL_SECONDS
        self.assertEqual(cache.get(f"profile_view_count:{self.me.id}:{bucket}"), 1)

    def test_counter_failure_does_not_break_response(self):
        with patch("users.services.cache.add", side_effect=RuntimeError("redis down")):
            self.assertEqual(self.client.get(f"/api/v1/users/{self.other.id}").status_code, 200)


class PresenceServiceTests(TestCase):
    """在线状态服务:写入即在线、窗口边界、未知用户、时区与 Redis 故障降级。"""

    def setUp(self):
        cache.clear()

    def test_touch_then_online(self):
        presence.touch(9)
        data = presence.get_presence([9])
        self.assertTrue(data[9]["online"])
        self.assertIsNotNone(data[9]["last_active_at"])

    def test_online_window_boundary(self):
        # 119 秒内 = 在线;121 秒 = 离线但仍有最后活跃时间
        cache.set("presence:9", int(time.time()) - 119)
        cache.set("presence:10", int(time.time()) - 121)
        data = presence.get_presence([9, 10])
        self.assertTrue(data[9]["online"])
        self.assertFalse(data[10]["online"])
        self.assertIsNotNone(data[10]["last_active_at"])

    def test_unknown_user_is_unknown(self):
        self.assertEqual(presence.get_presence([404])[404],
                         {"online": False, "last_active_at": None})

    def test_iso_uses_local_timezone(self):
        cache.set("presence:9", 1757745000)
        text = presence.get_presence([9])[9]["last_active_at"]
        self.assertRegex(text, r"\+08:00$")

    @patch("users.presence.cache.get_many", side_effect=Exception("boom"))
    def test_redis_down_query_degrades(self, _):
        self.assertEqual(presence.get_presence([9])[9],
                         {"online": False, "last_active_at": None})

    @patch("users.presence.cache.set", side_effect=Exception("boom"))
    def test_redis_down_touch_is_silent(self, _):
        presence.touch(9)   # 不抛异常


class PresenceApiTests(AuthMixin, APITestCase):
    """在线状态接口:返回在线与最后活跃、剔除不可见对象、去重保序、限流与降级。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.me = User.objects.create_user(phone="13800138000")
        self.other = User.objects.create_user(phone="13800138001")
        Profile.objects.get_or_create(user=self.other)
        self.login(self.me)
        self.url = "/api/v1/presence"

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.url, {"user_ids": "1"}).status_code, 401)

    def test_returns_online_and_last_active(self):
        presence.touch(self.other.id)
        data = self.client.get(self.url, {"user_ids": str(self.other.id)}).json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["user_id"], self.other.id)
        self.assertTrue(data["results"][0]["online"])
        self.assertRegex(data["results"][0]["last_active_at"], r"\+08:00$")

    def test_omits_blocked_both_directions(self):
        third = User.objects.create_user(phone="13800138002")
        Block.objects.create(blocker=self.me, blocked=self.other)      # 我拉黑的
        Block.objects.create(blocker=third, blocked=self.me)           # 拉黑我的
        data = self.client.get(
            self.url, {"user_ids": f"{self.other.id},{third.id}"}).json()
        self.assertEqual(data["results"], [])

    def test_omits_self_unknown_and_heavy_banned(self):
        Profile.objects.filter(user=self.other).update(status=ProfileStatus.BANNED_HEAVY)
        data = self.client.get(
            self.url,
            {"user_ids": f"{self.me.id},{self.other.id},999999"}).json()
        self.assertEqual(data["results"], [])

    def test_dedupes_and_keeps_request_order(self):
        data = self.client.get(
            self.url,
            {"user_ids": f"{self.other.id},{self.me.id},{self.other.id}"}).json()
        # 自己去重省略后,只剩 other,顺序稳定
        self.assertEqual([item["user_id"] for item in data["results"]], [self.other.id])

    def test_bad_params(self):
        self.assertEqual(self.client.get(self.url).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"user_ids": ""}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {"user_ids": "abc"}).status_code, 400)
        too_many = ",".join(str(i) for i in range(1, 102))
        self.assertEqual(self.client.get(self.url, {"user_ids": too_many}).status_code, 400)

    def test_throttled(self):
        from .throttles import PresenceThrottle

        with patch.object(PresenceThrottle, "rate", "2/hour", create=True):
            for _ in range(2):
                self.assertEqual(
                    self.client.get(self.url, {"user_ids": str(self.other.id)}).status_code, 200)
            self.assertEqual(
                self.client.get(self.url, {"user_ids": str(self.other.id)}).status_code, 429)

    @patch("users.presence.cache.get_many", side_effect=Exception("boom"))
    def test_redis_down_returns_null_instead_of_500(self, _):
        resp = self.client.get(self.url, {"user_ids": str(self.other.id)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["results"][0]["last_active_at"], None)


class DeleteAccountTests(AuthMixin, APITestCase):
    """注销账号:立即硬删除 + 手机号二次确认 + 重封禁 403(防注销洗白)。"""

    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)   # 测试图片不写入真实 media/
        override.enable()
        self.addCleanup(override.disable)
        # 清掉别的用例留下的 IP 限流计数 / 验证码 / presence 残留
        # (本类末尾要真调一次 /auth/sms/verify,不清会被别处的限流计数连累)
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(phone="13800138000")
        self.login(self.user)
        self.url = "/api/v1/users/me"

    def _delete(self, phone="13800138000"):
        """调用账号注销接口。

        Args:
            phone: 二次确认用的手机号。

        Returns:
            DRF 测试客户端的响应对象。
        """
        return self.client.delete(self.url, {"phone": phone}, format="json")

    def test_requires_auth(self):
        self.client.credentials()
        resp = self._delete()
        self.assertEqual(resp.status_code, 401)

    def test_phone_mismatch_rejected_and_data_kept(self):
        resp = self._delete(phone="13900139000")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 400)
        self.assertEqual(resp.json()["message"], "手机号与当前账号不一致")
        self.assertTrue(User.objects.filter(id=self.user.id).exists())

    def test_phone_missing_rejected(self):
        resp = self.client.delete(self.url, {}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 400)
        self.assertTrue(User.objects.filter(id=self.user.id).exists())

    def test_heavy_banned_cannot_delete(self):
        Profile.objects.create(user=self.user, status=ProfileStatus.BANNED_HEAVY)
        resp = self._delete()
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(User.objects.filter(id=self.user.id).exists())

    def test_light_banned_can_delete(self):
        Profile.objects.create(user=self.user, status=ProfileStatus.BANNED_LIGHT)
        self.assertEqual(self._delete().status_code, 204)

    def test_success_deletes_user_and_all_related_rows(self):
        user_id = self.user.id
        other = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.user, nickname="小明")
        Photo.objects.create(user=self.user, file="photos/a.png")
        Swipe.objects.create(swiper=self.user, target=other, action="like")
        Swipe.objects.create(swiper=other, target=self.user, action="like")
        Match.objects.create(**Match.pair_kwargs(self.user, other))
        post = Post.objects.create(author=self.user, text="动态")
        PostImage.objects.create(post=post, file="posts/a.png")
        PostComment.objects.create(post=post, author=other, text="评论")
        Block.objects.create(blocker=self.user, blocked=other)
        Report.objects.create(reporter=other, target=self.user, type="harassment")
        BanLog.objects.create(user=self.user, action="ban_light", reason="x")

        resp = self._delete()

        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.content, b"")
        self.assertFalse(User.objects.filter(id=user_id).exists())
        self.assertFalse(Profile.objects.filter(user_id=user_id).exists())
        self.assertFalse(Photo.objects.filter(user_id=user_id).exists())
        self.assertFalse(Swipe.objects.filter(Q(swiper_id=user_id) | Q(target_id=user_id)).exists())
        self.assertFalse(Match.objects.filter(Q(user_a_id=user_id) | Q(user_b_id=user_id)).exists())
        self.assertFalse(Post.objects.filter(author_id=user_id).exists())
        self.assertFalse(PostImage.objects.filter(post__author_id=user_id).exists())
        self.assertFalse(PostComment.objects.filter(author_id=user_id).exists())
        self.assertFalse(Block.objects.filter(Q(blocker_id=user_id) | Q(blocked_id=user_id)).exists())
        self.assertFalse(Report.objects.filter(Q(reporter_id=user_id) | Q(target_id=user_id)).exists())
        self.assertFalse(BanLog.objects.filter(user_id=user_id).exists())

    def test_deletes_photo_and_post_image_files_on_disk(self):
        photo = Photo.objects.create(user=self.user)
        photo.file.save("a.png", ContentFile(PNG_1PX), save=True)
        post = Post.objects.create(author=self.user, text="动态")
        image = PostImage.objects.create(post=post)
        image.file.save("b.png", ContentFile(PNG_1PX), save=True)
        photo_name, image_name = photo.file.name, image.file.name
        self.assertTrue(default_storage.exists(photo_name))
        self.assertTrue(default_storage.exists(image_name))

        with self.captureOnCommitCallbacks(execute=True):
            resp = self._delete()

        self.assertEqual(resp.status_code, 204)
        self.assertFalse(default_storage.exists(photo_name))
        self.assertFalse(default_storage.exists(image_name))

    def test_deletes_chat_image_files_on_disk(self):
        from im.models import ChatImage   # 延迟导入,与 services.py 的删号逻辑保持一致

        image = ChatImage(owner=self.user, width=1, height=1, bytes=len(PNG_1PX))
        image.file.save("chat/c.png", ContentFile(PNG_1PX), save=False)
        image.thumb.save("chat/c_thumb.png", ContentFile(PNG_1PX), save=False)
        image.save()
        names = [image.file.name, image.thumb.name]
        for name in names:
            self.assertTrue(default_storage.exists(name))

        with self.captureOnCommitCallbacks(execute=True):
            resp = self._delete()

        self.assertEqual(resp.status_code, 204)
        for name in names:
            self.assertFalse(default_storage.exists(name), name)

    def test_clears_presence_and_kick_pending_flag(self):
        user_id = self.user.id
        presence.touch(user_id)
        cache.set(im_tasks.kick_pending_key(user_id, "app"), 1, 60)
        self.assertIsNotNone(presence.get_presence([user_id])[user_id]["last_active_at"])

        with self.captureOnCommitCallbacks(execute=True):
            self._delete()

        self.assertIsNone(presence.get_presence([user_id])[user_id]["last_active_at"])
        self.assertIsNone(cache.get(im_tasks.kick_pending_key(user_id, "app")))

    @patch("im.tasks.delete_account.delay")
    def test_enqueues_im_delete_with_im_user_id_after_commit(self, delay):
        user_id = self.user.id          # ⚠️ 必须在注销前取,删完 user.id 会是 None
        with self.captureOnCommitCallbacks(execute=True):
            resp = self._delete()
        self.assertEqual(resp.status_code, 204)
        delay.assert_called_once_with(f"u{user_id}")

    @patch("im.tasks.delete_account.delay")
    def test_nothing_enqueued_when_phone_mismatch(self, delay):
        with self.captureOnCommitCallbacks(execute=True):
            resp = self._delete(phone="13900139000")
        self.assertEqual(resp.status_code, 400)
        delay.assert_not_called()

    def test_other_users_data_untouched(self):
        other = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=other, nickname="小红")
        Photo.objects.create(user=other, file="photos/b.png")
        self.assertEqual(self._delete().status_code, 204)
        self.assertTrue(User.objects.filter(id=other.id).exists())
        self.assertTrue(Profile.objects.filter(user=other).exists())
        self.assertTrue(Photo.objects.filter(user=other).exists())

    def test_old_token_rejected_after_delete(self):
        self.assertEqual(self._delete().status_code, 204)
        # 同一个 access token:用户行没了 → 鉴权失败
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 401)

    def test_same_phone_can_register_again_as_new_user(self):
        old_id = self.user.id
        self.assertEqual(self._delete().status_code, 204)

        self.client.credentials()   # 旧令牌已失效,换匿名请求
        cache.delete("sms:send:13800138000")
        sms_codes.store("13800138000", settings.SMS_DEV_CODE)
        resp = self.client.post("/api/v1/auth/sms/verify",
                                {"phone": "13800138000", "code": settings.SMS_DEV_CODE},
                                format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["is_new_user"])
        self.assertNotEqual(resp.json()["user_id"], old_id)
class ProfileVisitModelTests(TestCase):
    """访客记录模型:默认值、唯一约束、按最近访问排序。"""

    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_visits_hidden_defaults_to_false(self):
        profile = Profile.objects.create(user=self.a, nickname="小明")
        self.assertFalse(profile.visits_hidden)

    def test_unique_viewer_owner_pair(self):
        ProfileVisit.objects.create(viewer=self.a, owner=self.b, last_at=timezone.now())
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                ProfileVisit.objects.create(viewer=self.a, owner=self.b, last_at=timezone.now())

    def test_ordered_by_last_at_desc(self):
        # 显式错开时间:Windows 上 time.time() 分辨率约 15ms,连着两次 now() 可能相等,
        # 排序就会退化成「插入顺序」而偶发失败。
        now = timezone.now()
        ProfileVisit.objects.create(viewer=self.a, owner=self.b,
                                    last_at=now - timedelta(minutes=5))
        ProfileVisit.objects.create(viewer=self.b, owner=self.a, last_at=now)
        first = ProfileVisit.objects.first()
        self.assertEqual(first.viewer_id, self.b.id)

class ProfileVisitWriteTests(TestCase):
    """落库口径:30 分钟窗口、隐身、自看、展示门槛与上限、异常兜底。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.viewer = User.objects.create_user(phone="13800138000")
        self.owner = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.viewer, nickname="小明")
        Profile.objects.create(user=self.owner, nickname="小红")
        self._make_displayable(self.viewer, "小明")

    def _make_displayable(self, user, nickname="小明"):
        """把用户补成「资料完善 + 一张过审照片」——访客记录只对这类访问者落库(M-2)。

        Args:
            user: 目标账号。
            nickname: 昵称(资料完善必填项之一)。

        Returns:
            None。
        """
        profile = user.profile
        profile.nickname = nickname
        profile.gender = "male"
        profile.birthday = date(1995, 1, 1)
        profile.city = "上海"
        profile.bio = "你好"
        profile.save()
        Photo.objects.create(user=user, file="photos/visit-test.jpg",
                             status=PhotoStatus.APPROVED)
        profile.refresh_status()

    def test_first_visit_creates_row(self):
        services.record_profile_view(self.viewer.id, self.owner.id)
        visit = ProfileVisit.objects.get(viewer=self.viewer, owner=self.owner)
        # first_at 由 auto_now_add 在插入时取,last_at 是写入前算的 now,两者差毫秒级
        self.assertLess(abs((visit.last_at - visit.first_at).total_seconds()), 1)

    def test_second_visit_within_window_keeps_one_row(self):
        services.record_profile_view(self.viewer.id, self.owner.id)
        before = ProfileVisit.objects.get(viewer=self.viewer, owner=self.owner).last_at
        services.record_profile_view(self.viewer.id, self.owner.id)
        self.assertEqual(ProfileVisit.objects.count(), 1)
        after = ProfileVisit.objects.get(viewer=self.viewer, owner=self.owner).last_at
        self.assertEqual(before, after)

    def test_visit_after_window_updates_last_at(self):
        services.record_profile_view(self.viewer.id, self.owner.id)
        before = ProfileVisit.objects.get(viewer=self.viewer, owner=self.owner).last_at
        cache.delete(f"visit:{self.viewer.id}:{self.owner.id}")   # 模拟 30 分钟窗口过期
        services.record_profile_view(self.viewer.id, self.owner.id)
        self.assertEqual(ProfileVisit.objects.count(), 1)
        after = ProfileVisit.objects.get(viewer=self.viewer, owner=self.owner).last_at
        self.assertGreater(after, before)

    def test_incognito_viewer_is_not_recorded(self):
        profile = self.viewer.profile
        profile.visits_hidden = True
        profile.save(update_fields=["visits_hidden"])
        services.record_profile_view(self.viewer.id, self.owner.id)
        self.assertEqual(ProfileVisit.objects.count(), 0)

    def test_self_view_is_not_recorded(self):
        services.record_profile_view(self.viewer.id, self.viewer.id)
        self.assertEqual(ProfileVisit.objects.count(), 0)

    def test_write_failure_is_swallowed(self):
        with patch("users.services.ProfileVisit.objects.update_or_create",
                   side_effect=RuntimeError("db down")):
            services.record_profile_view(self.viewer.id, self.owner.id)   # 不抛即通过

    def test_missing_profile_is_not_recorded(self):
        """资料未创建 = 未完善,不在访客列表的展示口径内,不落库(M-2)。"""
        stranger = User.objects.create_user(phone="13900139002")   # 没有 Profile
        services.record_profile_view(stranger.id, self.owner.id)
        self.assertFalse(ProfileVisit.objects.filter(viewer=stranger).exists())

    def test_incomplete_viewer_is_not_recorded(self):
        """资料未完善的访问者不会出现在列表里,写库是纯放大(M-2)。"""
        half = User.objects.create_user(phone="13900139003")
        Profile.objects.create(user=half, nickname="只填了昵称")
        services.record_profile_view(half.id, self.owner.id)
        self.assertFalse(ProfileVisit.objects.filter(viewer=half).exists())

    def test_viewer_without_approved_photo_is_not_recorded(self):
        """照片待审/没有照片同样不落库,与 ``visits_received_queryset`` 同口径(M-2)。"""
        profile = self.viewer.profile
        Photo.objects.filter(user=self.viewer).update(status=PhotoStatus.PENDING)
        profile.refresh_status()
        services.record_profile_view(self.viewer.id, self.owner.id)
        self.assertFalse(ProfileVisit.objects.filter(viewer=self.viewer).exists())

    @override_settings(PROFILE_VISIT_MAX_PER_OWNER=2)
    def test_owner_keeps_only_recent_visits(self):
        """单个 owner 超过上限时淘汰最旧的行,表不会无限增长(M-2 第二道闸)。"""
        for index in range(3):
            viewer = User.objects.create_user(phone=f"1370013900{index}")
            Profile.objects.create(user=viewer, nickname=f"访客{index}")
            self._make_displayable(viewer, f"访客{index}")
            services.record_profile_view(viewer.id, self.owner.id)
        self.assertEqual(ProfileVisit.objects.filter(owner=self.owner).count(), 2)

class PurgeProfileVisitsCommandTests(TestCase):
    """保留期清理:dry-run 不删、--apply 只删过期行、自定义天数。"""

    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")
        self.old = ProfileVisit.objects.create(
            viewer=self.a, owner=self.b,
            last_at=timezone.now() - timedelta(days=91))
        self.fresh = ProfileVisit.objects.create(
            viewer=self.b, owner=self.a,
            last_at=timezone.now() - timedelta(days=89))

    def test_dry_run_keeps_rows(self):
        call_command("purge_profile_visits", stdout=StringIO())
        self.assertEqual(ProfileVisit.objects.count(), 2)

    def test_apply_deletes_only_expired(self):
        call_command("purge_profile_visits", "--apply", stdout=StringIO())
        self.assertFalse(ProfileVisit.objects.filter(id=self.old.id).exists())
        self.assertTrue(ProfileVisit.objects.filter(id=self.fresh.id).exists())

    def test_custom_days(self):
        call_command("purge_profile_visits", "--apply", "--days", "1", stdout=StringIO())
        self.assertEqual(ProfileVisit.objects.count(), 0)