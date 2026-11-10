"""个人使用报告接口与每日运营指标快照的测试。

覆盖场景:
    1. 三种周期的起止日期:自然周(周一起)/ 自然月 / 自然年,含闰年 2 月;
    2. 七项数字只数**区间内**、只数**我自己**的行,区间外与他人活动一律不计;
    3. 缺省周期是 ``week``;``period`` 非法 400 + ``40005``;未登录 401;
    4. 解除过配对的记录仍按创建时间计入(口径是「区间内新产生的配对」);
    5. 访客表是「一人一行」,按 ``last_at`` 落区间:很久以前首次看过、本周期又来看的人
       算本周期,只有首次在本周期而最近访问在周期外的不算;
    6. ``metrics_daily``:各字段口径、幂等重跑、``--backfill`` 窗口、``--dry-run`` 不写库、
       留存取「注册 cohort ∩ 当日活跃」交集(不是当日活跃人数)、目标日无数据时为 ``None``、
       「每天只跑昨天」时前一天 / 七天前的留存靠端点外补算、时区按 Asia/Shanghai 日切、
       参数非法退出码 1;
    7. IM 库只读客户端:DSN 密码含 ``@`` 的切分、缺省端口、DSN 为空 / 连不上时降级为
       ``None``、查询参数是 epoch 秒。
"""

from datetime import date, datetime, time, timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient, APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from discovery.models import Match, Swipe, SwipeAction
from feed.models import Follow, Post, PostLike
from users import activity
from users.models import Profile, ProfileStatus, ProfileVisit

from . import im_source
from .metrics import fill_retention, match_rate, recent_rows
from .models import DailyMetric
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


# 快照测试固定用这个「过去的日子」,避免与「今天」的真实活跃数据互相干扰
SNAPSHOT_DAY = date(2026, 11, 2)
# 用例会 touch 的日子:前后各留 10 天,足够覆盖留存用的 D+7
ACTIVITY_DAYS = [SNAPSHOT_DAY + timedelta(days=offset) for offset in range(-10, 11)]


def _local(day: date, hour: int = 10, minute: int = 0, second: int = 0) -> datetime:
    """造一个 ``Asia/Shanghai`` 本地时刻。

    Args:
        day: 本地自然日。
        hour: 小时。
        minute: 分钟。
        second: 秒。

    Returns:
        带时区的时刻。
    """
    return datetime.combine(day, time(hour, minute, second),
                            tzinfo=timezone.get_current_timezone())


@override_settings(IM_MYSQL_DSN="")   # 缺省没有 IM 库:消息量应当是 None 而不是 0
class MetricsDailyCommandTests(TestCase):
    """``metrics_daily``:口径、幂等、回填窗口、留存补算、时区边界与降级。"""

    def setUp(self):
        self._drop_activity()
        self.addCleanup(self._drop_activity)

    def _drop_activity(self):
        """清掉本类用到的活跃集合(Redis DB 跨用例共享,必须自己打扫)。

        Returns:
            None。
        """
        keys = []
        for day in ACTIVITY_DAYS:
            keys.append(activity.day_key(day))
            keys.extend(activity.hour_key(day, hour) for hour in range(24))
        activity._client().delete(*keys)

    def _user(self, phone, joined=None, complete=False):
        """造一个账号,可指定注册时刻并可置为「资料已完善」。

        Args:
            phone: 手机号(唯一)。
            joined: ``date_joined`` 要落到的时刻;``None`` 表示就用当前时间。
            complete: 是否把资料状态置为 ``complete``。

        Returns:
            新建的账号。
        """
        user = User.objects.create_user(phone=phone)
        if joined is not None:
            User.objects.filter(pk=user.pk).update(date_joined=joined)
        profile, _ = Profile.objects.get_or_create(user=user)
        if complete:
            Profile.objects.filter(pk=profile.pk).update(status=ProfileStatus.COMPLETE)
        return user

    def _run(self, *args):
        """跑一次命令并返回标准输出。

        Args:
            *args: 命令行参数。

        Returns:
            命令的完整 stdout。
        """
        out = StringIO()
        call_command("metrics_daily", *args, stdout=out)
        return out.getvalue()

    def test_snapshot_numbers(self):
        """各字段按口径落库:日活 / 新注册 / 完善 / 滑卡 / 配对 / 活跃时段。"""
        day = SNAPSHOT_DAY
        long_ago = _local(day - timedelta(days=30))
        a = self._user("13900000001", joined=long_ago)
        b = self._user("13900000002", joined=long_ago)
        c = self._user("13900000003", joined=long_ago)
        d = self._user("13900000004", joined=long_ago)
        new_done = self._user("13900000005", joined=_local(day, 9), complete=True)
        new_plain = self._user("13900000006", joined=_local(day, 10))
        _at(Swipe, _local(day, 11), swiper=a, target=b, action=SwipeAction.LIKE)
        _at(Swipe, _local(day, 11, 5), swiper=a, target=c, action=SwipeAction.LIKE)
        _at(Swipe, _local(day, 11, 10), swiper=b, target=a, action=SwipeAction.LIKE)
        _at(Swipe, _local(day, 12), swiper=c, target=b, action=SwipeAction.PASS)
        _at(Swipe, _local(day, 12, 5), swiper=c, target=d, action=SwipeAction.PASS)
        _at(Match, _local(day, 13), **Match.pair_kwargs(a, b))
        activity.touch(new_done.id, at=_local(day, 10, 30))
        activity.touch(new_plain.id, at=_local(day, 15, 5))

        self._run("--date", day.isoformat())

        row = DailyMetric.objects.get(date=day)
        self.assertEqual(row.dau, 2)
        self.assertEqual(row.new_users, 2)
        self.assertEqual(row.profiles_completed, 1)
        self.assertEqual(row.swipes_like, 3)
        self.assertEqual(row.swipes_pass, 2)
        self.assertEqual(row.matches, 1)
        self.assertIsNone(row.messages)
        self.assertEqual(row.active_hours[10], 1)
        self.assertEqual(row.active_hours[15], 1)
        self.assertEqual(sum(row.active_hours), 2)
        # 次日 / 第 7 日都没有活跃记录 → 留空,不是 0
        self.assertIsNone(row.retention_d1)
        self.assertIsNone(row.retention_d7)

    def test_dau_is_none_when_no_activity_records(self):
        """没有活跃集合的那天:``dau`` / ``active_hours`` 为 None(看板显示 ``—``)。"""
        day = SNAPSHOT_DAY
        self._run("--date", day.isoformat())
        row = DailyMetric.objects.get(date=day)
        self.assertIsNone(row.dau)
        self.assertIsNone(row.active_hours)
        self.assertEqual(row.new_users, 0)

    def test_dry_run_prints_without_writing(self):
        """``--dry-run`` 打印窗口内每天一行且不写库,缺失值打印 ``-``。"""
        out = self._run("--date", SNAPSHOT_DAY.isoformat(), "--backfill", "3", "--dry-run")
        self.assertEqual(DailyMetric.objects.count(), 0)
        self.assertIn("dry-run", out)
        lines = [line for line in out.splitlines() if line.startswith("2026-")]
        self.assertEqual(len(lines), 3)
        self.assertEqual(
            lines[-1],
            "2026-11-02 dau=- new=0 done=0 like=0 pass=0 match=0 msg=- d1=- d7=-",
        )

    def test_backfill_window_includes_endpoint(self):
        """``--backfill 3`` 写 3 行,日期连续且终点是昨天(缺省 --date)。"""
        self._run("--backfill", "3")
        yesterday = timezone.localdate() - timedelta(days=1)
        dates = list(DailyMetric.objects.order_by("date").values_list("date", flat=True))
        self.assertEqual(dates, [yesterday - timedelta(days=2),
                                 yesterday - timedelta(days=1),
                                 yesterday])

    def test_rerun_is_idempotent_and_overwrites(self):
        """同一天跑两次表里只有 1 行;数据变了重跑会覆盖旧值。"""
        day = SNAPSHOT_DAY
        a = self._user("13900000101")
        b = self._user("13900000102")
        c = self._user("13900000103")
        _at(Swipe, _local(day, 11), swiper=a, target=b, action=SwipeAction.LIKE)

        self._run("--date", day.isoformat())
        self._run("--date", day.isoformat())
        self.assertEqual(DailyMetric.objects.count(), 1)
        self.assertEqual(DailyMetric.objects.get(date=day).swipes_like, 1)

        _at(Swipe, _local(day, 12), swiper=c, target=a, action=SwipeAction.LIKE)
        self._run("--date", day.isoformat())
        self.assertEqual(DailyMetric.objects.count(), 1)
        self.assertEqual(DailyMetric.objects.get(date=day).swipes_like, 2)

    def test_retention_is_cohort_intersection(self):
        """留存 = 当日注册 cohort ∩ 目标日活跃,不是目标日的活跃人数。"""
        day = SNAPSHOT_DAY
        cohort = [self._user(f"1390000020{index}", joined=_local(day, 8)) for index in range(3)]
        outsiders = [self._user(f"1390000021{index}",
                                joined=_local(day - timedelta(days=20)))
                     for index in range(3)]
        for user in cohort[:2]:
            activity.touch(user.id, at=_local(day + timedelta(days=1), 9))
        for user in outsiders:   # 非 cohort 的活跃用户,不能算进留存
            activity.touch(user.id, at=_local(day + timedelta(days=1), 9))
        activity.touch(cohort[0].id, at=_local(day + timedelta(days=7), 9))
        for user in outsiders[:2]:
            activity.touch(user.id, at=_local(day + timedelta(days=7), 9))

        self._run("--date", day.isoformat())

        row = DailyMetric.objects.get(date=day)
        self.assertEqual(row.retention_d1, 2)   # 目标日活跃 5 人,交集只有 2 人
        self.assertEqual(row.retention_d7, 1)   # 目标日活跃 3 人,交集只有 1 人

    def test_retention_is_none_when_target_day_has_no_data(self):
        """目标日没有活跃记录时留空(``None``),不能用 0 冒充。"""
        day = SNAPSHOT_DAY - timedelta(days=1)
        self._user("13900000300", joined=_local(day, 8))
        self._run("--date", day.isoformat())
        row = DailyMetric.objects.get(date=day)
        self.assertIsNone(row.retention_d1)
        self.assertIsNone(row.retention_d7)

    def test_next_run_fills_previous_day_retention(self):
        """「每天只跑昨天」时,前一天的次日留存靠本次运行的端点外补算补上。"""
        yesterday = SNAPSHOT_DAY - timedelta(days=1)
        cohort = [self._user(f"1390000040{index}", joined=_local(yesterday, 8))
                  for index in range(2)]

        self._run("--date", yesterday.isoformat())
        self.assertIsNone(DailyMetric.objects.get(date=yesterday).retention_d1)

        # 昨天注册的人今天活跃 → 明天那次运行要把昨天的 d1 补上
        activity.touch(cohort[0].id, at=_local(SNAPSHOT_DAY, 9))
        activity.touch(cohort[1].id, at=_local(SNAPSHOT_DAY, 9))
        self._run("--date", SNAPSHOT_DAY.isoformat())

        self.assertEqual(DailyMetric.objects.get(date=yesterday).retention_d1, 2)

    def test_fill_retention_does_not_create_rows(self):
        """补留存只 update 已存在的行,不为它凭空造行。"""
        orphan = SNAPSHOT_DAY - timedelta(days=5)
        self.assertFalse(fill_retention(orphan, "retention_d1"))
        self.assertFalse(DailyMetric.objects.filter(date=orphan).exists())

    def test_day_cut_is_local_timezone(self):
        """23:59:59 算前一天、次日 00:00:01 算次日 —— 专抓「按 UTC 切日」的实现。"""
        day = SNAPSHOT_DAY
        next_day = day + timedelta(days=1)
        long_ago = _local(day - timedelta(days=30))
        a = self._user("13900000500", joined=_local(day, 23, 59, 59))
        b = self._user("13900000501", joined=_local(next_day, 0, 0, 1))
        c = self._user("13900000502", joined=long_ago)
        _at(Swipe, _local(day, 23, 59, 59), swiper=c, target=a, action=SwipeAction.LIKE)
        _at(Swipe, _local(next_day, 0, 0, 1), swiper=c, target=b, action=SwipeAction.LIKE)

        self._run("--date", day.isoformat())
        self._run("--date", next_day.isoformat())

        first = DailyMetric.objects.get(date=day)
        second = DailyMetric.objects.get(date=next_day)
        self.assertEqual((first.new_users, first.swipes_like), (1, 1))
        self.assertEqual((second.new_users, second.swipes_like), (1, 1))

    def test_invalid_arguments_raise_command_error(self):
        """非法日期与 ``--backfill <= 0`` 抛 ``CommandError``(退出码 1)。"""
        with self.assertRaises(CommandError):
            call_command("metrics_daily", "--date", "2026-13-01", stdout=StringIO())
        with self.assertRaises(CommandError):
            call_command("metrics_daily", "--backfill", "0", stdout=StringIO())
        self.assertEqual(DailyMetric.objects.count(), 0)

    def test_messages_from_im_source(self):
        """IM 库读得到时消息量照原样落库。"""
        day = SNAPSHOT_DAY
        with patch("stats.im_source.count_messages", return_value=42):
            self._run("--date", day.isoformat())
        self.assertEqual(DailyMetric.objects.get(date=day).messages, 42)

    def test_match_rate(self):
        """配对率分母为 0 时返回 None,否则返回比值。"""
        row = DailyMetric(date=SNAPSHOT_DAY, swipes_like=0, matches=3)
        self.assertIsNone(match_rate(row))
        row.swipes_like = 4
        self.assertEqual(match_rate(row), 0.75)

    def test_recent_rows_is_newest_first(self):
        """看板用的 ``recent_rows`` 按日期倒序取最近 N 行。"""
        for offset in range(3):
            DailyMetric.objects.create(date=SNAPSHOT_DAY - timedelta(days=offset))
        dates = [row.date for row in recent_rows(2)]
        self.assertEqual(dates, [SNAPSHOT_DAY, SNAPSHOT_DAY - timedelta(days=1)])


class ImSourceTests(TestCase):
    """IM 库只读客户端:DSN 解析(密码含 ``@``)、缺省端口与失败降级。"""

    def test_dsn_with_at_sign_in_password(self):
        """按最后一个 ``@`` 切分,密码里的 ``@`` 不会被当成主机分隔符。"""
        params = im_source._parse_dsn("mysql://u:p@ss@db.example:3307/chatapp_im")
        self.assertEqual(params, {
            "user": "u", "password": "p@ss", "host": "db.example",
            "port": 3307, "database": "chatapp_im",
        })

    def test_dsn_defaults_port(self):
        """没写端口时用 3306。"""
        self.assertEqual(im_source._parse_dsn("mysql://u:p@127.0.0.1/chatapp_im")["port"], 3306)

    def test_dsn_without_at_or_database_raises(self):
        """缺 ``@`` 或库名的 DSN 直接报错(由调用方降级)。"""
        with self.assertRaises(ValueError):
            im_source._parse_dsn("chatapp_im")
        with self.assertRaises(ValueError):
            im_source._parse_dsn("mysql://u:p@127.0.0.1")

    def test_count_messages_none_when_dsn_empty(self):
        """DSN 留空 → None 且不抛异常(消息量显示「无数据」)。"""
        with override_settings(IM_MYSQL_DSN=""):
            self.assertIsNone(im_source.count_messages(SNAPSHOT_DAY))

    def test_count_messages_none_when_connect_fails(self):
        """连不上 → None 且不抛异常(看板不能因为 IM 库挂了整页空白)。"""
        with override_settings(IM_MYSQL_DSN="mysql://u:p@127.0.0.1:3306/chatapp_im"), \
                patch("pymysql.connect", side_effect=RuntimeError("boom")):
            self.assertIsNone(im_source.count_messages(SNAPSHOT_DAY))

    def test_count_messages_returns_count_and_uses_epoch_seconds(self):
        """读到条数就返回;查询参数是 epoch 秒(``created_at`` 是 BIGINT),用完关连接。"""
        cursor = MagicMock()
        cursor.fetchone.return_value = (7,)
        conn = MagicMock()
        conn.cursor.return_value.__enter__.return_value = cursor
        with override_settings(IM_MYSQL_DSN="mysql://u:p@127.0.0.1:3306/chatapp_im"), \
                patch("pymysql.connect", return_value=conn):
            self.assertEqual(im_source.count_messages(SNAPSHOT_DAY), 7)
        bounds = cursor.execute.call_args.args[1]
        self.assertTrue(all(isinstance(bound, int) for bound in bounds))
        conn.close.assert_called_once()
