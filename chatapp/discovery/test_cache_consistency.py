"""候选池缓存的一致性测试:命中、失效、降级与并发。

为什么单独一个文件:缓存的价值不在「能存」,而在**写完之后读不到旧值**。
这里的用例按「读 → 写 → 再读」的顺序钉住这个契约,以及 Redis 不可用时的降级行为。

文件信息:
    文件名称          discovery/test_cache_consistency.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from config import cache_utils
from discovery import services
from discovery.cache_keys import (POOL_VERSION_KEY, invalidate_candidates,
                                  invalidate_pool_globally, user_version_key)
from users.models import Photo, PhotoStatus, Profile, ProfileStatus

User = get_user_model()


class _Base(APITestCase):
    """造数 + 认证的公共基类。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``class CandidateCacheTests(_Base):``

    备注信息:
        ``URL`` 是候选接口路径,子类共用;``setUp`` 里清缓存是因为版本号是全局 Redis
        键,用例之间不会自动过期。``_make_user`` 造的人是「资料完善 + 一张已过审照片」,
        这是进候选池的最小条件。
    """

    URL = "/api/v1/discovery/candidates"

    def setUp(self):
        """清空缓存并建一个已登录的男性账号,供各用例直接发请求。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``TestCase`` 在每个用例前自动调用 ``setUp()``

        备注信息:
            顺序不能换:先 ``cache.clear()`` 再发请求,否则上一个用例残留的版本号会让
            命中率断言随机失败。认证头用 ``RefreshToken.for_user`` 直接签出的 access,
            不走登录接口;``self.me`` 是男性,即候选池的请求方。
        """
        cache.clear()   # 版本号是全局 Redis 键,用例之间必须清
        self.me = self._make_user("13800138000", gender="male")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _make_user(self, phone, gender="female", complete=True):
        """造一个资料完善的用户(带一张已过审照片)。

        参数说明:
            phone: 手机号,同时用作昵称。
            gender: 性别,默认 ``female``。
            complete: 是否资料完善,默认 ``True``。

        返回参数:
            新建用户。

        使用示例:
            ``other = self._make_user("13900139000", gender="male")``

        备注信息:
            资料字段固定为生日 ``2000-01-01``、城市「上海」;``complete=False`` 时状态写
            ``INCOMPLETE`` 且不建照片,``complete=True`` 时额外建一张 ``APPROVED`` 照片——
            候选池只推资料完善且有已过审照片的人。
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
    """缓存命中与失效。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.test_cache_consistency.CandidateCacheTests``

    备注信息:
        每个用例都按「读 → 写 → 再读」走一遍,用 ``_count_pool_queries`` 统计
        ``services._query_pool_ids`` 的真实调用次数,以此证明后一次读走的是缓存;
        「失效」的判据是版本号变了、旧键不可达,不是显式删键。
    """

    def _count_pool_queries(self, requests: int) -> int:
        """跑 ``requests`` 次候选接口,统计真正查库的次数。

        参数说明:
            requests: 请求次数。

        返回参数:
            ``_query_pool_ids`` 被调用的次数。

        使用示例:
            ``self.assertEqual(self._count_pool_queries(2), 1)``

        备注信息:
            用 ``patch.object`` 把 ``services._query_pool_ids`` 临时换成记账闭包,只在这一段
            里生效;每次请求都断言 200,避免把错误响应误当成缓存命中。
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
        """同一用户连读两次只查一次库。

        参数说明:
            无。
        """
        self._make_user("13900139000")
        self.assertEqual(self._count_pool_queries(2), 1)

    def test_swipe_invalidates_pool(self):
        """划过的人必须立刻从候选池消失(升版本,旧键不可达)。

        参数说明:
            无。
        """
        other = self._make_user("13900139000")
        self.assertEqual([item["user_id"] for item in self.client.get(self.URL).json()],
                         [other.id])

        resp = self.client.post("/api/v1/discovery/swipe",
                                {"target_user_id": other.id, "action": "like"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.client.get(self.URL).json(), [])

    def test_preference_change_invalidates_pool(self):
        """改偏好后必须重新查库,而不是继续用旧池子。

        参数说明:
            无。
        """
        self._make_user("13900139000", gender="female")
        self.assertEqual(self._count_pool_queries(1), 1)

        resp = self.client.patch("/api/v1/users/me/preference",
                                 {"target_gender": "male"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self._count_pool_queries(1), 1)

    def test_global_bump_invalidates_everyone(self):
        """照片过审这类全局变化:所有用户的键都要换。

        参数说明:
            无。
        """
        self._make_user("13900139000")
        self.assertEqual(self._count_pool_queries(2), 1)
        invalidate_pool_globally()
        self.assertEqual(self._count_pool_queries(1), 1)

    def test_empty_pool_is_cached(self):
        """空结果也缓存(防穿透):没人可推时不该每次都打库。

        参数说明:
            无。
        """
        self.assertEqual(self._count_pool_queries(3), 1)

    def test_cache_down_degrades_to_database(self):
        """Redis 挂了接口仍要 200:缓存故障不能升级为业务故障。

        参数说明:
            无。
        """
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
        """空值哨兵不能泄漏给调用方。

        参数说明:
            无。
        """
        key = "test:null"
        cache.set(key, cache_utils.NULL, 30)
        self.assertIsNone(cache_utils.get_or_load(key, 30, lambda: ["不该被调用"]))


class CandidateCacheDisabledTests(_Base):
    """``CANDIDATE_CACHE_TTL <= 0`` = 显式关闭缓存(E-7 的对比实验与线上熔断都用它)。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.test_cache_consistency.CandidateCacheDisabledTests``

    备注信息:
        注意别把它当成「TTL 设成 0 秒」:``ttl_with_jitter(0)`` 会被兜成 1 秒,
        只设 0 不实现关闭的话,同一个用户 1 秒内的重复读仍会命中。
    """

    def _count_pool_queries(self, requests: int) -> int:
        """跑 ``requests`` 次候选接口,统计真正查库的次数。

        参数说明:
            requests: 请求次数。

        返回参数:
            ``_query_pool_ids`` 被调用的次数。

        使用示例:
            ``self.assertEqual(self._count_pool_queries(3), 3)``

        备注信息:
            与 ``CandidateCacheTests`` 的同名方法逐字相同:两个类各自继承 ``_Base``,
            互不共用方法,改一处时另一处要同步改。
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

    @override_settings(CANDIDATE_CACHE_TTL=0)
    def test_zero_ttl_bypasses_cache_entirely(self):
        """TTL=0:每次都查库,不命中缓存。

        参数说明:
            无。
        """
        self._make_user("13900139000")
        self.assertEqual(self._count_pool_queries(3), 3)

    @override_settings(CANDIDATE_CACHE_TTL=0)
    def test_zero_ttl_does_not_populate_cache(self):
        """TTL=0:关闭期间不往缓存里回填 —— 重新打开后第一次请求仍要查库。

        参数说明:
            无。
        """
        self._make_user("13900139000")
        self.client.get(self.URL)
        with override_settings(CANDIDATE_CACHE_TTL=300):
            self.assertEqual(self._count_pool_queries(1), 1)
            self.assertEqual(self._count_pool_queries(1), 0)   # 这一次才是命中


class CacheVersionTests(TestCase):
    """版本号语义:单调递增、键随版本变化。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.test_cache_consistency.CacheVersionTests``

    备注信息:
        直接调 ``config.cache_utils`` 与 ``discovery.cache_keys``,不经接口;版本键不存在时
        按 0 读,所以「第一次 bump 得到 1」是这个类全部断言的前提。用户级键
        (``disc:ver:{uid}``)与全局键(``disc:ver:global``)必须互不影响。
    """

    def setUp(self):
        """清空缓存,让每个用例的版本号都从 0 起算。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``TestCase`` 在每个用例前自动调用 ``setUp()``

        备注信息:
            版本号存在 Redis 里跨用例存活,不清会让「第一次 bump 得到 1」的断言在后续
            用例上失败。
        """
        cache.clear()

    def test_bump_initializes_from_zero(self):
        """键不存在时第一次 bump 得到 1,而不是报错。

        参数说明:
            无。
        """
        self.assertEqual(cache_utils.version("disc:ver:test"), 0)
        self.assertEqual(cache_utils.bump_version("disc:ver:test"), 1)
        self.assertEqual(cache_utils.version("disc:ver:test"), 1)

    def test_invalidate_candidates_uses_user_key(self):
        """用户级失效只动自己的版本。

        参数说明:
            无。
        """
        invalidate_candidates(7)
        self.assertEqual(cache_utils.version(user_version_key(7)), 1)
        self.assertEqual(cache_utils.version(POOL_VERSION_KEY), 0)

    def test_invalidate_globally_uses_global_key(self):
        """全局失效不动任何人的用户版本。

        参数说明:
            无。
        """
        invalidate_pool_globally()
        self.assertEqual(cache_utils.version(POOL_VERSION_KEY), 1)
        self.assertEqual(cache_utils.version(user_version_key(7)), 0)

    def test_ttl_jitter_stays_within_bounds(self):
        """TTL 抖动必须在 ±10% 内,且不小于 1 秒。

        参数说明:
            无。
        """
        for _ in range(200):
            value = cache_utils.ttl_with_jitter(30)
            self.assertGreaterEqual(value, 27)
            self.assertLessEqual(value, 33)
        self.assertGreaterEqual(cache_utils.ttl_with_jitter(1), 1)


class CacheConcurrencyTests(TestCase):
    """并发正确性:并发 bump 不丢计数;读线程能在 1 秒内看到新版本。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``python manage.py test discovery.test_cache_consistency.CacheConcurrencyTests``

    备注信息:
        靠真实 Redis 的 ``INCR`` 原子性与跨连接可见性成立,用 ``ThreadPoolExecutor`` 起
        多线程;换成不带原子自增的缓存后端,这两条断言都会失败。
    """

    def setUp(self):
        """清空缓存,保证并发用例的计数从 0 开始。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``TestCase`` 在每个用例前自动调用 ``setUp()``

        备注信息:
            两条用例断言的都是绝对值(``+1000``、``== 1``),残留版本会让断言直接偏。
        """
        cache.clear()

    def test_concurrent_bumps_do_not_lose_increments(self):
        """50 线程各 bump 20 次,版本必须恰好 +1000(Redis INCR 原子)。

        参数说明:
            无。
        """
        key = "disc:ver:race"
        with ThreadPoolExecutor(max_workers=50) as pool:
            list(pool.map(lambda _: [cache_utils.bump_version(key) for _ in range(20)],
                          range(50)))
        self.assertEqual(cache_utils.version(key), 1000)

    def test_reader_sees_new_version_within_one_second(self):
        """写线程 bump 后,读线程 1 秒内必须看到新值(最终一致而非强一致)。

        参数说明:
            无。
        """
        key = "disc:ver:visible"
        with ThreadPoolExecutor(max_workers=2) as pool:
            future = pool.submit(cache_utils.bump_version, key)
            future.result(timeout=5)
            seen = pool.submit(cache_utils.version, key).result(timeout=1)
        self.assertEqual(seen, 1)
