"""发现页应用的测试:滑卡/配对模型约束、候选池规则、滑卡接口与配对列表。

覆盖场景:
    - 模型约束:同一对用户只能滑一次(反向是另一条)、配对按 id 升序且拒绝重复与逆序;
    - 候选池:排除自己/未完善/无过审照片/已划过/已配对,按偏好过滤,年龄边界含端点,
      只返回已过审照片,``limit`` 默认值与上限,未登录 401;
    - 滑卡:幂等、互喜只建一条配对且只发一次灰条、pass 不配对、入队失败不影响结果、
      不能划自己、目标不存在/未完善/被轻封禁的处理、非法动作、限流;
    - 配对列表:双向都能列出、无过审照片时头像为 null、只列自己的、分页、
      共同标签只返回交集且整页一次批量求交(条数翻倍不增加 SQL);
    - ``dev_reset_pair`` 命令:只清这一对、不动其他对、非法 IM id 报错;
    - 撤销滑卡(批次 O):硬删除、30 秒窗口、已配对/已解除拒绝、候选池复位、轻封禁 403;
    - 每日喜欢额度(批次 O):超限 ``429`` + ``42904``、``pass`` 与重放不占额度、撤销退回、
      默认 ``0`` 时行为与加额度前一致。

文件信息:
    文件名称          discovery/tests.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from datetime import date, timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from moderation.models import Block
from users.models import (Photo, PhotoStatus, Preference, Profile, ProfileStatus,
                           ProfileVisit, Tag)

from .models import Match, Swipe, SwipeAction
from .throttles import VisitsCountThrottle, VisitsThrottle

User = get_user_model()


def _years_ago(today, years):
    """取 ``years`` 年前的今天;2 月 29 日退化成 2 月 28 日。

    参数说明:
        today: 参照日期。
        years: 往前推的年数。

    返回参数:
        推算出的日期。

    使用示例:
        ``_years_ago(timezone.localdate(), 18)``

    备注信息:
        目标年份不是闰年时,2 月 29 日落到 2 月 28 日,不会把 ``ValueError`` 抛给调用方。
    """
    try:
        return date(today.year - years, today.month, today.day)
    except ValueError:      # 2 月 29 日
        return date(today.year - years, today.month, 28)


class SwipeModelTests(TestCase):
    """滑卡模型:``(swiper, target)`` 唯一,反向是另一条记录。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.SwipeModelTests``

    备注信息:
        只建两个用户,断言完全依赖数据库唯一约束,不走接口。 ``test_same_pair_can_only_swipe_once`` 是本类第一个用例,可用它单个复跑。
    """

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``SwipeModelTests().setUp()``

        备注信息:
            只建两个用户,不涉及资料与照片。
        """
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_same_pair_can_only_swipe_once(self):
        """同一对用户第二次滑卡撞唯一约束,抛 ``IntegrityError``。

        参数说明:
            无。
        """
        Swipe.objects.create(swiper=self.a, target=self.b, action=SwipeAction.LIKE)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Swipe.objects.create(swiper=self.a, target=self.b, action=SwipeAction.PASS)

    def test_reverse_direction_is_a_different_swipe(self):
        """反向滑卡是另一条记录,两张行同时存在。

        参数说明:
            无。
        """
        Swipe.objects.create(swiper=self.a, target=self.b, action=SwipeAction.LIKE)
        Swipe.objects.create(swiper=self.b, target=self.a, action=SwipeAction.LIKE)
        self.assertEqual(Swipe.objects.count(), 2)


class MatchModelTests(TestCase):
    """配对模型:按 id 升序存储,重复配对与逆序写入都被约束挡住。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.MatchModelTests``

    备注信息:
        配对行一律用 ``Match.pair_kwargs`` 拼参数,逆序写入由 CHECK 约束拦截。
    """

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``MatchModelTests().setUp()``

        备注信息:
            只建两个用户,配对参数由 ``Match.pair_kwargs`` 拼出。
        """
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_pair_kwargs_orders_by_id(self):
        """``pair_kwargs`` 不论传参顺序都按 id 升序拼出 ``user_a`` / ``user_b``。

        参数说明:
            无。
        """
        self.assertEqual(Match.pair_kwargs(self.b, self.a), {"user_a": self.a, "user_b": self.b})
        self.assertEqual(Match.pair_kwargs(self.a, self.b), {"user_a": self.a, "user_b": self.b})

    def test_duplicate_pair_rejected(self):
        """同一对用户重复建配对抛 ``IntegrityError``。

        参数说明:
            无。
        """
        Match.objects.create(**Match.pair_kwargs(self.a, self.b))
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Match.objects.create(**Match.pair_kwargs(self.b, self.a))

    def test_reversed_order_rejected_by_check_constraint(self):
        """逆序直接写库被 CHECK 约束拦下。

        参数说明:
            无。
        """
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Match.objects.create(user_a=self.b, user_b=self.a)

    def test_other_user(self):
        """``other_user`` 按入参换算出另一方。

        参数说明:
            无。
        """
        match = Match.objects.create(**Match.pair_kwargs(self.a, self.b))
        self.assertEqual(match.other_user(self.a), self.b)
        self.assertEqual(match.other_user(self.b), self.a)


class MatchUnmatchModelTests(TestCase):
    """解除配对是软删除:行还在,但 is_active 变 False。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.MatchUnmatchModelTests``

    备注信息:
        ``is_active`` 是 ``unmatched_at`` 为空的派生属性,改完要 ``refresh_from_db`` 复核。
    """

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``MatchUnmatchModelTests().setUp()``

        备注信息:
            只建两个用户,用例内自己造配对再改解除字段。
        """
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def test_new_match_is_active(self):
        """新建的配对 ``is_active`` 为 ``True`` 且没有解除时间。

        参数说明:
            无。
        """
        match = Match.objects.create(**Match.pair_kwargs(self.a, self.b))
        self.assertIsNone(match.unmatched_at)
        self.assertTrue(match.is_active)

    def test_marked_match_is_inactive(self):
        """写入 ``unmatched_at`` / ``unmatched_by`` 后 ``is_active`` 变 ``False``。

        参数说明:
            无。
        """
        match = Match.objects.create(**Match.pair_kwargs(self.a, self.b))
        match.unmatched_at = timezone.now()
        match.unmatched_by = self.a
        match.save(update_fields=["unmatched_at", "unmatched_by"])
        match.refresh_from_db()
        self.assertFalse(match.is_active)
        self.assertEqual(match.unmatched_by, self.a)


class CandidateTests(APITestCase):
    """候选池:排除规则、偏好过滤、年龄边界、照片过滤与分页上限。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.CandidateTests``

    备注信息:
        用 ``RefreshToken.for_user`` 直接签发凭证;``_make_user`` 负责造合格用户。
    """

    URL = "/api/v1/discovery/candidates"

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``CandidateTests().setUp()``

        备注信息:
            ``self.me`` 是男性、上海、资料完善;登录凭证用 ``RefreshToken.for_user`` 直接签发。
        """
        self.me = self._make_user("13800138000", gender="male", birthday="2000-01-01", city="上海")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, gender="female", birthday="2000-01-01", city="上海", complete=True):
        """造一个用户,可选地补齐资料并加一张已过审照片。

        参数说明:
            phone: 手机号,同时用作昵称。
            gender: 性别,默认 ``female``。
            birthday: 生日,默认 ``2000-01-01``。
            city: 城市,默认 ``上海``。
            complete: 为 ``True`` 时资料置为完善并附一张已过审照片。

        返回参数:
            新建的用户实例。

        使用示例:
            ``self._make_user("13900139000", gender="female", complete=False)``

        备注信息:
            昵称直接取手机号;``complete=False`` 时状态停在 ``ProfileStatus.INCOMPLETE`` 且不加照片。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(
            user=user, nickname=phone, gender=gender, birthday=birthday, city=city, bio="你好",
            status=ProfileStatus.COMPLETE if complete else ProfileStatus.INCOMPLETE,
        )
        if complete:
            Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def _ids(self, resp):
        """从候选响应里取出 ``user_id`` 列表。

        参数说明:
            resp: 接口响应。

        返回参数:
            候选人的账号 id 列表,保持响应顺序。

        使用示例:
            ``self._ids(self.client.get(self.URL))``

        备注信息:
            候选接口返回的是裸数组,不是分页信封。
        """
        return [item["user_id"] for item in resp.json()]

    def test_excludes_self_incomplete_and_no_photo(self):
        """排除自己、资料未完善与没有过审照片的人,只留合格候选。

        参数说明:
            无。
        """
        other = self._make_user("13900139000")
        self._make_user("13900139001", complete=False)
        self._make_user("13900139002")
        Photo.objects.filter(user__phone="13900139002").delete()          # 抽掉照片
        Profile.objects.filter(user__phone="13900139002").update(status=ProfileStatus.COMPLETE)
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), [other.id])

    def test_excludes_swiped_and_matched(self):
        """划过与已配对的人都不再进候选池。

        参数说明:
            无。
        """
        swiped = self._make_user("13900139000")
        matched = self._make_user("13900139001")
        fresh = self._make_user("13900139002")
        Swipe.objects.create(swiper=self.me, target=swiped, action=SwipeAction.PASS)
        Match.objects.create(**Match.pair_kwargs(self.me, matched))
        self.assertEqual(self._ids(self.client.get(self.URL)), [fresh.id])

    def test_filters_by_preference(self):
        """按偏好的性别、年龄区间与城市过滤。

        参数说明:
            无。
        """
        Preference.objects.create(profile=self.me.profile, target_gender="female",
                                  age_min=25, age_max=30, city="上海")
        ok = self._make_user("13900139000", gender="female", birthday="1998-01-01", city="上海")   # 28 岁
        self._make_user("13900139001", gender="male", birthday="1998-01-01")        # 性别不符
        self._make_user("13900139002", gender="female", birthday="2005-01-01")      # 太年轻
        self._make_user("13900139003", gender="female", birthday="1990-01-01")      # 太大
        self._make_user("13900139004", gender="female", birthday="1998-01-01", city="北京")  # 城市不符
        self.assertEqual(self._ids(self.client.get(self.URL)), [ok.id])

    def test_age_boundaries_are_inclusive(self):
        """年龄区间两端都算命中,多或少一岁即被排除。

        参数说明:
            无。
        """
        today = timezone.localdate()
        Preference.objects.create(profile=self.me.profile, age_min=18, age_max=30)
        exactly_18 = self._make_user("13900139000", birthday=_years_ago(today, 18))
        exactly_30 = self._make_user("13900139001", birthday=_years_ago(today, 30))
        self._make_user("13900139002", birthday=_years_ago(today, 31))   # 31 岁
        self._make_user("13900139003", birthday=_years_ago(today, 17))   # 17 岁
        self.assertEqual(sorted(self._ids(self.client.get(self.URL))), sorted([exactly_18.id, exactly_30.id]))

    def test_without_preference_returns_everyone_eligible(self):
        """没有偏好设置时返回所有符合准入条件的人。

        参数说明:
            无。
        """
        Preference.objects.filter(profile=self.me.profile).delete()
        a = self._make_user("13900139000", gender="female", birthday="2005-01-01", city="北京")
        b = self._make_user("13900139001", gender="male", birthday="1980-01-01", city="广州")
        self.assertEqual(sorted(self._ids(self.client.get(self.URL))), sorted([a.id, b.id]))

    def test_only_approved_photos_returned(self):
        """候选卡片只带已过审照片,待审的不会出现。

        参数说明:
            无。
        """
        ghost = self._make_user("13900139000")
        Photo.objects.create(user=ghost, file="photos/pending.png", status=PhotoStatus.PENDING)
        data = self.client.get(self.URL).json()
        self.assertEqual(len(data), 1)
        self.assertTrue(all(p["status"] == "approved" for p in data[0]["photos"]))

    def test_limit_default_and_cap(self):
        """``limit`` 默认 10、上限 20,候选不足时有多少给多少。

        参数说明:
            无。
        """
        for i in range(12):
            self._make_user(f"1390013{i:04d}")
        self.assertEqual(len(self.client.get(self.URL).json()), 10)
        self.assertEqual(len(self.client.get(f"{self.URL}?limit=3").json()), 3)
        self.assertEqual(len(self.client.get(f"{self.URL}?limit=99").json()), 12)   # 上限 20,但只有 12 个人

    def test_invalid_limit_is_400_and_negative_is_clamped(self):
        """``limit=abc`` 返回 400;``limit=-1`` 收敛到 1,不再触发 500(M10)。

        参数说明:
            无。
        """
        self.assertEqual(self.client.get(f"{self.URL}?limit=abc").status_code, 400)
        self.assertEqual(self.client.get(f"{self.URL}?limit=-1").status_code, 200)

    def test_candidates_throttled(self):
        """候选池按用户限流,超限返回 429(M7)。

        参数说明:
            无。
        """
        from .throttles import CandidateThrottle

        cache.clear()
        with patch.object(CandidateThrottle, "rate", "2/hour", create=True):
            self.assertEqual(self.client.get(self.URL).status_code, 200)
            self.assertEqual(self.client.get(self.URL).status_code, 200)
            self.assertEqual(self.client.get(self.URL).status_code, 429)

    def test_requires_auth(self):
        """未登录访问候选池返回 401。

        参数说明:
            无。
        """
        self.client.credentials()
        self.assertEqual(self.client.get(self.URL).status_code, 401)


class CandidateShuffleTests(APITestCase):
    """候选池排序(M7):走 ``shuffle_key`` 索引取池再抽样,不再 ORDER BY RAND()。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.CandidateShuffleTests``

    备注信息:
        ``CaptureQueriesContext`` 抓真实 SQL,``patch`` 换掉 ``random.sample`` 断言入参。
    """

    URL = "/api/v1/discovery/candidates"

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``CandidateShuffleTests().setUp()``

        备注信息:
            ``self.me`` 是男性、上海;登录凭证直接写进 ``client.credentials``。
        """
        self.me = self._make_user("13800138000", gender="male", city="上海")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, gender="female", city="上海"):
        """造一个资料完善、带一张已过审照片的用户。

        参数说明:
            phone: 手机号,同时用作昵称。
            gender: 性别,默认 ``female``。
            city: 城市,默认 ``上海``。

        返回参数:
            新建的用户实例。

        使用示例:
            ``self._make_user("13900139000", city="北京")``

        备注信息:
            生日固定 ``2000-01-01``,资料状态直接置为 ``ProfileStatus.COMPLETE``。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(
            user=user, nickname=phone, gender=gender, birthday="2000-01-01", city=city,
            bio="你好", status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def test_candidates_do_not_use_random_ordering(self):
        """查询里出现的是 ``shuffle_key``,不是 RAND()/RANDOM()。

        参数说明:
            无。
        """
        self._make_user("13900139000")
        with CaptureQueriesContext(connection) as queries:
            self.assertEqual(self.client.get(self.URL).status_code, 200)
        sql = " ".join(query["sql"] for query in queries.captured_queries).upper()
        self.assertIn("SHUFFLE_KEY", sql)
        self.assertNotIn("RAND", sql)

    def test_pool_is_capped_then_sampled(self):
        """先按 ``CANDIDATE_POOL_SIZE`` 截断池子,再在池内抽样(不是全表排序)。

        参数说明:
            无。
        """
        users = []
        for index in range(6):
            user = self._make_user(f"1390013900{index}")
            Profile.objects.filter(user=user).update(shuffle_key=index)
            users.append(user)
        with self.settings(CANDIDATE_POOL_SIZE=4):
            with patch("discovery.views.random.sample",
                       side_effect=lambda seq, count: seq[:count]) as sample:
                data = self.client.get(f"{self.URL}?limit=2").json()
        sample.assert_called_once()
        self.assertEqual(len(sample.call_args.args[0]), 4)     # 池子被截到 4 条
        self.assertEqual(sample.call_args.args[1], 2)          # 本次只要 2 张
        self.assertEqual([item["user_id"] for item in data], [user.id for user in users[:2]])


class RefreshShuffleKeysCommandTests(TestCase):
    """``refresh_shuffle_keys``:轮换全部资料的随机键,dry-run 不写库。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.RefreshShuffleKeysCommandTests``

    备注信息:
        ``setUp`` 把三条资料的 ``shuffle_key`` 统一置 0,模拟升级前共用一个键。
    """

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``RefreshShuffleKeysCommandTests().setUp()``

        备注信息:
            造三个资料并把 ``shuffle_key`` 统一置 0,模拟升级前共用一个键的状态。
        """
        self.users = [User.objects.create_user(phone=f"1380013800{index}") for index in range(3)]
        for index, user in enumerate(self.users):
            Profile.objects.create(user=user, nickname=f"u{index}")
        Profile.objects.update(shuffle_key=0)   # 模拟「升级前所有人同一个 key」

    def test_rotates_all_keys(self):
        """命令跑完所有资料的 ``shuffle_key`` 都被换掉且彼此不同。

        参数说明:
            无。
        """
        call_command("refresh_shuffle_keys", stdout=StringIO())
        keys = list(Profile.objects.values_list("shuffle_key", flat=True))
        self.assertTrue(all(key != 0 for key in keys))
        self.assertEqual(len(set(keys)), 3)

    def test_dry_run_does_not_write(self):
        """``--dry-run`` 只统计不落库,键值保持原样。

        参数说明:
            无。
        """
        call_command("refresh_shuffle_keys", "--dry-run", stdout=StringIO())
        self.assertEqual(set(Profile.objects.values_list("shuffle_key", flat=True)), {0})


class SwipeApiTests(APITestCase):
    """滑卡接口:幂等、互喜配对与通知、各类拒绝分支、限流。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.SwipeApiTests``

    备注信息:
        ``setUp`` 必须 ``cache.clear()``:限流计数在缓存里,不清会串用例。
    """

    URL = "/api/v1/discovery/swipe"

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``SwipeApiTests().setUp()``

        备注信息:
            先 ``cache.clear()`` 再建一男一女两个用户并登录,``addCleanup`` 保证用例结束后再清一次缓存。
        """
        cache.clear()               # 限流计数存在缓存里,测试之间必须清
        self.addCleanup(cache.clear)
        self.me = self._make_user("13800138000", gender="male")
        self.target = self._make_user("13900139000", gender="female")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, gender="female"):
        """造一个资料完善、带已过审照片的用户。

        参数说明:
            phone: 手机号,同时用作昵称。
            gender: 性别,默认 ``female``。

        返回参数:
            新建的用户实例。

        使用示例:
            ``self._make_user("13900139000", gender="female")``

        备注信息:
            生日与城市固定为 ``2000-01-01`` / ``上海``,资料状态置为 ``ProfileStatus.COMPLETE``。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=phone, gender=gender, birthday="2000-01-01",
                               city="上海", bio="你好", status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def swipe(self, target_id, action="like"):
        """提交一次滑卡。

        参数说明:
            target_id: 目标账号 id。
            action: ``like`` 或 ``pass``,默认 ``like``。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self.swipe(self.target.id, action="pass")``

        备注信息:
            请求体按 JSON 提交,打的是 ``/api/v1/discovery/swipe``。
        """
        return self.client.post(self.URL, {"target_user_id": target_id, "action": action}, format="json")

    def test_like_creates_swipe(self):
        """喜欢一次落一条 ``Swipe``,响应 ``matched`` 为 ``False``。

        参数说明:
            无。
        """
        resp = self.swipe(self.target.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"matched": False, "shared_tags": []})
        self.assertTrue(Swipe.objects.filter(swiper=self.me, target=self.target,
                                             action=SwipeAction.LIKE).exists())

    def test_repeat_swipe_is_idempotent(self):
        """重复滑同一个人仍是 200,库里只有一条记录。

        参数说明:
            无。
        """
        self.swipe(self.target.id)
        resp = self.swipe(self.target.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Swipe.objects.count(), 1)

    def test_blocked_target_cannot_be_swiped(self):
        """对方拉黑我后,我不能再对他滑卡,也不能生成配对(M11)。

        参数说明:
            无。
        """
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        Block.objects.create(blocker=self.target, blocked=self.me)
        resp = self.swipe(self.target.id)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(Swipe.objects.filter(swiper=self.me).count(), 0)
        self.assertEqual(Match.objects.count(), 0)

    def test_mutual_like_creates_one_match(self):
        """互喜只建一条配对,按 ``(user_a, user_b)`` 升序落库并只发一次灰条。

        参数说明:
            无。
        """
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        with patch("im.tasks.send_match_notice.delay") as notice:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.swipe(self.target.id)
        self.assertEqual(resp.json(), {"matched": True, "shared_tags": []})
        self.assertEqual(Match.objects.count(), 1)
        self.assertEqual(Match.objects.first().user_a, self.me)
        notice.assert_called_once_with(self.me.id, self.target.id)

    def test_mutual_like_after_match_does_not_resend_notice(self):
        """已配对的重复滑卡仍回 ``matched=True``,但不再重复发通知。

        参数说明:
            无。
        """
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        with patch("im.tasks.send_match_notice.delay") as notice:
            with self.captureOnCommitCallbacks(execute=True):
                self.swipe(self.target.id)
                again = self.swipe(self.target.id)
        self.assertEqual(again.json(), {"matched": True, "shared_tags": []})
        self.assertEqual(notice.call_count, 1)

    def test_pass_never_matches(self):
        """``pass`` 即使对方已喜欢我也不产生配对。

        参数说明:
            无。
        """
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        resp = self.swipe(self.target.id, action="pass")
        self.assertEqual(resp.json(), {"matched": False, "shared_tags": []})
        self.assertEqual(Match.objects.count(), 0)

    def test_match_returns_shared_tags(self):
        """配对成功时直接带回共同标签,客户端不必再拉一次资料(避免被记成访客)。

        参数说明:
            无。
        """
        tags = list(Tag.objects.order_by("id")[:3])
        self.me.profile.tags.set([tags[0], tags[1]])
        self.target.profile.tags.set([tags[1], tags[2]])
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        with patch("im.tasks.send_match_notice.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.swipe(self.target.id)
        self.assertEqual(resp.json()["matched"], True)
        self.assertEqual([tag["id"] for tag in resp.json()["shared_tags"]], [tags[1].id])

    def test_shared_tags_empty_when_no_overlap(self):
        """没有交集时是空数组,不是 null。

        参数说明:
            无。
        """
        tags = list(Tag.objects.order_by("id")[:2])
        self.me.profile.tags.set([tags[0]])
        self.target.profile.tags.set([tags[1]])
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        with patch("im.tasks.send_match_notice.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.swipe(self.target.id)
        self.assertEqual(resp.json()["shared_tags"], [])

    def test_enqueue_failure_does_not_break_swipe(self):
        """Celery 入队抛异常也不影响滑卡结果,``robust=True`` 把异常兜住。

        参数说明:
            无。
        """
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        with patch("im.tasks.send_match_notice.delay", side_effect=Exception("broker down")):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.swipe(self.target.id)
        self.assertEqual(resp.status_code, 200)   # robust=True 兜住,配对结果不受影响
        self.assertEqual(resp.json(), {"matched": True, "shared_tags": []})

    def test_cannot_swipe_self(self):
        """划自己返回 400。

        参数说明:
            无。
        """
        self.assertEqual(self.swipe(self.me.id).status_code, 400)

    def test_unknown_target_returns_404(self):
        """目标账号不存在返回 404。

        参数说明:
            无。
        """
        self.assertEqual(self.swipe(999999).status_code, 404)

    def test_incomplete_target_rejected(self):
        """目标资料未完善返回 400。

        参数说明:
            无。
        """
        loner = User.objects.create_user(phone="13900139001")
        Profile.objects.create(user=loner, status=ProfileStatus.INCOMPLETE)
        self.assertEqual(self.swipe(loner.id).status_code, 400)

    def test_banned_light_cannot_swipe(self):
        """被轻封禁不能滑卡,返回 403 且不留滑卡记录。

        参数说明:
            无。
        """
        Profile.objects.filter(user=self.me).update(status=ProfileStatus.BANNED_LIGHT)
        resp = self.swipe(self.target.id)
        self.assertEqual(resp.status_code, 403)
        self.assertFalse(Swipe.objects.exists())

    def test_invalid_action_rejected(self):
        """非法动作值返回 400。

        参数说明:
            无。
        """
        self.assertEqual(self.swipe(self.target.id, action="hug").status_code, 400)

    def test_swipe_throttled(self):
        """滑卡按用户限流,超限返回 429。

        参数说明:
            无。
        """
        from discovery.throttles import SwipeThrottle
        with patch.object(SwipeThrottle, "rate", "2/hour", create=True):
            self.assertEqual(self.swipe(self.target.id).status_code, 200)
            self.assertEqual(self.swipe(self.target.id).status_code, 200)
            self.assertEqual(self.swipe(self.target.id).status_code, 429)


class MatchListTests(APITestCase):
    """配对列表:双向可见、头像降级、只看自己的、分页与鉴权。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.MatchListTests``

    备注信息:
        默认游标分页(``count`` / ``next_cursor`` / ``has_more``),带 ``offset`` 才退回老结构。
    """

    URL = "/api/v1/matches"

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``MatchListTests().setUp()``

        备注信息:
            只建 ``self.me`` 并登录,配对对象留给各用例自己造。
        """
        self.me = self._make_user("13800138000")
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, nickname=None, with_photo=True):
        """造一个资料完善的用户,可选是否带已过审照片。

        参数说明:
            phone: 手机号。
            nickname: 昵称;``None`` 表示用手机号。
            with_photo: 是否加一张已过审照片,默认 ``True``。

        返回参数:
            新建的用户实例。

        使用示例:
            ``self._make_user("13900139000", nickname="小红", with_photo=False)``

        备注信息:
            性别、生日、城市固定,资料状态置为 ``ProfileStatus.COMPLETE``。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=nickname or phone, gender="female",
                               birthday="2000-01-01", city="上海", bio="你好",
                               status=ProfileStatus.COMPLETE)
        if with_photo:
            Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def test_lists_both_sides(self):
        """配对的双方都能看到对方,字段含 ``im_user_id`` 与头像地址。

        参数说明:
            无。
        """
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
        """对方没有过审照片时 ``avatar_url`` 是 ``null``。

        参数说明:
            无。
        """
        other = self._make_user("13900139000", with_photo=False)
        Match.objects.create(**Match.pair_kwargs(self.me, other))
        self.assertIsNone(self.client.get(self.URL).json()["results"][0]["avatar_url"])

    def test_only_my_matches(self):
        """列表只出现自己的配对。

        参数说明:
            无。
        """
        other = self._make_user("13900139000")
        stranger_a = self._make_user("13900139001")
        stranger_b = self._make_user("13900139002")
        Match.objects.create(**Match.pair_kwargs(self.me, other))
        Match.objects.create(**Match.pair_kwargs(stranger_a, stranger_b))
        data = self.client.get(self.URL).json()
        self.assertEqual([item["user_id"] for item in data["results"]], [other.id])

    def test_pagination_by_cursor(self):
        """游标分页翻完不重不漏,``has_more`` 随之变化。

        参数说明:
            无。
        """
        others = [self._make_user(f"1390013910{i}") for i in range(3)]
        for other in others:
            Match.objects.create(**Match.pair_kwargs(self.me, other))
        first = self.client.get(self.URL, {"limit": 2}).json()
        self.assertEqual(first["count"], 3)
        self.assertEqual(len(first["results"]), 2)
        self.assertTrue(first["has_more"])
        second = self.client.get(self.URL,
                                 {"limit": 2, "before": first["next_cursor"]}).json()
        self.assertEqual(len(second["results"]), 1)
        self.assertFalse(second["has_more"])
        ids = [item["user_id"] for item in first["results"] + second["results"]]
        self.assertEqual(sorted(ids), sorted(other.id for other in others))   # 翻页不重不漏

    def test_offset_request_keeps_legacy_shape(self):
        """老客户端仍带 offset:响应退回 count/next/previous/results。

        参数说明:
            无。
        """
        others = [self._make_user(f"1390013910{i}") for i in range(3)]
        for other in others:
            Match.objects.create(**Match.pair_kwargs(self.me, other))
        first = self.client.get(self.URL, {"limit": 2, "offset": 0}).json()
        self.assertEqual(len(first["results"]), 2)
        self.assertIsNotNone(first["next"])
        self.assertEqual(len(self.client.get(self.URL,
                                             {"limit": 2, "offset": 2}).json()["results"]), 1)

    def test_invalid_cursor_is_400(self):
        """游标坏了给 400 + 统一错误信封(不许漏成 500)。

        参数说明:
            无。
        """
        response = self.client.get(self.URL, {"limit": 2, "before": "bogus"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 400)

    def test_requires_auth(self):
        """未登录访问配对列表返回 401。

        参数说明:
            无。
        """
        self.client.credentials()
        self.assertEqual(self.client.get(self.URL).status_code, 401)

    def test_shared_tags_is_intersection(self):
        """共同标签只返回交集,按 id 升序;没有交集的人给空数组。

        参数说明:
            无。
        """
        tags = list(Tag.objects.order_by("id")[:3])
        overlap = self._make_user("13900139000")
        overlap.profile.tags.set([tags[0], tags[1]])
        self.me.profile.tags.set([tags[1], tags[2]])
        no_overlap = self._make_user("13900139001")
        no_overlap.profile.tags.set([tags[0]])
        Match.objects.create(**Match.pair_kwargs(self.me, overlap))
        Match.objects.create(**Match.pair_kwargs(self.me, no_overlap))
        by_user = {item["user_id"]: item["shared_tags"]
                   for item in self.client.get(self.URL).json()["results"]}
        self.assertEqual([tag["id"] for tag in by_user[overlap.id]], [tags[1].id])
        self.assertEqual(by_user[overlap.id][0]["name"], tags[1].name)
        self.assertEqual(by_user[no_overlap.id], [])

    def test_shared_tags_query_count_does_not_grow(self):
        """共同标签是整页一次批量求交:配对条数翻倍不增加 SQL 条数。

        参数说明:
            无。
        """
        tags = list(Tag.objects.order_by("id")[:3])
        self.me.profile.tags.set(tags)
        first = self._make_user("13900139000")
        first.profile.tags.set(tags)
        Match.objects.create(**Match.pair_kwargs(self.me, first))
        self.client.get(self.URL)   # 预热:首次请求会懒创建 Preference 等一次性查询
        with CaptureQueriesContext(connection) as one_match:
            self.client.get(self.URL)
        second = self._make_user("13900139001")
        second.profile.tags.set(tags)
        Match.objects.create(**Match.pair_kwargs(self.me, second))
        with CaptureQueriesContext(connection) as two_matches:
            self.client.get(self.URL)
        self.assertEqual(len(one_match.captured_queries), len(two_matches.captured_queries))


class DevResetPairCommandTests(TestCase):
    """开发手测用:把一对用户的滑卡/配对记录清掉,好重演「互喜 → 配对」。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.DevResetPairCommandTests``

    备注信息:
        命令参数是 IM id 字符串(``u<id>``),``_seed`` 先造双向滑卡与一条配对。
    """

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``DevResetPairCommandTests().setUp()``

        备注信息:
            建两个用户留作 ``self.a`` / ``self.b``,滑卡与配对记录交给 ``_seed``。
        """
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")

    def _seed(self):
        """给这一对用户造出双向滑卡与一条配对记录。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self._seed()``

        备注信息:
            一条 like、一条 pass、一条配对,正好覆盖命令要清的三类行。
        """
        Swipe.objects.create(swiper=self.a, target=self.b, action=SwipeAction.LIKE)
        Swipe.objects.create(swiper=self.b, target=self.a, action=SwipeAction.PASS)
        Match.objects.create(**Match.pair_kwargs(self.a, self.b))

    def test_clears_swipes_and_match_between_the_pair(self):
        """命令跑完这一对的滑卡与配对都没了。

        参数说明:
            无。
        """
        self._seed()

        call_command("dev_reset_pair", a=f"u{self.a.id}", b=f"u{self.b.id}")

        self.assertFalse(Swipe.objects.exists())
        self.assertFalse(Match.objects.exists())

    def test_leaves_other_pairs_alone(self):
        """只清指定的一对,我与别人的滑卡不受影响。

        参数说明:
            无。
        """
        self._seed()
        other = User.objects.create_user(phone="13900139001")
        Swipe.objects.create(swiper=self.a, target=other, action=SwipeAction.LIKE)

        call_command("dev_reset_pair", a=f"u{self.a.id}", b=f"u{self.b.id}")

        self.assertEqual(Swipe.objects.count(), 1)
        self.assertTrue(Swipe.objects.filter(swiper=self.a, target=other).exists())

    def test_unknown_im_id_raises(self):
        """IM id 查不到用户时命令抛 ``CommandError``。

        参数说明:
            无。
        """
        with self.assertRaises(CommandError):
            call_command("dev_reset_pair", a="u99999", b=f"u{self.b.id}")

    def test_same_id_raises(self):
        """两端传同一个 IM id 时命令抛 ``CommandError``。

        参数说明:
            无。
        """
        with self.assertRaises(CommandError):
            call_command("dev_reset_pair", a=f"u{self.a.id}", b=f"u{self.a.id}")

class LikesReceivedTests(APITestCase):
    """喜欢我的人:口径、排序、分页、计数、权限与字段脱敏。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.LikesReceivedTests``

    备注信息:
        列表与计数共用同一套过滤;``_like_me`` 造「对方喜欢我」的记录。
    """

    URL = "/api/v1/discovery/likes"
    COUNT_URL = "/api/v1/discovery/likes/count"

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``LikesReceivedTests().setUp()``

        备注信息:
            ``self.me`` 是男性并登录;「对方喜欢我」的记录由各用例用 ``_like_me`` 造。
        """
        self.me = self._make_user("13800138000", gender="male")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, gender="female", birthday="2000-01-01",
                   city="上海", complete=True, photo=True, status=None):
        """造一个用户;默认资料完善并带一张已过审照片。

        参数说明:
            phone: 手机号,同时用作昵称。
            gender: 性别,默认 ``female``。
            birthday: 生日,默认 ``2000-01-01``;``None`` 表示未填。
            city: 城市,默认 ``上海``。
            complete: 是否把资料置为完善,默认 ``True``。
            photo: 是否加一张已过审照片,默认 ``True``。
            status: 显式指定资料状态,用于封禁场景。

        返回参数:
            新建的用户实例。

        使用示例:
            ``self._make_user("13900139002", status=ProfileStatus.BANNED_LIGHT)``

        备注信息:
            ``status`` 优先于 ``complete``:传了它就不再按 ``complete`` 推默认状态。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(
            user=user, nickname=phone, gender=gender, birthday=birthday, city=city,
            bio="你好",
            status=status or (ProfileStatus.COMPLETE if complete else ProfileStatus.INCOMPLETE),
        )
        if photo:
            Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def _like_me(self, user):
        """让对方喜欢我。

        参数说明:
            user: 发起喜欢的用户。

        返回参数:
            无返回值。

        使用示例:
            ``self._like_me(a)``

        备注信息:
            直接造一条 ``Swipe`` 行而不走接口,便于控制先后顺序与被测数据。
        """
        Swipe.objects.create(swiper=user, target=self.me, action=SwipeAction.LIKE)

    def _ids(self, resp):
        """取出列表响应里的 ``user_id``。

        参数说明:
            resp: 接口响应。

        返回参数:
            user_id 列表,保持响应顺序。

        使用示例:
            ``self._ids(self.client.get(self.URL))``

        备注信息:
            读的是分页信封里的 ``results``。
        """
        return [item["user_id"] for item in resp.json()["results"]]

    def test_lists_only_incoming_likes(self):
        """只列别人喜欢我的,我 ``pass`` 掉的人不出现。

        参数说明:
            无。
        """
        a = self._make_user("13900139000")
        b = self._make_user("13900139001")
        self._like_me(a)
        Swipe.objects.create(swiper=b, target=self.me, action=SwipeAction.PASS)
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), [a.id])

    def test_excludes_people_i_already_swiped(self):
        """我已经划过的人从列表里消失。

        参数说明:
            无。
        """
        a = self._make_user("13900139000")
        self._like_me(a)
        Swipe.objects.create(swiper=self.me, target=a, action=SwipeAction.PASS)
        self.assertEqual(self._ids(self.client.get(self.URL)), [])

    def test_matched_people_disappear(self):
        """回喜欢后配对成立,对方便从「喜欢我的人」里移走。

        参数说明:
            无。
        """
        a = self._make_user("13900139000")
        self._like_me(a)
        self.assertEqual(self._ids(self.client.get(self.URL)), [a.id])
        self.client.post("/api/v1/discovery/swipe",
                         {"target_user_id": a.id, "action": "like"}, format="json")
        self.assertTrue(Match.objects.filter(**Match.pair_kwargs(self.me, a)).exists())
        self.assertEqual(self._ids(self.client.get(self.URL)), [])

    def test_excludes_blocked_both_ways(self):
        """双向拉黑都过滤:我拉黑对方、对方拉黑我都算。

        参数说明:
            无。
        """
        a = self._make_user("13900139000")
        b = self._make_user("13900139001")
        self._like_me(a)
        self._like_me(b)
        Block.objects.create(blocker=self.me, blocked=a)
        Block.objects.create(blocker=b, blocked=self.me)
        self.assertEqual(self._ids(self.client.get(self.URL)), [])

    def test_excludes_incomplete_no_photo_and_banned(self):
        """资料未完善、无过审照片、轻/重封禁的人都不进列表。

        参数说明:
            无。
        """
        users = [
            self._make_user("13900139000", complete=False),
            self._make_user("13900139001", photo=False),
            self._make_user("13900139002", status=ProfileStatus.BANNED_LIGHT),
            self._make_user("13900139003", status=ProfileStatus.BANNED_HEAVY),
        ]
        for user in users:
            self._like_me(user)
        self.assertEqual(self._ids(self.client.get(self.URL)), [])

    def test_newest_like_first(self):
        """按喜欢时间倒序,最新的在前。

        参数说明:
            无。
        """
        a = self._make_user("13900139000")
        b = self._make_user("13900139001")
        self._like_me(a)
        self._like_me(b)
        self.assertEqual(self._ids(self.client.get(self.URL)), [b.id, a.id])

    def test_pagination_by_cursor(self):
        """游标分页翻完不重不漏。

        参数说明:
            无。
        """
        users = [self._make_user(f"1390013900{i}") for i in range(3)]
        for user in users:
            self._like_me(user)
        first = self.client.get(self.URL, {"limit": 2}).json()
        self.assertEqual(first["count"], 3)
        self.assertEqual(len(first["results"]), 2)
        self.assertTrue(first["has_more"])
        second = self.client.get(self.URL,
                                 {"limit": 2, "before": first["next_cursor"]}).json()
        self.assertEqual(len(second["results"]), 1)
        self.assertFalse(second["has_more"])
        ids = [item["user_id"] for item in first["results"] + second["results"]]
        self.assertEqual(sorted(ids), sorted(user.id for user in users))   # 翻页不重不漏

    def test_cursor_ignores_new_like_between_pages(self):
        """翻页期间又有人喜欢我:第二页不重复第 1 页的行(换成 offset 就会重复)。

        参数说明:
            无。
        """
        users = [self._make_user(f"1390013900{i}") for i in range(4)]
        for user in users[:3]:
            self._like_me(user)
        first = self.client.get(self.URL, {"limit": 2}).json()
        self._like_me(users[3])
        second = self.client.get(self.URL,
                                 {"limit": 2, "before": first["next_cursor"]}).json()
        first_ids = [item["user_id"] for item in first["results"]]
        second_ids = [item["user_id"] for item in second["results"]]
        self.assertFalse(set(first_ids) & set(second_ids))
        self.assertEqual(len(first_ids + second_ids), 3)

    def test_offset_request_keeps_legacy_shape(self):
        """老客户端仍带 offset:响应退回 count/next/previous/results。

        参数说明:
            无。
        """
        users = [self._make_user(f"1390013900{i}") for i in range(3)]
        for user in users:
            self._like_me(user)
        first = self.client.get(self.URL, {"limit": 2, "offset": 0}).json()
        self.assertEqual(len(first["results"]), 2)
        self.assertIsNotNone(first["next"])
        self.assertEqual(len(self.client.get(self.URL,
                                             {"limit": 2, "offset": 2}).json()["results"]), 1)

    def test_count_uses_same_rules(self):
        """计数接口与列表接口同一套过滤规则。

        参数说明:
            无。
        """
        a = self._make_user("13900139000")
        b = self._make_user("13900139001")
        self._like_me(a)
        self._like_me(b)
        Block.objects.create(blocker=self.me, blocked=b)
        self.assertEqual(self.client.get(self.COUNT_URL).json(), {"count": 1})
        self.assertEqual(self.client.get(self.URL).json()["count"], 1)

    def test_requires_auth(self):
        """未登录访问「喜欢我的人」返回 401。

        参数说明:
            无。
        """
        self.client.credentials()
        self.assertEqual(self.client.get(self.URL).status_code, 401)

    def test_heavy_banned_forbidden(self):
        """重封禁访问返回 403。

        参数说明:
            无。
        """
        self.me.profile.status = ProfileStatus.BANNED_HEAVY
        self.me.profile.save(update_fields=["status"])
        self.assertEqual(self.client.get(self.URL).status_code, 403)

    def test_light_banned_can_read(self):
        """轻封禁仍可读列表,返回 200。

        参数说明:
            无。
        """
        self.me.profile.status = ProfileStatus.BANNED_LIGHT
        self.me.profile.save(update_fields=["status"])
        self.assertEqual(self.client.get(self.URL).status_code, 200)

    def test_serializer_hides_private_fields_and_filters_photos(self):
        """序列化器隐藏手机号等隐私字段,照片只留已过审的。

        参数说明:
            无。
        """
        a = self._make_user("13900139000")
        Photo.objects.create(user=a, file="photos/pending.png", status=PhotoStatus.PENDING)
        self._like_me(a)
        item = self.client.get(self.URL).json()["results"][0]
        self.assertEqual(item["im_user_id"], f"u{a.id}")
        self.assertIn("liked_at", item)
        for hidden in ("phone", "birthday", "ban_reason", "missing_fields"):
            self.assertNotIn(hidden, item)
        self.assertEqual([photo["status"] for photo in item["photos"]], ["approved"])

    def test_age_is_null_when_birthday_missing(self):
        """对方没填生日时 ``age`` 是 ``null``。

        参数说明:
            无。
        """
        a = self._make_user("13900139000", birthday=None)
        self._like_me(a)
        self.assertIsNone(self.client.get(self.URL).json()["results"][0]["age"])


class UnmatchApiTests(APITestCase):
    """解除配对:204 幂等、列表过滤、滑卡不复活、IM 双向拉黑入队。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.UnmatchApiTests``

    备注信息:
        ``setUp`` 预置一对已配对用户,统一打 ``DELETE /api/v1/matches/{id}``。
    """

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``UnmatchApiTests().setUp()``

        备注信息:
            预置一对已配对用户(我 / 小红)并登录,``self.match`` 供各用例改解除字段。
        """
        self.me = self._make_user("13800138000", "我")
        self.other = self._make_user("13900139000", "小红")
        self.match = Match.objects.create(**Match.pair_kwargs(self.me, self.other))
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, nickname):
        """造一个资料完善的用户(带一张已过审照片)。

        参数说明:
            phone: 手机号。
            nickname: 昵称。

        返回参数:
            新建的用户实例。

        使用示例:
            ``self._make_user("13900139000", "小红")``

        备注信息:
            性别、生日、城市固定,资料状态置为 ``ProfileStatus.COMPLETE``。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=nickname, gender="female",
                               birthday="2000-01-01", city="上海", bio="你好",
                               status=ProfileStatus.COMPLETE)
        Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def test_unmatch_marks_row_and_enqueues_im(self):
        """解除配对写 ``unmatched_at`` / ``unmatched_by`` 并按 user_id 入队 IM 拉黑。

        参数说明:
            无。
        """
        with patch("im.tasks.unmatch_blacklist.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.delete(f"/api/v1/matches/{self.other.id}")
        self.assertEqual(resp.status_code, 204)
        self.match.refresh_from_db()
        self.assertIsNotNone(self.match.unmatched_at)
        self.assertEqual(self.match.unmatched_by, self.me)
        delay.assert_called_once_with(self.me.id, self.other.id)

    def test_unmatch_is_idempotent(self):
        """重复解除仍是 204,不重复入队。

        参数说明:
            无。
        """
        self.match.unmatched_at = timezone.now()
        self.match.save(update_fields=["unmatched_at"])
        with patch("im.tasks.unmatch_blacklist.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.client.delete(f"/api/v1/matches/{self.other.id}")
        self.assertEqual(resp.status_code, 204)
        delay.assert_not_called()

    def test_unmatch_without_match_is_204(self):
        """本来就没配对也回 204。

        参数说明:
            无。
        """
        stranger = self._make_user("13900139001", "路人")
        resp = self.client.delete(f"/api/v1/matches/{stranger.id}")
        self.assertEqual(resp.status_code, 204)

    def test_match_list_hides_unmatched(self):
        """解除后配对列表不再包含对方。

        参数说明:
            无。
        """
        self.match.unmatched_at = timezone.now()
        self.match.save(update_fields=["unmatched_at"])
        self.assertEqual(self.client.get("/api/v1/matches").json()["count"], 0)

    def test_swipe_after_unmatch_does_not_revive(self):
        """解除后再点喜欢不复活配对,也不发通知。

        参数说明:
            无。
        """
        self.match.unmatched_at = timezone.now()
        self.match.save(update_fields=["unmatched_at"])
        # 双方原本就互相 like,这里再点一次喜欢不应复活
        Swipe.objects.create(swiper=self.other, target=self.me, action=SwipeAction.LIKE)
        with patch("discovery.services.notify_match") as notify:
            resp = self.client.post("/api/v1/discovery/swipe",
                                    {"target_user_id": self.other.id, "action": "like"},
                                    format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["matched"])
        notify.assert_not_called()
        self.match.refresh_from_db()
        self.assertIsNotNone(self.match.unmatched_at)

    def test_unmatch_requires_auth(self):
        """未登录解除配对返回 401。

        参数说明:
            无。
        """
        self.client.credentials()
        self.assertEqual(self.client.delete(f"/api/v1/matches/{self.other.id}").status_code, 401)

class VisitsReceivedTests(APITestCase):
    """谁看过我:口径、排序、分页、计数、字段脱敏与权限。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.VisitsReceivedTests``

    备注信息:
        ``_visit`` 直接写 ``ProfileVisit``;列表与人数两个接口分别限流。
    """

    URL = "/api/v1/discovery/visits"
    COUNT_URL = "/api/v1/discovery/visits/count"

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``VisitsReceivedTests().setUp()``

        备注信息:
            先清缓存(访客限流计数在里面),再建 ``self.me`` 并登录。
        """
        cache.clear()
        self.addCleanup(cache.clear)
        self.me = self._make_user("13800138000", gender="male")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, gender="female", complete=True, photo=True, status=None):
        """造一个用户;默认资料完善并带一张已过审照片。

        参数说明:
            phone: 手机号,同时用作昵称。
            gender: 性别,默认 ``female``。
            complete: 是否把资料置为完善,默认 ``True``。
            photo: 是否加一张已过审照片,默认 ``True``。
            status: 显式指定资料状态,用于封禁场景。

        返回参数:
            新建的用户实例。

        使用示例:
            ``self._make_user("13900139001", photo=False)``

        备注信息:
            ``status`` 优先于 ``complete``:传了它就不再按 ``complete`` 推默认状态。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(
            user=user, nickname=phone, gender=gender, birthday="2000-01-01", city="上海",
            bio="你好",
            status=status or (ProfileStatus.COMPLETE if complete else ProfileStatus.INCOMPLETE),
        )
        if photo:
            Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user

    def _visit(self, viewer, minutes_ago=0):
        """让 viewer 访问我一次。

        参数说明:
            viewer: 访客。
            minutes_ago: 访问发生在多少分钟前,默认 0(就是现在)。

        返回参数:
            写入的记录。

        使用示例:
            ``self._visit(a, minutes_ago=30)``

        备注信息:
            ``last_at`` 由 ``minutes_ago`` 反推,用于断言访客列表的倒序。
        """
        return ProfileVisit.objects.create(
            viewer=viewer, owner=self.me,
            last_at=timezone.now() - timedelta(minutes=minutes_ago))

    def _ids(self, resp):
        """取出列表响应里的 ``user_id``。

        参数说明:
            resp: 接口响应。

        返回参数:
            user_id 列表,保持响应顺序。

        使用示例:
            ``self._ids(self.client.get(self.URL))``

        备注信息:
            读的是分页信封里的 ``results``。
        """
        return [item["user_id"] for item in resp.json()["results"]]

    def test_lists_visitors(self):
        """列出看过我资料的人。

        参数说明:
            无。
        """
        a = self._make_user("13900139000")
        self._visit(a)
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), [a.id])

    def test_excludes_people_i_already_swiped(self):
        """我已经划过的人不再出现在访客里。

        参数说明:
            无。
        """
        a = self._make_user("13900139000")
        self._visit(a)
        Swipe.objects.create(swiper=self.me, target=a, action=SwipeAction.PASS)
        self.assertEqual(self._ids(self.client.get(self.URL)), [])

    def test_excludes_matched_people(self):
        """已配对的人不再出现在访客里。

        参数说明:
            无。
        """
        a = self._make_user("13900139000")
        self._visit(a)
        Swipe.objects.create(swiper=self.me, target=a, action=SwipeAction.LIKE)
        Swipe.objects.create(swiper=a, target=self.me, action=SwipeAction.LIKE)
        Match.objects.create(**Match.pair_kwargs(self.me, a))
        self.assertEqual(self._ids(self.client.get(self.URL)), [])

    def test_excludes_blocked_both_ways(self):
        """双向拉黑都过滤:我拉黑对方、对方拉黑我都算。

        参数说明:
            无。
        """
        a = self._make_user("13900139000")
        b = self._make_user("13900139001")
        self._visit(a)
        self._visit(b)
        Block.objects.create(blocker=self.me, blocked=a)
        Block.objects.create(blocker=b, blocked=self.me)
        self.assertEqual(self._ids(self.client.get(self.URL)), [])

    def test_excludes_incomplete_no_photo_and_banned(self):
        """资料未完善、无过审照片、轻/重封禁的访客都不进列表。

        参数说明:
            无。
        """
        users = [
            self._make_user("13900139000", complete=False),
            self._make_user("13900139001", photo=False),
            self._make_user("13900139002", status=ProfileStatus.BANNED_LIGHT),
            self._make_user("13900139003", status=ProfileStatus.BANNED_HEAVY),
        ]
        for user in users:
            self._visit(user)
        self.assertEqual(self._ids(self.client.get(self.URL)), [])

    def test_newest_visit_first(self):
        """按 ``last_at`` 倒序,最新来访的在前。

        参数说明:
            无。
        """
        a = self._make_user("13900139000")
        b = self._make_user("13900139001")
        self._visit(a, minutes_ago=30)
        self._visit(b, minutes_ago=1)
        self.assertEqual(self._ids(self.client.get(self.URL)), [b.id, a.id])

    def test_pagination_by_cursor(self):
        """游标分页翻完不重不漏。

        参数说明:
            无。
        """
        users = [self._make_user(f"1390013900{i}") for i in range(3)]
        for user in users:
            self._visit(user)
        first = self.client.get(self.URL, {"limit": 2}).json()
        self.assertEqual(first["count"], 3)
        self.assertEqual(len(first["results"]), 2)
        self.assertTrue(first["has_more"])
        second = self.client.get(self.URL,
                                 {"limit": 2, "before": first["next_cursor"]}).json()
        self.assertEqual(len(second["results"]), 1)
        self.assertFalse(second["has_more"])
        ids = [item["user_id"] for item in first["results"] + second["results"]]
        self.assertEqual(sorted(ids), sorted(user.id for user in users))   # 翻页不重不漏

    def test_cursor_ignores_new_visit_between_pages(self):
        """翻页期间又有人来访:第二页不重复第 1 页的行。

        参数说明:
            无。
        """
        users = [self._make_user(f"1390013900{i}") for i in range(4)]
        for index, user in enumerate(users[:3]):
            self._visit(user, minutes_ago=10 * (index + 1))
        first = self.client.get(self.URL, {"limit": 2}).json()
        self._visit(users[3])
        second = self.client.get(self.URL,
                                 {"limit": 2, "before": first["next_cursor"]}).json()
        first_ids = [item["user_id"] for item in first["results"]]
        second_ids = [item["user_id"] for item in second["results"]]
        self.assertFalse(set(first_ids) & set(second_ids))
        self.assertEqual(len(first_ids + second_ids), 3)

    def test_offset_request_keeps_legacy_shape(self):
        """老客户端仍带 offset:响应退回 count/next/previous/results。

        参数说明:
            无。
        """
        users = [self._make_user(f"1390013900{i}") for i in range(3)]
        for user in users:
            self._visit(user)
        first = self.client.get(self.URL, {"limit": 2, "offset": 0}).json()
        self.assertEqual(len(first["results"]), 2)
        self.assertIsNotNone(first["next"])
        self.assertEqual(len(self.client.get(self.URL,
                                             {"limit": 2, "offset": 2}).json()["results"]), 1)

    def test_count_uses_same_rules(self):
        """访客人数接口与列表接口同一套过滤规则。

        参数说明:
            无。
        """
        a = self._make_user("13900139000")
        b = self._make_user("13900139001")
        self._visit(a)
        self._visit(b)
        Block.objects.create(blocker=self.me, blocked=b)
        self.assertEqual(self.client.get(self.COUNT_URL).json(), {"count": 1})
        self.assertEqual(self.client.get(self.URL).json()["count"], 1)

    def test_visits_are_throttled_per_user(self):
        """M-3:访客列表按用户限流,超限 429(额度 120/hour)。

        参数说明:
            无。
        """
        with patch.dict(VisitsThrottle.THROTTLE_RATES, {"visits": "2/hour"}):
            statuses = [self.client.get(self.URL).status_code for _ in range(3)]
        self.assertEqual(statuses, [200, 200, 429])

    def test_visits_count_is_throttled_per_user(self):
        """M-3:访客人数按用户限流,超限 429(额度 240/hour)。

        参数说明:
            无。
        """
        with patch.dict(VisitsCountThrottle.THROTTLE_RATES, {"visits_count": "2/hour"}):
            statuses = [self.client.get(self.COUNT_URL).status_code for _ in range(3)]
        self.assertEqual(statuses, [200, 200, 429])

    def test_requires_auth(self):
        """未登录访问访客列表返回 401。

        参数说明:
            无。
        """
        self.client.credentials()
        self.assertEqual(self.client.get(self.URL).status_code, 401)

    def test_heavy_banned_forbidden(self):
        """重封禁访问返回 403。

        参数说明:
            无。
        """
        self.me.profile.status = ProfileStatus.BANNED_HEAVY
        self.me.profile.save(update_fields=["status"])
        self.assertEqual(self.client.get(self.URL).status_code, 403)

    def test_light_banned_can_read(self):
        """轻封禁仍可读访客列表,返回 200。

        参数说明:
            无。
        """
        self.me.profile.status = ProfileStatus.BANNED_LIGHT
        self.me.profile.save(update_fields=["status"])
        self.assertEqual(self.client.get(self.URL).status_code, 200)

    def test_serializer_hides_private_fields_and_filters_photos(self):
        """序列化器隐藏隐私字段并过滤掉未过审照片。

        参数说明:
            无。
        """
        a = self._make_user("13900139000")
        Photo.objects.create(user=a, file="photos/pending.png", status=PhotoStatus.PENDING)
        self._visit(a)
        item = self.client.get(self.URL).json()["results"][0]
        self.assertEqual(item["im_user_id"], f"u{a.id}")
        self.assertIn("visited_at", item)
        for hidden in ("phone", "birthday", "ban_reason", "missing_fields", "visits_hidden"):
            self.assertNotIn(hidden, item)
        self.assertEqual([photo["status"] for photo in item["photos"]], ["approved"])

    def test_end_to_end_via_public_profile(self):
        """我看别人资料只会给对方留下访客记录,我这边列表仍为空。

        参数说明:
            无。
        """
        a = self._make_user("13900139000")
        self.client.get(f"/api/v1/users/{a.id}")      # 我看他 → 他那边才该有记录
        self.assertEqual(self._ids(self.client.get(self.URL)), [])
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(a).access_token}")
        self.assertEqual(self._ids(self.client.get(self.URL)), [self.me.id])

def _make_swipe_user(phone, gender="female"):
    """造一个资料完善、带已过审照片的用户(撤销与每日额度用例共用)。

    参数说明:
        phone: 手机号,同时用作昵称。
        gender: 性别,默认 ``female``。

    返回参数:
        新建的用户实例。

    使用示例:
        ``_make_swipe_user("13900139000", gender="female")``

    备注信息:
        资料状态直接置为 ``ProfileStatus.COMPLETE`` 并附一张已过审照片,满足候选池的准入条件。
    """
    user = User.objects.create_user(phone=phone)
    Profile.objects.create(user=user, nickname=phone, gender=gender, birthday="2000-01-01",
                           city="上海", bio="你好", status=ProfileStatus.COMPLETE)
    Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
    return user


class SwipeUndoTests(APITestCase):
    """撤销上一次滑卡(批次 O):窗口、配对拒绝、候选池复位、日志与鉴权。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.SwipeUndoTests``

    备注信息:
        候选池靠 ``cache_keys`` 版本号失效,``setUp`` 必须清缓存。
    """

    URL = "/api/v1/discovery/swipe/undo"
    SWIPE_URL = "/api/v1/discovery/swipe"
    CANDIDATES_URL = "/api/v1/discovery/candidates"

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``SwipeUndoTests().setUp()``

        备注信息:
            清缓存后造我、目标、路人三个用户,候选池版本键与限流计数都在缓存里。
        """
        cache.clear()               # 候选池版本键与限流计数都在缓存里
        self.addCleanup(cache.clear)
        self.me = _make_swipe_user("13800138000", gender="male")
        self.target = _make_swipe_user("13900139000")
        self.other = _make_swipe_user("13900139001")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _swipe(self, target_id, action="like"):
        """提交一次滑卡。

        参数说明:
            target_id: 目标账号 id。
            action: ``like`` 或 ``pass``,默认 ``like``。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self._swipe(self.target.id, action="pass")``

        备注信息:
            打的是 ``self.SWIPE_URL``,与撤销接口分开;请求体按 JSON 提交。
        """
        return self.client.post(self.SWIPE_URL,
                                {"target_user_id": target_id, "action": action}, format="json")

    def _undo(self):
        """调用撤销接口(无请求体)。

        参数说明:
            无。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self._undo()``

        备注信息:
            撤销目标是服务端按「当前用户最近一次滑卡」推断出来的,不需要传参。
        """
        return self.client.post(self.URL)

    def _candidate_ids(self):
        """拉一页候选卡,返回其账号 id。

        参数说明:
            无。

        返回参数:
            候选卡片上的 ``user_id`` 列表。

        使用示例:
            ``self._candidate_ids()``

        备注信息:
            固定 ``limit=20``,并顺带断言候选接口返回 200。
        """
        resp = self.client.get(self.CANDIDATES_URL, {"limit": 20})
        self.assertEqual(resp.status_code, 200)
        return [card["user_id"] for card in resp.json()]

    def test_undo_deletes_swipe_and_returns_target(self):
        """撤销成功回显目标 id,滑卡行被硬删除。

        参数说明:
            无。
        """
        self.assertEqual(self._swipe(self.target.id).status_code, 200)
        resp = self._undo()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"undone": True, "target_user_id": self.target.id})
        # 实现是硬删除:行不在了,不是软删
        self.assertFalse(Swipe.objects.filter(swiper=self.me, target=self.target).exists())

    def test_undo_restores_target_to_candidates(self):
        """撤销后该目标重新出现在候选池(靠 cache_keys 的版本号失效)。

        参数说明:
            无。
        """
        self.assertIn(self.target.id, self._candidate_ids())
        self._swipe(self.target.id)
        self.assertNotIn(self.target.id, self._candidate_ids())
        self.assertEqual(self._undo().status_code, 200)
        self.assertIn(self.target.id, self._candidate_ids())

    def test_undo_writes_info_log_with_uid_and_target(self):
        """撤销会写一条带 ``uid`` 与 ``target`` 的 INFO 日志。

        参数说明:
            无。
        """
        self._swipe(self.target.id)
        with self.assertLogs("discovery.views", level="INFO") as captured:
            self.assertEqual(self._undo().status_code, 200)
        lines = "\n".join(captured.output)
        self.assertIn(f"uid={self.me.id}", lines)
        self.assertIn(f"target={self.target.id}", lines)

    def test_undo_of_pass_is_allowed(self):
        """``pass`` 也能撤销,响应带回目标 id。

        参数说明:
            无。
        """
        self._swipe(self.target.id, action="pass")
        resp = self._undo()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["target_user_id"], self.target.id)

    def test_undo_rejected_when_swipe_produced_match(self):
        """已产生配对的滑卡不撤销:Match 保留,Swipe 行也在。

        参数说明:
            无。
        """
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        with patch("im.tasks.send_match_notice.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                self.assertEqual(self._swipe(self.target.id).json()["matched"], True)
        resp = self._undo()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 40003)     # error_codes.SWIPE_UNDO_UNAVAILABLE
        self.assertTrue(Match.objects.filter(user_a=self.me, user_b=self.target).exists())
        self.assertTrue(Swipe.objects.filter(swiper=self.me, target=self.target).exists())

    def test_undo_rejected_after_unmatch(self):
        """已解除的配对同样拒绝:灰条与 IM 拉黑都发生过,撤销它是另一码事。

        参数说明:
            无。
        """
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.LIKE)
        with patch("im.tasks.send_match_notice.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                self._swipe(self.target.id)
        Match.objects.update(unmatched_at=timezone.now())
        resp = self._undo()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 40003)

    def test_undo_rejected_after_window(self):
        """超过 30 秒不能再撤销(把 created_at 往前挪 31 秒)。

        参数说明:
            无。
        """
        self._swipe(self.target.id)
        Swipe.objects.filter(swiper=self.me, target=self.target).update(
            created_at=timezone.now() - timedelta(seconds=31))
        resp = self._undo()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 40003)
        self.assertTrue(Swipe.objects.filter(swiper=self.me, target=self.target).exists())

    def test_undo_without_swipe_is_400(self):
        """没有可撤销的滑卡时返回 400 + ``40003``。

        参数说明:
            无。
        """
        resp = self._undo()
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 40003)

    def test_second_undo_is_400(self):
        """同一次滑卡不能撤销两次。

        参数说明:
            无。
        """
        self._swipe(self.target.id)
        self.assertEqual(self._undo().status_code, 200)
        again = self._undo()
        self.assertEqual(again.status_code, 400)
        self.assertEqual(again.json()["code"], 40003)

    def test_undo_only_removes_latest_swipe(self):
        """只撤销最近那一次:更早的那条留在库里(候选池照旧排除)。

        参数说明:
            无。
        """
        self._swipe(self.target.id)
        self._swipe(self.other.id)
        resp = self._undo()
        self.assertEqual(resp.json()["target_user_id"], self.other.id)
        self.assertTrue(Swipe.objects.filter(swiper=self.me, target=self.target).exists())
        self.assertFalse(Swipe.objects.filter(swiper=self.me, target=self.other).exists())

    def test_undo_does_not_touch_received_swipes(self):
        """别人划我的记录不受影响。

        参数说明:
            无。
        """
        Swipe.objects.create(swiper=self.target, target=self.me, action=SwipeAction.PASS)
        self._swipe(self.target.id, action="pass")
        self.assertEqual(self._undo().status_code, 200)
        self.assertTrue(Swipe.objects.filter(swiper=self.target, target=self.me).exists())

    def test_banned_light_cannot_undo(self):
        """被轻封禁不能撤销,返回 403 且滑卡记录还在。

        参数说明:
            无。
        """
        self._swipe(self.target.id)
        Profile.objects.filter(user=self.me).update(status=ProfileStatus.BANNED_LIGHT)
        resp = self._undo()
        self.assertEqual(resp.status_code, 403)
        self.assertTrue(Swipe.objects.filter(swiper=self.me, target=self.target).exists())

    def test_requires_auth(self):
        """未登录撤销返回 401。

        参数说明:
            无。
        """
        self.client.credentials()
        self.assertEqual(self.client.post(self.URL).status_code, 401)


class SwipeDailyLikeQuotaTests(APITestCase):
    """每日喜欢额度(批次 O):超限 429/42904、pass 不限、重放不重复计、撤销退回。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.SwipeDailyLikeQuotaTests``

    备注信息:
        额度计数就是 Redis 键,``setUp`` 清缓存;用例逐个 ``override_settings``。
    """

    SWIPE_URL = "/api/v1/discovery/swipe"
    UNDO_URL = "/api/v1/discovery/swipe/undo"
    QUOTA_URL = "/api/v1/discovery/quota"

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``SwipeDailyLikeQuotaTests().setUp()``

        备注信息:
            清缓存后造一个我、三个目标;额度计数就是 Redis 键,必须逐用例清。
        """
        cache.clear()               # 额度计数就是 Redis 键,必须逐用例清
        self.addCleanup(cache.clear)
        self.me = _make_swipe_user("13800138000", gender="male")
        self.targets = [_make_swipe_user(f"1390013900{index}") for index in range(3)]
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _swipe(self, target_id, action="like"):
        """提交一次滑卡。

        参数说明:
            target_id: 目标账号 id。
            action: ``like`` 或 ``pass``,默认 ``like``。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self._swipe(self.targets[0].id, action="pass")``

        备注信息:
            打的是 ``self.SWIPE_URL``,请求体按 JSON 提交。
        """
        return self.client.post(self.SWIPE_URL,
                                {"target_user_id": target_id, "action": action}, format="json")

    def _quota(self):
        """查询额度接口。

        参数说明:
            无。

        返回参数:
            响应体字典,含 ``like_limit`` / ``likes_used`` / ``likes_remaining``。

        使用示例:
            ``self._quota()["likes_used"]``

        备注信息:
            顺带断言接口返回 200,省掉每个用例重复写状态码。
        """
        resp = self.client.get(self.QUOTA_URL)
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    @override_settings(SWIPE_DAILY_LIKE_LIMIT=2)
    def test_over_limit_returns_429_with_business_code(self):
        """超额度返回 429 + ``42904`` 与 ``Retry-After``,被拒那次不落库也不计数。

        参数说明:
            无。
        """
        self.assertEqual(self._swipe(self.targets[0].id).status_code, 200)
        self.assertEqual(self._swipe(self.targets[1].id).status_code, 200)
        blocked = self._swipe(self.targets[2].id)
        self.assertEqual(blocked.status_code, 429)
        self.assertEqual(blocked.json()["code"], 42904)   # error_codes.SWIPE_LIKE_QUOTA_EXCEEDED
        self.assertIn("Retry-After", blocked.headers)
        # 被拒的那次不留痕迹:不落 Swipe 行,额度也不再多计一次
        self.assertFalse(Swipe.objects.filter(swiper=self.me, target=self.targets[2]).exists())
        self.assertEqual(self._quota()["likes_used"], 2)

    @override_settings(SWIPE_DAILY_LIKE_LIMIT=1)
    def test_pass_is_not_limited(self):
        """``pass`` 不占每日喜欢额度。

        参数说明:
            无。
        """
        self.assertEqual(self._swipe(self.targets[0].id).status_code, 200)
        self.assertEqual(self._swipe(self.targets[1].id, action="pass").status_code, 200)
        self.assertEqual(self._swipe(self.targets[2].id, action="pass").status_code, 200)

    @override_settings(SWIPE_DAILY_LIKE_LIMIT=1)
    def test_idempotent_replay_does_not_consume_quota(self):
        """同一目标重复喜欢不重复扣额度,额度用完后划新人才 429。

        参数说明:
            无。
        """
        self.assertEqual(self._swipe(self.targets[0].id).status_code, 200)
        self.assertEqual(self._swipe(self.targets[0].id).status_code, 200)   # 重放:不算新喜欢
        self.assertEqual(self._swipe(self.targets[1].id).status_code, 429)

    @override_settings(SWIPE_DAILY_LIKE_LIMIT=1)
    def test_undo_refunds_the_like(self):
        """撤销把已用的喜欢退回额度。

        参数说明:
            无。
        """
        self.assertEqual(self._swipe(self.targets[0].id).status_code, 200)
        self.assertEqual(self._quota()["likes_remaining"], 0)
        self.assertEqual(self.client.post(self.UNDO_URL).status_code, 200)
        self.assertEqual(self._quota()["likes_used"], 0)
        self.assertEqual(self._quota()["likes_remaining"], 1)
        self.assertEqual(self._swipe(self.targets[1].id).status_code, 200)

    @override_settings(SWIPE_DAILY_LIKE_LIMIT=3)
    def test_quota_endpoint_reports_usage(self):
        """额度接口按 ``like_limit`` 报出已用与剩余。

        参数说明:
            无。
        """
        self.assertEqual(self._swipe(self.targets[0].id).status_code, 200)
        self.assertEqual(self._quota(),
                         {"like_limit": 3, "likes_used": 1, "likes_remaining": 2})

    @override_settings(SWIPE_DAILY_LIKE_LIMIT=2)
    def test_counter_key_is_per_user_and_per_day(self):
        """计数键形如 ``swipe_like:{uid}:{yyyymmdd}``,TTL 不超过一天。

        参数说明:
            无。
        """
        self._swipe(self.targets[0].id)
        now = timezone.localtime()
        key = f"swipe_like:{self.me.id}:{now.strftime('%Y%m%d')}"
        self.assertEqual(cache.get(key), 1)
        self.assertLessEqual(cache.ttl(key), 86400)

    @override_settings(SWIPE_DAILY_LIKE_LIMIT=2)
    def test_counter_resets_on_next_day(self):
        """跨自然日(``Asia/Shanghai``)重新计数。

        参数说明:
            无。
        """
        self.assertEqual(self._swipe(self.targets[0].id).status_code, 200)
        with patch("discovery.quota._now", return_value=timezone.localtime() + timedelta(days=1)):
            self.assertEqual(self._quota()["likes_used"], 0)
            self.assertEqual(self._swipe(self.targets[1].id).status_code, 200)


class SwipeQuotaDisabledTests(APITestCase):
    """默认值 ``SWIPE_DAILY_LIKE_LIMIT=0`` 时,行为与加额度前完全一致。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.SwipeQuotaDisabledTests``

    备注信息:
        不覆盖 ``SWIPE_DAILY_LIKE_LIMIT``,沿用默认 0(不限额、不写计数键)。
    """

    SWIPE_URL = "/api/v1/discovery/swipe"
    QUOTA_URL = "/api/v1/discovery/quota"

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``SwipeQuotaDisabledTests().setUp()``

        备注信息:
            清缓存后造一个我、三个目标;不覆盖 ``SWIPE_DAILY_LIKE_LIMIT``,沿用默认 0。
        """
        cache.clear()
        self.addCleanup(cache.clear)
        self.me = _make_swipe_user("13800138000", gender="male")
        self.targets = [_make_swipe_user(f"1390013900{index}") for index in range(3)]
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def test_unlimited_likes_when_limit_is_zero(self):
        """额度为 0 时喜欢不受限,连续三次都是 200。

        参数说明:
            无。
        """
        statuses = [self.client.post(
            self.SWIPE_URL, {"target_user_id": target.id, "action": "like"},
            format="json").status_code for target in self.targets]
        self.assertEqual(statuses, [200, 200, 200])

    def test_quota_endpoint_reports_unlimited(self):
        """额度接口报 ``like_limit=0`` 且剩余为 ``null``。

        参数说明:
            无。
        """
        resp = self.client.get(self.QUOTA_URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(),
                         {"like_limit": 0, "likes_used": 0, "likes_remaining": None})

    def test_no_counter_is_written(self):
        """关闭额度时不写 Redis 键:线上不配这个值就等于没有这个功能。

        参数说明:
            无。
        """
        self.client.post(self.SWIPE_URL,
                         {"target_user_id": self.targets[0].id, "action": "like"}, format="json")
        now = timezone.localtime()
        self.assertIsNone(cache.get(f"swipe_like:{self.me.id}:{now.strftime('%Y%m%d')}"))

    def test_quota_requires_auth(self):
        """未登录查额度返回 401。

        参数说明:
            无。
        """
        self.client.credentials()
        self.assertEqual(self.client.get(self.QUOTA_URL).status_code, 401)


def _make_tag(name):
    """造一个兴趣标签(批次 S 的标签筛选用例共用)。

    参数说明:
        name: 标签名(唯一)。

    返回参数:
        新建或已存在的标签。

    使用示例:
        ``_make_tag("徒步")``

    备注信息:
        用 ``get_or_create`` 取名,图标固定 ``star``,重复造同名标签不会报错。
    """
    tag, _ = Tag.objects.get_or_create(name=name, defaults={"icon": "star"})
    return tag


class CandidateFilterTests(APITestCase):
    """候选池的临时筛选(批次 S):覆盖偏好、非法值 400、缓存键不变与去重。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.CandidateFilterTests``

    备注信息:
        ``_pool_keys`` 读 Redis 候选池键断言指纹;``setUp`` 把我城市改成上海。
    """

    URL = "/api/v1/discovery/candidates"

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``CandidateFilterTests().setUp()``

        备注信息:
            造 ``self.me`` 并把资料城市改成上海再登录,候选池键留在 Redis 里供 ``_pool_keys`` 读。
        """
        cache.clear()
        self.addCleanup(cache.clear)
        self.me = _make_swipe_user("13800138000", gender="male")
        Profile.objects.filter(user=self.me).update(city="上海")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make(self, phone, city="上海", birthday="2000-01-01", tags=()):
        """造一个候选用户,可附带标签。

        参数说明:
            phone: 手机号,同时用作昵称。
            city: 城市,默认 ``上海``。
            birthday: 生日,默认 ``2000-01-01``。
            tags: 要挂上的标签序列,默认空。

        返回参数:
            新建的用户实例。

        使用示例:
            ``self._make("13900139000", city="杭州", tags=[hiking])``

        备注信息:
            城市与生日用 ``queryset.update`` 写回,``tags`` 非空时才挂标签。
        """
        user = _make_swipe_user(phone)
        Profile.objects.filter(user=user).update(city=city, birthday=birthday)
        if tags:
            user.profile.tags.set(tags)
        return user

    def _ids(self, resp):
        """从响应里取出 ``user_id`` 列表(保持顺序)。

        参数说明:
            resp: 接口响应。

        返回参数:
            账号 id 列表。

        使用示例:
            ``self._ids(resp)``

        备注信息:
            候选接口返回的是裸数组,不是分页信封。
        """
        return [item["user_id"] for item in resp.json()]

    def _pool_keys(self):
        """Redis 里所有候选池键(去掉前缀,便于断言后缀)。

        参数说明:
            无。

        返回参数:
            键名字符串列表。

        使用示例:
            ``self._pool_keys()``

        备注信息:
            只留属于当前用户的键,并剥掉 ``chatapp:2:`` 前缀,断言时看 ``:u0:g0:p200`` 与 ``:f{指纹}`` 后缀。
        """
        from django_redis import get_redis_connection

        prefix = f"chatapp:2:disc:cand:{self.me.id}:"
        keys = [raw.decode() for raw in get_redis_connection("default").keys("*disc:cand:*")]
        return [key.split("chatapp:2:", 1)[-1] for key in keys if prefix in key]

    def test_city_filter_overrides_preference(self):
        """``city`` 覆盖偏好里的城市(偏好不动)。

        参数说明:
            无。
        """
        Preference.objects.create(profile=self.me.profile, city="上海",
                                  age_min=18, age_max=99)
        hangzhou = self._make("13900139000", city="杭州")
        self._make("13900139001", city="上海")
        self.assertEqual(self._ids(self.client.get(f"{self.URL}?city=杭州")), [hangzhou.id])
        # 偏好没被写回:不带筛选时仍按上海过滤
        self.assertEqual(len(self._ids(self.client.get(self.URL))), 1)
        self.assertEqual(Preference.objects.get(profile=self.me.profile).city, "上海")

    def test_age_range_filter_overrides_preference(self):
        """``age_min`` / ``age_max`` 覆盖偏好的年龄区间,边界含端点。

        参数说明:
            无。
        """
        today = timezone.localdate()
        Preference.objects.create(profile=self.me.profile, age_min=18, age_max=99)
        in_range = self._make("13900139000", birthday=_years_ago(today, 28))
        self._make("13900139001", birthday=_years_ago(today, 24))    # 太小
        self._make("13900139002", birthday=_years_ago(today, 31))    # 太大
        resp = self.client.get(f"{self.URL}?age_min=25&age_max=30")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._ids(resp), [in_range.id])

    def test_inverted_age_range_is_400(self):
        """``age_min=40&age_max=20`` → 400(非法参数不新增业务码)。

        参数说明:
            无。
        """
        resp = self.client.get(f"{self.URL}?age_min=40&age_max=20")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 400)

    def test_non_numeric_filters_are_400(self):
        """非整数年龄 / 非整数或非正标签 id 一律 400。

        参数说明:
            无。
        """
        for query in ("age_min=abc", "age_max=25.5", "tag_ids=1,x", "tag_ids=-1", "tag_ids=0"):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(f"{self.URL}?{query}").status_code, 400)

    def test_city_too_long_is_400(self):
        """城市名超过 ``Profile.city`` 的长度上限时 400。

        参数说明:
            无。
        """
        self.assertEqual(self.client.get(f"{self.URL}?city={'长' * 51}").status_code, 400)

    def test_tag_ids_filter_requires_one_match(self):
        """``tag_ids`` 是「命中其一即可」,且重复标签不会让人重复出现。

        参数说明:
            无。
        """
        hiking = _make_tag("徒步")
        reading = _make_tag("读书")
        music = _make_tag("音乐")
        Profile.objects.get(user=self.me).tags.set([hiking, reading])
        both = self._make("13900139000", tags=[hiking, reading])
        only_hiking = self._make("13900139001", tags=[hiking])
        self._make("13900139002", tags=[music])
        resp = self.client.get(f"{self.URL}?tag_ids={hiking.id},{reading.id}")
        self.assertEqual(resp.status_code, 200)
        # 命中两个标签的人只出现一次,不因 M2M JOIN 产生重复行
        self.assertEqual(sorted(self._ids(resp)), sorted([both.id, only_hiking.id]))

    def test_tag_filter_excludes_people_without_tag(self):
        """没有该标签的人不进结果。

        参数说明:
            无。
        """
        hiking = _make_tag("徒步")
        music = _make_tag("音乐")
        tagged = self._make("13900139000", tags=[hiking])
        self._make("13900139001", tags=[music])
        self.assertEqual(self._ids(self.client.get(f"{self.URL}?tag_ids={hiking.id}")), [tagged.id])

    def test_default_path_keeps_cache_key_and_filter_adds_fingerprint(self):
        """无筛选时缓存键与改动前完全一致,只有带筛选才追加 ``:f{指纹}``。

        参数说明:
            无。
        """
        self._make("13900139000", city="杭州")
        self.assertEqual(self.client.get(self.URL).status_code, 200)
        default_key = f"disc:cand:{self.me.id}:u0:g0:p200"
        self.assertIsNotNone(cache.get(default_key), self._pool_keys())
        self.assertFalse([key for key in self._pool_keys() if ":f" in key.split(":p", 1)[-1]])

        self.assertEqual(self.client.get(f"{self.URL}?city=杭州").status_code, 200)
        filtered = [key for key in self._pool_keys() if ":f" in key.split(":p", 1)[-1]]
        self.assertEqual(len(filtered), 1, self._pool_keys())

    def test_same_filter_reuses_one_bucket(self):
        """同一份筛选重复请求只占一个分桶(指纹稳定,不按请求次数膨胀)。

        参数说明:
            无。
        """
        self._make("13900139000", city="杭州")
        for _ in range(3):
            self.assertEqual(self.client.get(f"{self.URL}?city=杭州").status_code, 200)
        filtered = [key for key in self._pool_keys() if ":f" in key.split(":p", 1)[-1]]
        self.assertEqual(len(filtered), 1, self._pool_keys())

    def test_different_filters_get_different_buckets(self):
        """不同筛选各自成桶,不会互相污染结果。

        参数说明:
            无。
        """
        self._make("13900139000", city="杭州")
        self._make("13900139001", city="北京")
        self.assertEqual(len(self._ids(self.client.get(f"{self.URL}?city=杭州"))), 1)
        self.assertEqual(len(self._ids(self.client.get(f"{self.URL}?city=北京"))), 1)
        filtered = [key for key in self._pool_keys() if ":f" in key.split(":p", 1)[-1]]
        self.assertEqual(len(filtered), 2, self._pool_keys())


class DailyPicksTests(APITestCase):
    """今日精选(批次 S):当天稳定、跨天变化、同口径排除、共同标签数排序。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.DailyPicksTests``

    备注信息:
        跨天变化用 ``patch`` 改 ``discovery.services.today_date``。
    """

    URL = "/api/v1/discovery/daily"

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``DailyPicksTests().setUp()``

        备注信息:
            造 ``self.me`` 并把资料城市改成上海再登录。
        """
        cache.clear()
        self.addCleanup(cache.clear)
        self.me = _make_swipe_user("13800138000", gender="male")
        Profile.objects.filter(user=self.me).update(city="上海")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make(self, phone, city="上海", tags=()):
        """造一个候选用户,可指定城市与标签。

        参数说明:
            phone: 手机号,同时用作昵称。
            city: 城市,默认 ``上海``。
            tags: 要挂上的标签序列,默认空。

        返回参数:
            新建的用户实例。

        使用示例:
            ``self._make("13900139000", city="北京", tags=[hiking])``

        备注信息:
            城市用 ``queryset.update`` 写回,``tags`` 非空时才挂标签。
        """
        user = _make_swipe_user(phone)
        Profile.objects.filter(user=user).update(city=city)
        if tags:
            user.profile.tags.set(tags)
        return user

    def _ids(self, resp):
        """从响应里取出精选卡片的 ``user_id`` 列表(保持顺序)。

        参数说明:
            resp: 接口响应。

        返回参数:
            账号 id 列表。

        使用示例:
            ``self._ids(resp)``

        备注信息:
            精选接口的卡片在 ``candidates`` 字段下,不是 ``results``。
        """
        return [item["user_id"] for item in resp.json()["candidates"]]

    def test_same_day_is_stable(self):
        """同一天连续两次调用,结果与顺序完全相同。

        参数说明:
            无。
        """
        for index in range(8):
            self._make(f"1390013900{index}")
        first = self.client.get(self.URL).json()
        second = self.client.get(self.URL).json()
        self.assertEqual(first, second)

    def test_next_day_changes(self):
        """把日期 monkeypatch 成明天,结果变化(同一天内仍稳定)。

        参数说明:
            无。
        """
        for index in range(10):
            self._make(f"1390013900{index}")
        today = timezone.localdate()
        first = self.client.get(self.URL).json()
        with patch("discovery.services.today_date",
                   return_value=today + timedelta(days=1)):
            tomorrow = self.client.get(self.URL).json()
        self.assertEqual(tomorrow["date"], (today + timedelta(days=1)).isoformat())
        self.assertNotEqual(first["candidates"], tomorrow["candidates"])

    def test_response_shape_and_date(self):
        """返回 ``{date, candidates}``,date 是服务端当天,卡片字段与候选卡一致。

        参数说明:
            无。
        """
        self._make("13900139000")
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["date"], timezone.localdate().isoformat())
        self.assertEqual(set(body["candidates"][0]),
                         {"user_id", "nickname", "gender", "age", "city", "bio", "tags", "photos"})

    def test_default_limit_and_cap(self):
        """默认 6 张、上限 12;候选不足时有多少给多少。

        参数说明:
            无。
        """
        for index in range(15):
            self._make(f"139001390{index:02d}")
        self.assertEqual(len(self._ids(self.client.get(self.URL))), 6)
        self.assertEqual(len(self._ids(self.client.get(f"{self.URL}?limit=12"))), 12)
        self.assertEqual(len(self._ids(self.client.get(f"{self.URL}?limit=99"))), 12)
        self.assertEqual(self.client.get(f"{self.URL}?limit=abc").status_code, 400)

    def test_empty_pool_is_empty_list(self):
        """候选池为空时返回空数组,不报错。

        参数说明:
            无。
        """
        resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["candidates"], [])

    def test_excludes_self_swiped_matched_and_incomplete(self):
        """排除自己 / 已划过 / 已配对 / 资料不全 / 无过审照片,与 candidates 同口径。

        参数说明:
            无。
        """
        fresh = self._make("13900139000")
        swiped = self._make("13900139001")
        matched = self._make("13900139002")
        incomplete = self._make("13900139003")
        Swipe.objects.create(swiper=self.me, target=swiped, action=SwipeAction.PASS)
        Match.objects.create(**Match.pair_kwargs(self.me, matched))
        Profile.objects.filter(user=incomplete).update(status=ProfileStatus.INCOMPLETE)
        no_photo = self._make("13900139004")
        Photo.objects.filter(user=no_photo).delete()
        self.assertEqual(self._ids(self.client.get(self.URL)), [fresh.id])

    def test_orders_by_shared_tag_count(self):
        """共同标签多的排前面(2 个 > 0 个)。

        参数说明:
            无。
        """
        hiking = _make_tag("徒步")
        reading = _make_tag("读书")
        Profile.objects.get(user=self.me).tags.set([hiking, reading])
        two_shared = self._make("13900139000", tags=[hiking, reading])
        none_shared = self._make("13900139001")
        self.assertEqual(self._ids(self.client.get(self.URL)), [two_shared.id, none_shared.id])

    def test_same_city_comes_before_other_city(self):
        """共同标签数相同时同城优先。

        参数说明:
            无。
        """
        same_city = self._make("13900139000", city="上海")
        other_city = self._make("13900139001", city="北京")
        self.assertEqual(self._ids(self.client.get(self.URL)), [same_city.id, other_city.id])

    def test_requires_auth(self):
        """未登录访问今日精选返回 401。

        参数说明:
            无。
        """
        self.client.credentials()
        self.assertEqual(self.client.get(self.URL).status_code, 401)


class SharedTagCountTests(TestCase):
    """共同标签数聚合(批次 S):一条分组查询,不按人循环。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.tests.SharedTagCountTests``

    备注信息:
        只测 ``discovery.services.shared_tag_counts``,``CaptureQueriesContext`` 钉 SQL 条数。
    """

    def setUp(self):
        """按用例场景准备数据库、缓存与登录凭证。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``SharedTagCountTests().setUp()``

        备注信息:
            造 ``self.me`` 与三个标签,并给我挂上「徒步」「读书」两个供求交用。
        """
        self.me = _make_swipe_user("13800138000", gender="male")
        self.hiking = _make_tag("徒步")
        self.reading = _make_tag("读书")
        self.music = _make_tag("音乐")
        Profile.objects.get(user=self.me).tags.set([self.hiking, self.reading])

    def test_counts_shared_tags_in_one_query(self):
        """只数与我共有的标签,并给出 ``{user_id: n}``。

        参数说明:
            无。
        """
        from .services import shared_tag_counts

        two = _make_swipe_user("13900139000")
        two.profile.tags.set([self.hiking, self.reading, self.music])
        none = _make_swipe_user("13900139001")
        none.profile.tags.set([self.music])
        with CaptureQueriesContext(connection) as queries:
            counts = shared_tag_counts(self.me, [two.id, none.id])
        self.assertEqual(counts, {two.id: 2})
        self.assertEqual(len(queries.captured_queries), 2)   # 我的标签 + 分组聚合,不随人数增长

    def test_empty_inputs_return_empty_dict(self):
        """我没有标签或池子为空时返回空字典。

        参数说明:
            无。
        """
        from .services import shared_tag_counts

        other = _make_swipe_user("13900139000")
        self.assertEqual(shared_tag_counts(self.me, []), {})
        Profile.objects.get(user=self.me).tags.clear()
        self.assertEqual(shared_tag_counts(self.me, [other.id]), {})
