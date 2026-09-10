from datetime import date

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
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
