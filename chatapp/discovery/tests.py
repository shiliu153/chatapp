from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
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


class SwipeApiTests(APITestCase):
    URL = "/api/v1/discovery/swipe"

    def setUp(self):
        cache.clear()               # 限流计数存在缓存里,测试之间必须清
        self.addCleanup(cache.clear)
        self.me = self._make_user("13800138000", gender="male")
        self.target = self._make_user("13900139000", gender="female")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, gender="female"):
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=phone, gender=gender, birthday="2000-01-01",
                               city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def swipe(self, target_id, action="like"):
        return self.client.post(self.URL, {"target_user_id": target_id, "action": action}, format="json")

    def test_like_creates_swipe(self):
        resp = self.swipe(self.target.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"matched": False})
        self.assertTrue(Swipe.objects.filter(swiper=self.me, target=self.target,
                                             action=SwipeAction.LIKE).exists())

    def test_repeat_swipe_is_idempotent(self):
        self.swipe(self.target.id)
        resp = self.swipe(self.target.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Swipe.objects.count(), 1)

    def test_mutual_like_creates_one_match(self):
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        with patch("im.tasks.send_match_notice.delay") as notice:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.swipe(self.target.id)
        self.assertEqual(resp.json(), {"matched": True})
        self.assertEqual(Match.objects.count(), 1)
        self.assertEqual(Match.objects.first().user_a, self.me)
        notice.assert_called_once_with(self.me.id, self.target.id)

    def test_mutual_like_after_match_does_not_resend_notice(self):
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        with patch("im.tasks.send_match_notice.delay") as notice:
            with self.captureOnCommitCallbacks(execute=True):
                self.swipe(self.target.id)
                again = self.swipe(self.target.id)
        self.assertEqual(again.json(), {"matched": True})
        self.assertEqual(notice.call_count, 1)

    def test_pass_never_matches(self):
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        resp = self.swipe(self.target.id, action="pass")
        self.assertEqual(resp.json(), {"matched": False})
        self.assertEqual(Match.objects.count(), 0)

    def test_enqueue_failure_does_not_break_swipe(self):
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        with patch("im.tasks.send_match_notice.delay", side_effect=Exception("broker down")):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.swipe(self.target.id)
        self.assertEqual(resp.status_code, 200)   # robust=True 兜住,配对结果不受影响
        self.assertEqual(resp.json(), {"matched": True})

    def test_cannot_swipe_self(self):
        self.assertEqual(self.swipe(self.me.id).status_code, 400)

    def test_unknown_target_returns_404(self):
        self.assertEqual(self.swipe(999999).status_code, 404)

    def test_incomplete_target_rejected(self):
        loner = User.objects.create_user(phone="13900139001")
        Profile.objects.create(user=loner, status=ProfileStatus.INCOMPLETE)
        self.assertEqual(self.swipe(loner.id).status_code, 400)

    def test_banned_light_cannot_swipe(self):
        Profile.objects.filter(user=self.me).update(status=ProfileStatus.BANNED_LIGHT)
        resp = self.swipe(self.target.id)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Swipe.objects.exists())

    def test_invalid_action_rejected(self):
        self.assertEqual(self.swipe(self.target.id, action="hug").status_code, 400)

    def test_swipe_throttled(self):
        from discovery.throttles import SwipeThrottle
        with patch.object(SwipeThrottle, "rate", "2/hour", create=True):
            self.assertEqual(self.swipe(self.target.id).status_code, 200)
            self.assertEqual(self.swipe(self.target.id).status_code, 200)
            self.assertEqual(self.swipe(self.target.id).status_code, 429)


class MatchListTests(APITestCase):
    URL = "/api/v1/matches"

    def setUp(self):
        self.me = self._make_user("13800138000")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, nickname=None, with_photo=True):
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=nickname or phone, gender="female",
                               birthday="2000-01-01", city="上海", bio="你好",
                               status=ProfileStatus.COMPLETE)
        if with_photo:
            Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def test_lists_both_sides(self):
        other = self._make_user("13900139000", nickname="小红")
        Match.objects.create(**Match.pair_kwargs(self.me, other))
        data = self.client.get(self.URL).json()
        self.assertEqual(data["count"], 1)
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["user_id"], other.id)
        self.assertEqual(data["results"][0]["im_user_id"], other.im_user_id)
        self.assertEqual(data["results"][0]["nickname"], "小红")
        self.assertTrue(data["results"][0]["avatar_url"].startswith("http://testserver/media/"))

    def test_avatar_null_without_approved_photo(self):
        other = self._make_user("13900139000", with_photo=False)
        Match.objects.create(**Match.pair_kwargs(self.me, other))
        self.assertIsNone(self.client.get(self.URL).json()["results"][0]["avatar_url"])

    def test_only_my_matches(self):
        other = self._make_user("13900139000")
        stranger_a = self._make_user("13900139001")
        stranger_b = self._make_user("13900139002")
        Match.objects.create(**Match.pair_kwargs(self.me, other))
        Match.objects.create(**Match.pair_kwargs(stranger_a, stranger_b))
        data = self.client.get(self.URL).json()
        self.assertEqual([item["user_id"] for item in data["results"]], [other.id])

    def test_pagination_limit_and_offset(self):
        others = [self._make_user(f"1390013910{i}") for i in range(3)]
        for other in others:
            Match.objects.create(**Match.pair_kwargs(self.me, other))
        first = self.client.get(self.URL, {"limit": 2}).json()
        self.assertEqual(first["count"], 3)
        self.assertEqual(len(first["results"]), 2)
        second = self.client.get(self.URL, {"limit": 2, "offset": 2}).json()
        self.assertEqual(len(second["results"]), 1)
        ids = [item["user_id"] for item in first["results"] + second["results"]]
        self.assertEqual(sorted(ids), sorted(other.id for other in others))   # 翻页不重不漏

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self.client.get(self.URL).status_code, 401)


class DevResetPairCommandTests(TestCase):
    """开发手测用:把一对用户的滑卡/配对记录清掉,好重演「互喜 → 配对」。"""

    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def _seed(self):
        Swipe.objects.create(swiper=self.a, target=self.b, action=SwipeAction.LIKE)
        Swipe.objects.create(swiper=self.b, target=self.a, action=SwipeAction.PASS)
        Match.objects.create(**Match.pair_kwargs(self.a, self.b))

    def test_clears_swipes_and_match_between_the_pair(self):
        self._seed()

        call_command("dev_reset_pair", a=f"u{self.a.id}", b=f"u{self.b.id}")

        self.assertFalse(Swipe.objects.exists())
        self.assertFalse(Match.objects.exists())

    def test_leaves_other_pairs_alone(self):
        self._seed()
        other = User.objects.create_user(phone="13900139001")
        Swipe.objects.create(swiper=self.a, target=other, action=SwipeAction.LIKE)

        call_command("dev_reset_pair", a=f"u{self.a.id}", b=f"u{self.b.id}")

        self.assertEqual(Swipe.objects.count(), 1)
        self.assertTrue(Swipe.objects.filter(swiper=self.a, target=other).exists())

    def test_unknown_im_id_raises(self):
        with self.assertRaises(CommandError):
            call_command("dev_reset_pair", a="u99999", b=f"u{self.b.id}")

    def test_same_id_raises(self):
        with self.assertRaises(CommandError):
            call_command("dev_reset_pair", a=f"u{self.a.id}", b=f"u{self.a.id}")
