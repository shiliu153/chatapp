"""列表接口的查询预算(N+1 门禁)与「别退回 Python 侧排除列表」守卫。

背景:2026-11-03 之前全仓没有一处 ``assertNumQueries``,列表接口一旦漏写
``select_related`` / ``prefetch_related``,表现只是「线上慢一点」,测试完全看不见。

两类断言:
    1. **固定预算**:冷/热请求各设上限,超了说明多打了固定几条(如 get_profile 重复查);
    2. **页大小不变性**:limit 从 5 加到 10,SQL 条数必须不变 —— 有 N+1 时条数会跟着涨,
       这比固定预算更能抓住「每行一次查询」的问题。

另有一个 ``IndexAndExistsTests``:把「三处排除列表必须是 ``NOT EXISTS``」与「三条索引
必须存在」钉死,防止有人把 ``~Exists`` 改回「先拉 id 再 ``__in``」(审查 N-2~N-4)。
"""

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from discovery.models import Match
from discovery.services import likes_received_queryset, visits_received_queryset
from feed.models import Post
from users.models import Photo, PhotoStatus, Profile, ProfileStatus

User = get_user_model()

# 2026-11-03 实测值(10 张候选 / 3 个配对 / 12 条动态),上限留 2 条余量。
# 同日 A-2 把三处排除列表改成 NOT EXISTS 后重测:候选冷 18→11、热 9→7、配对 13→7,
# 喜欢我/谁看过我各 4 条(首次纳入门禁)。
BUDGET = {
    "candidates_cold": 13,
    "candidates_warm": 9,
    "matches": 9,
    "posts": 15,
    "likes": 6,
    "visits": 6,
}


def _make_user(phone: str, gender: str = "female") -> User:
    """造一个资料完善、带一张已过审照片的用户。

    Args:
        phone: 手机号(兼昵称)。
        gender: 性别。

    Returns:
        新建用户。
    """
    user = User.objects.create_user(phone=phone)
    Profile.objects.create(user=user, nickname=phone, gender=gender,
                           birthday="2000-01-01", city="上海", bio="你好",
                           status=ProfileStatus.COMPLETE)
    Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
    return user


class QueryBudgetTests(APITestCase):
    """三个列表接口的 SQL 条数上限。"""

    def setUp(self):
        cache.clear()
        self.me = _make_user("13800138000", gender="male")
        for index in range(12):
            other = _make_user(f"1390013{index:04d}")
            if index < 3:
                Match.objects.create(**Match.pair_kwargs(self.me, other))
            Post.objects.create(author=other, text=f"动态{index}")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _count(self, url: str) -> int:
        """请求一个接口并返回执行的 SQL 条数。

        Args:
            url: 接口路径。

        Returns:
            本次请求的 SQL 条数。
        """
        with CaptureQueriesContext(connection) as context:
            response = self.client.get(url)
        self.assertEqual(response.status_code, 200, response.content[:200])
        return len(context.captured_queries)

    def test_candidates_cold_budget(self):
        """冷请求(缓存未命中):含候选池查询与拉黑查询。"""
        self.assertLessEqual(self._count("/api/v1/discovery/candidates?limit=10"),
                             BUDGET["candidates_cold"])

    def test_candidates_warm_budget(self):
        """热请求(缓存命中):只剩鉴权、资料与 10 张卡片的批量查询。"""
        self._count("/api/v1/discovery/candidates?limit=10")
        self.assertLessEqual(self._count("/api/v1/discovery/candidates?limit=10"),
                             BUDGET["candidates_warm"])

    def test_matches_budget(self):
        """配对列表:3 个配对不能按条数线性增长。"""
        self._count("/api/v1/matches")   # 预热:触发 Preference 懒创建
        self.assertLessEqual(self._count("/api/v1/matches"), BUDGET["matches"])

    def test_posts_budget(self):
        """广场列表:两段式分页(取 id + 聚合当页)。"""
        self.assertLessEqual(self._count("/api/v1/posts?limit=10"), BUDGET["posts"])

    def test_candidates_page_size_does_not_change_query_count(self):
        """N+1 守卫:limit 5 → 10,SQL 条数必须不变。"""
        self._count("/api/v1/discovery/candidates?limit=5")   # 预热:触发 Preference 懒创建
        cache.clear()
        small = self._count("/api/v1/discovery/candidates?limit=5")
        cache.clear()
        large = self._count("/api/v1/discovery/candidates?limit=10")
        self.assertEqual(small, large)

    def test_posts_page_size_does_not_change_query_count(self):
        """N+1 守卫:广场每页 5 条与 10 条的 SQL 条数一致。"""
        self._count("/api/v1/posts?limit=5")   # 预热:触发 Preference 懒创建(3 条一次性 SQL)
        small = self._count("/api/v1/posts?limit=5")
        large = self._count("/api/v1/posts?limit=10")
        self.assertEqual(small, large)

    def test_likes_budget(self):
        """喜欢我的人:排除列表必须是 NOT EXISTS,不能按活跃度涨占位符。"""
        self._count("/api/v1/discovery/likes")   # 预热:触发 Preference 懒创建
        self.assertLessEqual(self._count("/api/v1/discovery/likes"), BUDGET["likes"])

    def test_visits_budget(self):
        """谁看过我:与「喜欢我的人」同口径。"""
        self._count("/api/v1/discovery/visits")   # 预热:触发 Preference 懒创建
        self.assertLessEqual(self._count("/api/v1/discovery/visits"), BUDGET["visits"])


class IndexAndExistsTests(APITestCase):
    """把 A-2 的两件事钉死:三条索引必须在,三处排除列表必须走 NOT EXISTS。"""

    def setUp(self):
        """造一个当前用户与一个有照片的对方。"""
        cache.clear()
        self.me = _make_user("13700137000", gender="male")
        self.other = _make_user("13700137001")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _sql_of(self, queryset) -> str:
        """取查询集的 SQL 文本(参数已内联)。

        Args:
            queryset: 要检查的查询集。

        Returns:
            完整 SQL 字符串。
        """
        return str(queryset.query)

    def test_exclusion_lists_use_not_exists(self):
        """三处排除列表必须是 EXISTS 子查询,不能退回「先拉 id 再 NOT IN」。"""
        for name, sql in (
            ("likes", self._sql_of(likes_received_queryset(self.me))),
            ("visits", self._sql_of(visits_received_queryset(self.me))),
        ):
            self.assertIn("EXISTS", sql.upper(), f"{name} 应使用 EXISTS 子查询")
            self.assertNotIn("NOT IN", sql.upper(), f"{name} 不应退回 NOT IN 列表")

    def test_new_indexes_exist(self):
        """三条新索引必须真实存在于库里(迁移漏跑 / 被人删掉都会红)。"""
        if connection.vendor != "mysql":
            self.skipTest("索引检查只对 MySQL 有意义")
        expected = {
            "discovery_swipe": "idx_swipe_target_action",
            "discovery_match": "idx_match_user_b",
            "users_photo": "idx_photo_status_user",
        }
        with connection.cursor() as cursor:
            for table, index in expected.items():
                cursor.execute(f"SHOW INDEX FROM {table} WHERE Key_name = %s", [index])
                self.assertTrue(cursor.fetchall(), f"{table} 缺索引 {index}")
