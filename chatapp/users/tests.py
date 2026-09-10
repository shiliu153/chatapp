import base64
import shutil
import tempfile
from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Photo, Profile, ProfileStatus, Tag, calculate_age

User = get_user_model()


class AgeTests(SimpleTestCase):
    def test_calculate_age_boundary(self):
        today = date(2026, 9, 10)
        self.assertEqual(calculate_age(date(2008, 9, 11), today), 17)   # 差一天
        self.assertEqual(calculate_age(date(2008, 9, 10), today), 18)   # 生日当天刚好 18


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

    def test_update_fields(self):
        tag = Tag.objects.first()
        resp = self.client.patch(self.url, {**self._full_profile(), "tag_ids": [tag.id]}, format="json")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["nickname"], "小明")
        self.assertEqual(data["age"], calculate_age(date(2000, 1, 1)))
        self.assertEqual([t["id"] for t in data["tags"]], [tag.id])
        self.assertEqual(data["status"], "incomplete")   # 还差照片

    def test_partial_update_keeps_other_fields(self):
        self.client.patch(self.url, {"nickname": "小明"}, format="json")
        resp = self.client.patch(self.url, {"city": "北京"}, format="json")
        self.assertEqual(resp.json()["nickname"], "小明")
        self.assertEqual(resp.json()["city"], "北京")

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
