from datetime import date

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import Photo, PhotoStatus, Preference, Profile, ProfileStatus

from .models import Match, Swipe, SwipeAction

User = get_user_model()


def _years_ago(today, years):
    try:
        return date(today.year - years, today.month, today.day)
    except ValueError:      # 2 月 29 日
        return date(today.year - years, today.month, 28)


class SwipeModelTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_same_pair_can_only_swipe_once(self):
        Swipe.objects.create(swiper=self.a, target=self.b, action=SwipeAction.LIKE)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Swipe.objects.create(swiper=self.a, target=self.b, action=SwipeAction.PASS)

    def test_reverse_direction_is_a_different_swipe(self):
        Swipe.objects.create(swiper=self.a, target=self.b, action=SwipeAction.LIKE)
        Swipe.objects.create(swiper=self.b, target=self.a, action=SwipeAction.LIKE)
        self.assertEqual(Swipe.objects.count(), 2)


class MatchModelTests(TestCase):
    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_pair_kwargs_orders_by_id(self):
        self.assertEqual(Match.pair_kwargs(self.b, self.a), {"user_a": self.a, "user_b": self.b})
        self.assertEqual(Match.pair_kwargs(self.a, self.b), {"user_a": self.a, "user_b": self.b})

    def test_duplicate_pair_rejected(self):
        Match.objects.create(**Match.pair_kwargs(self.a, self.b))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Match.objects.create(**Match.pair_kwargs(self.b, self.a))

    def test_reversed_order_rejected_by_check_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Match.objects.create(user_a=self.b, user_b=self.a)

    def test_other_user(self):
        match = Match.objects.create(**Match.pair_kwargs(self.a, self.b))
        self.assertEqual(match.other_user(self.a), self.b)
        self.assertEqual(match.other_user(self.b), self.a)


class CandidateTests(APITestCase):
    URL = "/api/v1/discovery/candidates"

    def setUp(self):
        self.me = self._make_user("13800138000", gender="male", birthday="2000-01-01", city="上海")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, gender="female", birthday="2000-01-01", city="上海", complete=True):
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(
            user=user, nickname=phone, gender=gender, birthday=birthday, city=city, bio="你好",
            status=ProfileStatus.COMPLETE if complete else ProfileStatus.INCOMPLETE,
        )
        if complete:
            Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def _ids(self, resp):
        return [item["user_id"] for item in resp.json()]

    def test_excludes_self_incomplete_and_no_photo(self):
        other = self._make_user("13900139000")
        self._make_user("13900139001", complete=False)
        self._make_user("13900139002")
        Photo.objects.filter(user__phone="13900139002").delete()          # 抽掉照片
        Profile.objects.filter(user__phone="13900139002").update(status=ProfileStatus.COMPLETE)
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), [other.id])

    def test_excludes_swiped_and_matched(self):
        swiped = self._make_user("13900139000")
        matched = self._make_user("13900139001")
        fresh = self._make_user("13900139002")
        Swipe.objects.create(swiper=self.me, target=swiped, action=SwipeAction.PASS)
        Match.objects.create(**Match.pair_kwargs(self.me, matched))
        self.assertEqual(self._ids(self.client.get(self.URL)), [fresh.id])

    def test_filters_by_preference(self):
        Preference.objects.create(profile=self.me.profile, target_gender="female",
                                  age_min=25, age_max=30, city="上海")
        ok = self._make_user("13900139000", gender="female", birthday="1998-01-01", city="上海")   # 28 岁
        self._make_user("13900139001", gender="male", birthday="1998-01-01")        # 性别不符
        self._make_user("13900139002", gender="female", birthday="2005-01-01")      # 太年轻
        self._make_user("13900139003", gender="female", birthday="1990-01-01")      # 太大
        self._make_user("13900139004", gender="female", birthday="1998-01-01", city="北京")  # 城市不符
        self.assertEqual(self._ids(self.client.get(self.URL)), [ok.id])

    def test_age_boundaries_are_inclusive(self):
        today = timezone.localdate()
        Preference.objects.create(profile=self.me.profile, age_min=18, age_max=30)
        exactly_18 = self._make_user("13900139000", birthday=_years_ago(today, 18))
        exactly_30 = self._make_user("13900139001", birthday=_years_ago(today, 30))
        self._make_user("13900139002", birthday=_years_ago(today, 31))   # 31 岁
        self._make_user("13900139003", birthday=_years_ago(today, 17))   # 17 岁
        self.assertEqual(sorted(self._ids(self.client.get(self.URL))), sorted([exactly_18.id, exactly_30.id]))

    def test_without_preference_returns_everyone_eligible(self):
        Preference.objects.filter(profile=self.me.profile).delete()
        a = self._make_user("13900139000", gender="female", birthday="2005-01-01", city="北京")
        b = self._make_user("13900139001", gender="male", birthday="1980-01-01", city="广州")
        self.assertEqual(sorted(self._ids(self.client.get(self.URL))), sorted([a.id, b.id]))

    def test_only_approved_photos_returned(self):
        ghost = self._make_user("13900139000")
        Photo.objects.create(user=ghost, file="photos/pending.png", status=PhotoStatus.PENDING)
        data = self.client.get(self.URL).json()
        self.assertEqual(len(data), 1)
        self.assertTrue(all(p["status"] == "approved" for p in data[0]["photos"]))

    def test_limit_default_and_cap(self):
        for i in range(12):
            self._make_user(f"1390013{i:04d}")
        self.assertEqual(len(self.client.get(self.URL).json()), 10)
        self.assertEqual(len(self.client.get(f"{self.URL}?limit=3").json()), 3)
        self.assertEqual(len(self.client.get(f"{self.URL}?limit=99").json()), 12)   # 上限 20,但只有 12 个人

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.URL).status_code, 401)
