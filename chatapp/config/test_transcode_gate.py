"""语音转码全局并发闸(``config/transcode_gate.py``)的单元用例。

用假 Redis 覆盖四种情形:抢到 / 抢不到 / 异常路径释放 / Redis 挂了 fail-open。
不连真 Redis 的理由是「异常」这条分支必须在 ``cache.add`` 抛 ``ConnectionError`` 时
也能验证,而真 Redis 故障没法在用例里稳定复现;视图侧的集成用例(``im/tests.py``、
``users/tests.py``)走的是真缓存,两头互补。

关联文档:
    - 实现:``config/transcode_gate.py``
    - 接口契约:docs/api/im.md(6.4)、docs/api/users.md(2.11)
"""

from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from config import transcode_gate


class FakeRedis:
    """只实现闸用到的 ``add`` / ``delete`` 的 Redis 替身。

    ``add`` 语义与 ``SET NX EX`` 一致:键已存在返回 ``False``、否则写入并返回 ``True``;
    把 ``fail`` 置 ``True`` 就模拟 Redis 不可用,两个方法都抛 ``ConnectionError``。
    """

    def __init__(self):
        """建一个空替身:没有键、``fail`` 关闭。"""
        self.values = {}
        self.ttls = []
        self.fail = False

    def add(self, key, value, timeout=None, version=None):
        """模拟 ``SET key value NX EX timeout``。

        参数说明:
            key: 键名。
            value: 写入的值(闸只放一个随机 token,不对它做判定)。
            timeout: 过期秒数,记录下来供用例断言。
            version: django 缓存的后缀版本号,替身忽略。

        返回参数:
            写入成功返回 ``True``;键已存在返回 ``False``;``fail`` 为真时抛 ``ConnectionError``。

        使用示例:
            ``self.assertTrue(fake.add("k", "v", 60))``(见本文件 ``TranscodeGateTests``)

        备注信息:
            替身不实现真实过期:``timeout`` 只被记录,用例靠显式 ``delete`` 回到「槽空闲」。
        """
        if self.fail:
            raise ConnectionError("redis down")
        self.ttls.append(timeout)
        if key in self.values:
            return False
        self.values[key] = value
        return True

    def delete(self, key, version=None):
        """模拟 ``DEL key``。

        参数说明:
            key: 键名。
            version: django 缓存的后缀版本号,替身忽略。

        返回参数:
            固定返回 ``1``(与 Redis ``DEL`` 的删除计数同形);``fail`` 为真时抛 ``ConnectionError``。

        使用示例:
            ``fake.delete("k")``(见本文件 ``TranscodeGateTests``)

        备注信息:
            删不存在的键也不报错,与 Redis 行为一致。
        """
        if self.fail:
            raise ConnectionError("redis down")
        self.values.pop(key, None)
        return 1


class TranscodeGateTests(SimpleTestCase):
    """抢槽、释放、异常路径与 fail-open 四种情形。"""

    def setUp(self):
        self.redis = FakeRedis()
        patcher = patch.object(transcode_gate, "cache", self.redis)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_acquire_then_release_frees_the_slot(self):
        """抢到 → 槽被占(第二次抢不到)→ 释放后又抢得到。"""
        self.assertTrue(transcode_gate.acquire())
        self.assertFalse(transcode_gate.acquire())
        transcode_gate.release()
        self.assertTrue(transcode_gate.acquire())

    def test_acquire_uses_configured_ttl(self):
        """TTL 取 ``settings.TRANSCODE_GATE_TTL``,默认 60 秒。"""
        self.assertTrue(transcode_gate.acquire())
        self.assertEqual(self.redis.ttls, [60])
        with override_settings(TRANSCODE_GATE_TTL=7):
            self.assertEqual(transcode_gate.gate_ttl(), 7)
        with override_settings(TRANSCODE_GATE_TTL=0):
            self.assertEqual(transcode_gate.gate_ttl(), 60)   # 配成 0 回落到默认值

    def test_slot_context_manager_releases_on_exception(self):
        """``with slot()`` 里抛异常也要释放槽,否则下一次上传要等 TTL 到点。"""
        with self.assertRaises(RuntimeError):
            with transcode_gate.slot() as acquired:
                self.assertTrue(acquired)
                raise RuntimeError("转码炸了")
        self.assertEqual(self.redis.values, {})
        self.assertTrue(transcode_gate.acquire())

    def test_slot_context_manager_reports_busy_without_acquiring(self):
        """槽被占时 ``slot()`` yield ``False`` 且不删别人的槽。"""
        self.assertTrue(transcode_gate.acquire())
        with transcode_gate.slot() as acquired:
            self.assertFalse(acquired)
        self.assertEqual(list(self.redis.values), [transcode_gate.SLOT_KEY])

    def test_redis_failure_fails_open(self):
        """Redis 挂了:抢槽放行(fail-open),释放不抛异常。"""
        self.redis.fail = True
        self.assertTrue(transcode_gate.acquire())
        transcode_gate.release()   # 不抛异常即通过
        with transcode_gate.slot() as acquired:
            self.assertTrue(acquired)
