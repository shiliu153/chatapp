"""用户资料应用的测试:年龄换算、资料完善度、资料/照片/偏好、在线状态与账号注销。

覆盖场景:
    - 年龄换算:生日当天恰好 18 岁、差一天算 17;年龄区间换算成生日区间、闰日退化;
    - 资料完善度:新资料默认未完善、``refresh_status`` 不覆盖封禁状态;
    - 标签池由数据迁移写入;
    - 我的资料:鉴权、懒创建、``user_id`` 是账号 id 而非资料主键、标签池;
    - 编辑资料:局部更新、昵称变化才同步 IM、未满 18 拒绝、违禁词、非法标签与性别;
    - 照片:开发期上传即过审、过审同步头像、非图片拒绝、6 张上限、删自己的照片与文件、
      不能删别人的、状态随照片增减在完善/未完善间流转;
    - 偏好:默认值、更新、区间非法、未满 18 下限、目标性别为空表示不限;
    - admin 审核动作:驳回与通过时的状态重算、记录审核人与时间;
    - 他人资料卡:只返回公开字段、重封禁不可见、轻封禁可见、拉黑双向不可见、404;
    - 在线状态服务:写入后在线、窗口边界、未知用户、本地时区 ISO、Redis 故障降级;
    - 在线状态接口:鉴权、返回在线与最后活跃、剔除拉黑/自己/未知/重封禁、去重保序、
      参数校验、限流、Redis 故障返回 null 而非 500;
    - 账号注销:鉴权、手机号不一致或缺失拒绝、重封禁禁止注销、删除全部关联数据与磁盘文件、
      清理在线状态与待踢标记、提交后按 im_user_id 入队删号、旧令牌失效、同号可重注册。
"""

import base64
import shutil
import tempfile
import time
from datetime import date
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db.models import Q
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from accounts import sms_codes
from discovery.models import Match, Swipe
from feed.models import Post, PostComment, PostImage
from im import tasks as im_tasks
from moderation.models import BanLog, Block, Report

from . import presence
from .models import Photo, PhotoStatus, Profile, ProfileStatus, Tag, birthday_bounds, calculate_age

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

    def test_upload_limit_six(self):
        for i in range(6):
            self.assertEqual(self.upload(name=f"{i}.png").status_code, 201)
        self.assertEqual(self.upload(name="7.png").status_code, 400)

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

    def test_clears_presence_and_kick_pending_flag(self):
        user_id = self.user.id
        presence.touch(user_id)
        cache.set(im_tasks.kick_pending_key(user_id), 1, 60)
        self.assertIsNotNone(presence.get_presence([user_id])[user_id]["last_active_at"])

        with self.captureOnCommitCallbacks(execute=True):
            self._delete()

        self.assertIsNone(presence.get_presence([user_id])[user_id]["last_active_at"])
        self.assertIsNone(cache.get(im_tasks.kick_pending_key(user_id)))

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
