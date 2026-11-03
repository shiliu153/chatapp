"""候选池缓存的一致性测试:命中、失效、降级与并发。

为什么单独一个文件:缓存的价值不在「能存」,而在**写完之后读不到旧值**。
这里的用例按「读 → 写 → 再读」的顺序钉住这个契约,以及 Redis 不可用时的降级行为。
"""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from config import cache_utils
from discovery import services
from discovery.cache_keys import (POOL_VERSION_KEY, invalidate_candidates,
                                  invalidate_pool_globally, user_version_key)
from users.models import Photo, PhotoStatus, Profile, ProfileStatus

User = get_user_model()


class _Base(APITestCase):
    """造数 + 认证的公共基类。"""

    URL = "/api/v1/discovery/candidates"

    def setUp(self):
        cache.clear()   # 版本号是全局 Redis 键,用例之间必须清
        self.me = self._make_user("13800138000", gender="male")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, gender="female", complete=True):
        """造一个资料完善的用户(带一张已过审照片)。

        Args:
            phone: 手机号。
            gender: 性别。
            complete: 是否资料完善。

        Returns:
            新建用户。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(
            user=user, nickname=phone, gender=gender, birthday="2000-01-01",
            city="上海", bio="你好",
            status=ProfileStatus.COMPLETE if complete else ProfileStatus.INCOMPLETE,
        )
        if complete:
            Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
        return user


class CandidateCacheTests(_Base):
    """缓存命中与失效。"""

    def _count_pool_queries(self, requests: int) -> int:
        """跑 ``requests`` 次候选接口,统计真正查库的次数。

        Args:
            requests: 请求次数。

        Returns:
            ``_query_pool_ids`` 被调用的次数。
        """
        calls = []
        original = services._query_pool_ids

        def counting(*args, **kwargs):
            calls.append(1)
            return original(*args, **kwargs)

        with patch.object(services, "_query_pool_ids", side_effect=counting):
            for _ in range(requests):
                self.assertEqual(self.client.get(self.URL).status_code, 200)
        return len(calls)

    def test_repeated_reads_hit_cache(self):
        """同一用户连读两次只查一次库。"""
        self._make_user("13900139000")
        self.assertEqual(self._count_pool_queries(2), 1)

    def test_swipe_invalidates_pool(self):
        """划过的人必须立刻从候选池消失(升版本,旧键不可达)。"""
        other = self._make_user("13900139000")
        self.assertEqual([item["user_id"] for item in self.client.get(self.URL).json()],
                         [other.id])

        resp = self.client.post("/api/v1/discovery/swipe",
                                {"target_user_id": other.id, "action": "like"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.get(self.URL).json(), [])

    def test_preference_change_invalidates_pool(self):
        """改偏好后必须重新查库,而不是继续用旧池子。"""
        self._make_user("13900139000", gender="female")
        self.assertEqual(self._count_pool_queries(1), 1)

        resp = self.client.patch("/api/v1/users/me/preference",
                                 {"target_gender": "male"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._count_pool_queries(1), 1)

    def test_global_bump_invalidates_everyone(self):
        """照片过审这类全局变化:所有用户的键都要换。"""
        self._make_user("13900139000")
        self.assertEqual(self._count_pool_queries(2), 1)
        invalidate_pool_globally()
        self.assertEqual(self._count_pool_queries(1), 1)

    def test_empty_pool_is_cached(self):
        """空结果也缓存(防穿透):没人可推时不该每次都打库。"""
        self.assertEqual(self._count_pool_queries(3), 1)

    def test_cache_down_degrades_to_database(self):
        """Redis 挂了接口仍要 200:缓存故障不能升级为业务故障。"""
        self._make_user("13900139000")
        original_get = cache.get

        def broken_get(key, default=None, version=None):
            # 只让候选池的键失败:限流器也用同一个 cache,全挂会把 429 变成 500。
            if str(key).startswith("disc:"):
                raise ConnectionError("redis down")
            return original_get(key, default, version)

        with patch.object(cache, "get", side_effect=broken_get):
            resp = self.client.get(self.URL)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.json()), 1)

    def test_null_sentinel_is_not_returned_as_value(self):
        """空值哨兵不能泄漏给调用方。"""
        key = "test:null"
        cache.set(key, cache_utils.NULL, 30)
        self.assertIsNone(cache_utils.get_or_load(key, 30, lambda: ["不该被调用"]))


class CacheVersionTests(TestCase):
    """版本号语义:单调递增、键随版本变化。"""

    def setUp(self):
        cache.clear()

    def test_bump_initializes_from_zero(self):
        """键不存在时第一次 bump 得到 1,而不是报错。"""
        self.assertEqual(cache_utils.version("disc:ver:test"), 0)
        self.assertEqual(cache_utils.bump_version("disc:ver:test"), 1)
        self.assertEqual(cache_utils.version("disc:ver:test"), 1)

    def test_invalidate_candidates_uses_user_key(self):
        """用户级失效只动自己的版本。"""
        invalidate_candidates(7)
        self.assertEqual(cache_utils.version(user_version_key(7)), 1)
        self.assertEqual(cache_utils.version(POOL_VERSION_KEY), 0)

    def test_invalidate_globally_uses_global_key(self):
        """全局失效不动任何人的用户版本。"""
        invalidate_pool_globally()
        self.assertEqual(cache_utils.version(POOL_VERSION_KEY), 1)
        self.assertEqual(cache_utils.version(user_version_key(7)), 0)

    def test_ttl_jitter_stays_within_bounds(self):
        """TTL 抖动必须在 ±10% 内,且不小于 1 秒。"""
        for _ in range(200):
            value = cache_utils.ttl_with_jitter(30)
            self.assertGreaterEqual(value, 27)
            self.assertLessEqual(value, 33)
        self.assertGreaterEqual(cache_utils.ttl_with_jitter(1), 1)


class CacheConcurrencyTests(TestCase):
    """并发正确性:并发 bump 不丢计数;读线程能在 1 秒内看到新版本。"""

    def setUp(self):
        cache.clear()

    def test_concurrent_bumps_do_not_lose_increments(self):
        """50 线程各 bump 20 次,版本必须恰好 +1000(Redis INCR 原子)。"""
        key = "disc:ver:race"
        with ThreadPoolExecutor(max_workers=50) as pool:
            list(pool.map(lambda _: [cache_utils.bump_version(key) for _ in range(20)],
                          range(50)))
        self.assertEqual(cache_utils.version(key), 1000)

    def test_reader_sees_new_version_within_one_second(self):
        """写线程 bump 后,读线程 1 秒内必须看到新值(最终一致而非强一致)。"""
        key = "disc:ver:visible"
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(cache_utils.bump_version, key)
            future.result(timeout=5)
            seen = pool.submit(cache_utils.version, key).result(timeout=1)
        self.assertEqual(seen, 1)
