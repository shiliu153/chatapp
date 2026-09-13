import base64
import shutil
import tempfile
import time
from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from moderation.models import Block

from . import presence
from .models import Photo, PhotoStatus, Profile, ProfileStatus, Tag, birthday_bounds, calculate_age

User = get_user_model()


class AgeTests(SimpleTestCase):
    def test_calculate_age_boundary(self):
        today = date(2026, 9, 10)
        self.assertEqual(calculate_age(date(2008, 9, 11), today), 17)   # 差一天
        self.assertEqual(calculate_age(date(2008, 9, 10), today), 18)   # 生日当天刚好 18


class BirthdayBoundsTests(SimpleTestCase):
    def test_bounds(self):
        upper, lower = birthday_bounds(18, 30, today=date(2026, 9, 10))
        self.assertEqual(upper, date(2008, 9, 10))   # 生在这天 = 刚好 18 岁
        self.assertEqual(lower, date(1995, 9, 10))   # 生在更早 = 31 岁,排除

    def test_leap_day(self):
        upper, _ = birthday_bounds(1, 30, today=date(2024, 2, 29))
        self.assertEqual(upper, date(2023, 2, 28))


class ProfileModelTests(TestCase):
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
    def test_tags_seeded_by_migration(self):
        self.assertGreaterEqual(Tag.objects.count(), 10)


class AuthMixin:
    def login(self, user):
        refresh = RefreshToken.for_user(user)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {refresh.access_token}")


class MeTests(AuthMixin, APITestCase):
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
    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")
        self.login(self.user)
        self.url = "/api/v1/users/me"

    def _full_profile(self, **overrides):
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
    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)   # 别把测试图片写进真 media/
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(phone="13800138000")
        self.login(self.user)
        self.url = "/api/v1/users/me/photos"

    def upload(self, name="a.png", content=PNG_1PX, content_type="image/png"):
        return self.client.post(self.url, {"file": SimpleUploadedFile(name, content, content_type=content_type)},
                                format="multipart")

    def fill_profile(self):
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
