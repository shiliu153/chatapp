"""准入名单快照的缓存契约测试(R4-A1)。

覆盖两件事:
    1. 缓存值必须是 JSON(``config/settings.py`` 已切 ``JSONSerializer``),不能是
       pickle 字节 —— 真去 Redis 里读原始字节断言,而不是信任序列化器配置;
    2. 缓存值必须自证:结构不对、签名不符、``SECRET_KEY`` 对不上,一律当未命中
       查库回填,伪造的号码绝不能出现在返回的集合里。
"""

import json

from django.core.cache import cache
from django.test import TestCase, override_settings
from django_redis import get_redis_connection

from accounts import allowlist

ENABLED_PHONE = "13900139000"
DISABLED_PHONE = "13700137000"
FORGED_PHONE = "13900000000"


class AllowlistSnapshotCacheTests(TestCase):
    """名单快照的序列化形态与签名校验。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def raw_value(self):
        """按 Django 的真实键名从 Redis 取快照的原始字节。

        Returns:
            ``bytes``:缓存里存的原始字节(未反序列化)。
        """
        conn = get_redis_connection("default")
        return conn.get(cache.make_key(allowlist.ALLOWLIST_CACHE_KEY))

    def test_snapshot_value_is_json(self):
        """快照落缓存后是 JSON 字节,不是 pickle(``\\x80\\x04`` 开头)。"""
        allowlist.snapshot()
        raw = self.raw_value()
        self.assertIsNotNone(raw)
        self.assertFalse(raw.startswith(b"\x80\x04"), "仍是 pickle 字节,序列化器没生效")
        parsed = json.loads(raw)
        self.assertEqual(set(parsed), {"active", "disabled", "sig"})

    def test_cache_key_is_versioned(self):
        """缓存键带 VERSION=2 前缀:旧 pickle 键(`chatapp:1:`)与新键互不可达。"""
        self.assertTrue(cache.make_key(allowlist.ALLOWLIST_CACHE_KEY).startswith("chatapp:2:"))

    def test_tampered_snapshot_is_ignored(self):
        """伪造值(签名瞎写)视为未命中:返回库里的真值,伪造号不出现。"""
        allowlist.PhoneAllowlist.objects.create(phone=ENABLED_PHONE)
        cache.set(
            allowlist.ALLOWLIST_CACHE_KEY,
            {"active": [FORGED_PHONE], "disabled": [], "sig": "deadbeef"},
            None,
        )
        active, disabled = allowlist.snapshot()
        self.assertEqual(active, frozenset({ENABLED_PHONE}))
        self.assertEqual(disabled, frozenset())
        self.assertNotIn(FORGED_PHONE, active)

    def test_unexpected_snapshot_shape_is_ignored(self):
        """结构不对(不是带 sig 的 dict)同样视为未命中。

        升级前的旧值形如 ``[["号"], []]``;即使它混进新键,也不能被当成真值放行。
        """
        allowlist.PhoneAllowlist.objects.create(phone=DISABLED_PHONE, is_active=False)
        cache.set(allowlist.ALLOWLIST_CACHE_KEY, [[FORGED_PHONE], []], None)
        active, disabled = allowlist.snapshot()
        self.assertEqual(active, frozenset())
        self.assertEqual(disabled, frozenset({DISABLED_PHONE}))

    def test_snapshot_signature_depends_on_secret_key(self):
        """换了 ``SECRET_KEY`` 后,上一把 key 签出的快照也失效(视为未命中)。"""
        allowlist.PhoneAllowlist.objects.create(phone=ENABLED_PHONE)
        allowlist.snapshot()                       # 用当前 SECRET_KEY 写入并签名
        with override_settings(SECRET_KEY="another-secret-for-this-test"):
            active, _ = allowlist.snapshot()
        self.assertEqual(active, frozenset({ENABLED_PHONE}))

    def test_snapshot_returns_frozensets(self):
        """返回值仍是 ``(frozenset, frozenset)``(调用方按集合判定,不能变成 list)。"""
        allowlist.PhoneAllowlist.objects.create(phone=ENABLED_PHONE)
        active, disabled = allowlist.snapshot()
        self.assertIsInstance(active, frozenset)
        self.assertIsInstance(disabled, frozenset)

    def test_snapshot_roundtrip_with_entries(self):
        """库里一启用一停用:两次读(第二次纯缓存)结果一致且不查库。"""
        allowlist.PhoneAllowlist.objects.create(phone=ENABLED_PHONE)
        allowlist.PhoneAllowlist.objects.create(phone=DISABLED_PHONE, is_active=False)
        first = allowlist.snapshot()
        with self.assertNumQueries(0):
            second = allowlist.snapshot()          # 验签通过,直接吃缓存
        self.assertEqual(first, second)
        self.assertEqual(first, (frozenset({ENABLED_PHONE}), frozenset({DISABLED_PHONE})))
