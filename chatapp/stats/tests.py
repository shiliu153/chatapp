"""个人使用报告接口的测试。

覆盖场景:
    1. 三种周期的起止日期:自然周(周一起)/ 自然月 / 自然年,含闰年 2 月;
    2. 七项数字只数**区间内**、只数**我自己**的行,区间外与他人活动一律不计;
    3. 缺省周期是 ``week``;``period`` 非法 400 + ``40005``;未登录 401;
    4. 解除过配对的记录仍按创建时间计入(口径是「区间内新产生的配对」);
    5. 访客表是「一人一行」,按 ``last_at`` 落区间:很久以前首次看过、本周期又来看的人
       算本周期,只有首次在本周期而最近访问在周期外的不算。
"""

from datetime import date, datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from discovery.models import Match, Swipe, SwipeAction
from feed.models import Follow, Post, PostLike
from users.models import ProfileVisit

from .services import METRICS, period_bounds, period_window

User = get_user_model()

URL = "/api/v1/stats/me"


def _make_user(phone: str) -> User:
    """造一个只带账号行的用户(报告接口不需要资料与照片)。

    Args:
        phone: 手机号(兼昵称)。

    Returns:
        新建用户。
    """
    return User.objects.create_user(phone=phone)


def _at(model, when: datetime, **fields):
    """按指定时刻创建一行(``created_at`` 是 ``auto_now_add``,只能建完再改)。

    Args:
        model: 模型类。
        when: ``created_at`` 要落到的时刻。
        **fields: 其余建行字段。

    Returns:
        创建好的行;``created_at`` 已改成 ``when``。
    """
    row = model.objects.create(**fields)
    model.objects.filter(pk=row.pk).update(created_at=when)
    row.created_at = when
    return row


def _inside(period: str, today: date | None = None) -> datetime:
    """取周期内一个安全的时刻(区间起点后 12 小时)。

    Args:
        period: ``week`` / ``month`` / ``year``。
        today: 参照日期;``None`` 表示今天。

    Returns:
        带时区的时刻。
    """
    after, _ = period_window(period, today)
    return after + timedelta(hours=12)


def _just_before(period: str, today: date | None = None) -> datetime:
    """取周期起点前一秒(必定落在区间外)。

    Args:
        period: ``week`` / ``month`` / ``year``。
        today: 参照日期;``None`` 表示今天。

    Returns:
        带时区的时刻。
    """
    after, _ = period_window(period, today)
    return after - timedelta(seconds=1)


class PeriodBoundsTests(APITestCase):
    """周期边界的纯函数口径(不查库)。"""

    def test_week_starts_on_monday(self):
        """自然周从周一起、到周日止:周一当天是周一,周中落在同一周。"""
        monday = date(2026, 11, 9)
        self.assertEqual(period_bounds("week", monday), (date(2026, 11, 9), date(2026, 11, 15)))
        # 周日(11-15)仍属于这一周
        self.assertEqual(period_bounds("week", date(2026, 11, 15)),
                         (date(2026, 11, 9), date(2026, 11, 15)))
        # 跨月也按自然周算
        self.assertEqual(period_bounds("week", date(2026, 12, 1)),
                         (date(2026, 11, 30), date(2026, 12, 6)))

    def test_month_is_calendar_month(self):
        """自然月从 1 号到月末,2 月按当年天数(闰年 29 天)。"""
        self.assertEqual(period_bounds("month", date(2026, 11, 9)),
                         (date(2026, 11, 1), date(2026, 11, 30)))
        self.assertEqual(period_bounds("month", date(2028, 2, 10)),
                         (date(2028, 2, 1), date(2028, 2, 29)))
        self.assertEqual(period_bounds("month", date(2027, 2, 10)),
                         (date(2027, 2, 1), date(2027, 2, 28)))

    def test_year_is_calendar_year(self):
        """自然年是整年,与参照日在年内哪个位置无关。"""
        expected = (date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(period_bounds("year", date(2026, 1, 1)), expected)
        self.assertEqual(period_bounds("year", date(2026, 12, 31)), expected)

    def test_window_is_half_open_in_local_time(self):
        """时刻区间左闭右开,且按本地时区(Asia/Shanghai)拼边界。"""
        after, before = period_window("month", date(2026, 11, 9))
        zone = timezone.get_current_timezone()
        self.assertEqual(after, timezone.make_aware(datetime.combine(date(2026, 11, 1), time.min), zone))
        # 右边界是 12-01 00:00(不含),所以 11-30 全天都在区间内
        self.assertEqual(before, timezone.make_aware(datetime.combine(date(2026, 12, 1), time.min), zone))


class StatsApiTests(APITestCase):
    """``GET /api/v1/stats/me`` 的数字口径与错误分支。"""

    def setUp(self):
        """准备当前用户、四个对方与登录态。"""
        cache.clear()
        self.me = _make_user("13400134000")
        self.peers = [_make_user(f"1340013400{index}") for index in range(1, 5)]
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _seed(self, inside: datetime, outside: datetime) -> None:
        """在两个时刻各造一套「七项指标各 1」的数据,并混入不该计入的干扰行。

        Args:
            inside: 落在统计区间内的时刻。
            outside: 落在统计区间外的时刻(区间起点前一秒)。
        """
        inner_a, inner_b, outer_a, outer_b = self.peers
        for moment, actor, other in ((inside, inner_a, inner_b), (outside, outer_a, outer_b)):
            match = Match.objects.create(**Match.pair_kwargs(self.me, actor))
            Match.objects.filter(pk=match.pk).update(created_at=moment)
            _at(Swipe, moment, swiper=self.me, target=actor, action=SwipeAction.LIKE)
            _at(Swipe, moment, swiper=other, target=self.me, action=SwipeAction.LIKE)
            visit = ProfileVisit.objects.create(viewer=actor, owner=self.me, last_at=moment)
            ProfileVisit.objects.filter(pk=visit.pk).update(first_at=moment)
            post = _at(Post, moment, author=self.me, text="我的动态")
            _at(PostLike, moment, post=post, user=actor)
            _at(Follow, moment, follower=other, followee=self.me)

        # 干扰行:都是别人的活动,一条都不能计到我的报告里
        _at(Match, inside, **Match.pair_kwargs(inner_a, inner_b))
        _at(Swipe, inside, swiper=inner_a, target=inner_b, action=SwipeAction.LIKE)
        _at(Post, inside, author=inner_a, text="别人的动态")
        other_post = Post.objects.get(author=inner_a)
        _at(PostLike, inside, post=other_post, user=inner_b)
        ProfileVisit.objects.create(viewer=self.me, owner=inner_a, last_at=inside)   # 我看别人
        _at(Follow, inside, follower=self.me, followee=inner_a)                       # 我关注别人
        _at(Swipe, inside, swiper=self.me, target=inner_b, action=SwipeAction.PASS)    # 划过但没喜欢

    def _get(self, period: str | None = None) -> dict:
        """请求报告接口并返回 JSON。

        Args:
            period: 传给 ``period`` 查询参数的周期;``None`` 表示不传。

        Returns:
            响应 JSON。
        """
        params = {"period": period} if period else {}
        response = self.client.get(URL, params)
        self.assertEqual(response.status_code, 200, response.content[:300])
        return response.json()

    def test_each_period_counts_only_rows_inside_it(self):
        """三种周期下七项数字都是 1:区间内的计入、区间外的与别人的都不计。"""
        for period in ("week", "month", "year"):
            with self.subTest(period=period):
                Match.objects.all().delete()
                Swipe.objects.all().delete()
                Post.objects.all().delete()
                PostLike.objects.all().delete()
                Follow.objects.all().delete()
                ProfileVisit.objects.all().delete()
                self._seed(_inside(period), _just_before(period))

                data = self._get(period)
                start, end = period_bounds(period)
                self.assertEqual(data["period"], period)
                self.assertEqual(data["start"], start.isoformat())
                self.assertEqual(data["end"], end.isoformat())
                self.assertEqual({name: data[name] for name in METRICS},
                                 {name: 1 for name in METRICS})

    def test_default_period_is_week(self):
        """不传 ``period`` 时按自然周统计。"""
        data = self._get()
        start, end = period_bounds("week")
        self.assertEqual(data["period"], "week")
        self.assertEqual(data["start"], start.isoformat())
        self.assertEqual(data["end"], end.isoformat())

    def test_invalid_period_returns_40005(self):
        """非法周期 400 + 业务码 40005。"""
        response = self.client.get(URL, {"period": "day"})
        self.assertEqual(response.status_code, 400)
        body = response.json()
        self.assertEqual(body["code"], 40005)
        self.assertIn("week", body["message"])
        self.assertIn("request_id", body)

    def test_requires_auth(self):
        """未带令牌 401。"""
        response = APIClient().get(URL)
        self.assertEqual(response.status_code, 401)

    def test_unmatched_matches_still_counted(self):
        """解除过的配对仍按创建时间计入(口径是「区间内新产生的配对」)。"""
        peer = self.peers[0]
        match = Match.objects.create(**Match.pair_kwargs(self.me, peer))
        Match.objects.filter(pk=match.pk).update(
            created_at=_inside("week"), unmatched_at=timezone.now())
        self.assertEqual(self._get("week")["matches"], 1)

    def test_visits_follow_last_visit_time(self):
        """访客按 ``last_at`` 落区间:很久以前首次看过、本周期又来的算本周期。"""
        long_ago = _inside("week") - timedelta(days=60)
        # 首次访问在两个月前,最近一次在本周期内 → 计入
        revisit = ProfileVisit.objects.create(viewer=self.peers[0], owner=self.me,
                                              last_at=_inside("week"))
        ProfileVisit.objects.filter(pk=revisit.pk).update(first_at=long_ago)
        # 首次访问在本周期内,但最近一次访问已经过了本周期 → 不计入
        stale = ProfileVisit.objects.create(viewer=self.peers[1], owner=self.me,
                                            last_at=_just_before("week"))
        ProfileVisit.objects.filter(pk=stale.pk).update(first_at=_inside("week"))
        self.assertEqual(self._get("week")["visits"], 1)

    def test_counts_are_integers_even_when_empty(self):
        """没有任何数据时七项都是 0(标量子查询要拿到 0 而不是 null)。"""
        data = self._get("week")
        for name in METRICS:
            self.assertEqual(data[name], 0)
            self.assertIsInstance(data[name], int)
