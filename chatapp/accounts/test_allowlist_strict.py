"""准入闸门的 fail-closed 行为与部署期检查(R4 M-1)。

覆盖两层:
    1. ``services.ensure_phone_allowed`` 在「库与种子都空」时按
       ``SMS_ALLOWLIST_STRICT`` 决定放行/拒绝 —— 生产留空即严格,开发与测试放行;
    2. ``accounts/checks.py`` 的 ``accounts.E001``:固定码开着、名单种子又为空时,
       ``manage.py check`` 必须变红(种子配好则安静;显式 ``SMS_ALLOWLIST_STRICT=0``
       也安静,因为那时运行时本来就把名单外号码放进来)。

严格模式只该改「名单空」这一条分支:名单内的种子号码、库内显式停用的号码,
行为都与非严格模式一致 —— 用例把这两点也钉住,避免以后改出「严格 = 全拒」。
"""

from unittest.mock import patch

from django.conf import settings
from django.core import checks
from django.core.cache import cache
from django.test import TestCase, override_settings
from rest_framework.test import APITestCase

from accounts import allowlist
from accounts.checks import DEV_SMS_WITHOUT_ALLOWLIST_ID
from accounts.exceptions import PhoneNotAllowed
from accounts.models import PhoneAllowlist

ALLOWED_PHONE = "13900139000"
OUTSIDER_PHONE = "13800138000"


class SmsAllowlistStrictTests(APITestCase):
    """名单为空时的准入判定:严格拒、非严格放行。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)

    def send(self, phone):
        """调用发码接口。

        Args:
            phone: 目标手机号。

        Returns:
            DRF 测试客户端的响应对象。
        """
        return self.client.post("/api/v1/auth/sms/send", {"phone": phone}, format="json")

    @override_settings(SMS_ALLOWLIST_STRICT="1", SMS_PHONE_WHITELIST=frozenset())
    def test_strict_rejects_when_allowlist_empty(self):
        """库空 + 种子空 + 严格:任何号码都拿不到码,403 + 40301,且不入队不发短信。"""
        with patch("notifications.tasks.send_sms_code.delay") as delay:
            resp = self.send(OUTSIDER_PHONE)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], 40301)
        delay.assert_not_called()

    @override_settings(SMS_ALLOWLIST_STRICT="0", SMS_PHONE_WHITELIST=frozenset())
    def test_non_strict_allows_when_allowlist_empty(self):
        """显式关掉严格:名单为空照旧放行 —— 开发/CI 的默认行为不能被改坏。"""
        with patch("notifications.tasks.send_sms_code.delay"):
            resp = self.send(OUTSIDER_PHONE)
        self.assertEqual(resp.status_code, 200)

    @override_settings(
        SMS_ALLOWLIST_STRICT="1", SMS_PHONE_WHITELIST=frozenset({ALLOWED_PHONE})
    )
    def test_strict_still_allows_seed_phone(self):
        """严格只作用于「名单空」:种子里的号码照常发码。"""
        with patch("notifications.tasks.send_sms_code.delay"):
            resp = self.send(ALLOWED_PHONE)
        self.assertEqual(resp.status_code, 200)

    @override_settings(
        SMS_ALLOWLIST_STRICT="1", SMS_PHONE_WHITELIST=frozenset({ALLOWED_PHONE})
    )
    def test_strict_still_rejects_disabled_phone(self):
        """库内显式停用优先于种子,严格模式不改变这条优先级。"""
        PhoneAllowlist.objects.create(phone=ALLOWED_PHONE, is_active=False)
        allowlist.invalidate()
        with patch("notifications.tasks.send_sms_code.delay") as delay:
            resp = self.send(ALLOWED_PHONE)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], 40301)
        delay.assert_not_called()

    @override_settings(SMS_ALLOWLIST_STRICT="1", SMS_PHONE_WHITELIST=frozenset())
    def test_strict_rejects_at_service_layer(self):
        """服务层同样拒绝:校验入口(不只是发码入口)也要挡住。"""
        with self.assertRaises(PhoneNotAllowed):
            from accounts import services

            services.ensure_phone_allowed(OUTSIDER_PHONE)


class SmsAllowlistStrictDefaultTests(TestCase):
    """``SMS_ALLOWLIST_STRICT`` 留空时按环境自动:非 DEBUG 且非测试才严格。"""

    def test_empty_setting_is_not_strict_in_tests(self):
        """测试运行下留空 = 非严格,否则全仓库的既有用例会集体 403。"""
        from accounts import services

        with override_settings(SMS_ALLOWLIST_STRICT="", TESTING=True):
            self.assertFalse(services._strict())


class AllowlistSecurityCheckTests(TestCase):
    """部署期检查 ``accounts.E001``:固定码 + 名单种子空 = check 红。"""

    @staticmethod
    def _ids(errors):
        """把检查结果压成 id 列表,方便断言。

        Args:
            errors: ``checks.run_checks()`` 返回的 ``CheckMessage`` 列表。

        Returns:
            list: 每条结果的 ``id``;没有 id 的项记为 ``""``。
        """
        return [getattr(error, "id", "") for error in errors]

    @override_settings(
        DEBUG=False,
        TESTING=False,
        SMS_DEV_MODE=True,
        SMS_PHONE_WHITELIST=frozenset(),
        SMS_ALLOWLIST_STRICT="",
    )
    def test_security_check_flags_dev_sms_without_allowlist(self):
        """非 DEBUG + 固定码 + 种子空 + 严格留空:结果里必须有 accounts.E001,且 ID 是公布的常量。"""
        self.assertIn(DEV_SMS_WITHOUT_ALLOWLIST_ID, self._ids(checks.run_checks()))
        self.assertEqual(DEV_SMS_WITHOUT_ALLOWLIST_ID, "accounts.E001")

    @override_settings(
        DEBUG=False,
        TESTING=False,
        SMS_DEV_MODE=True,
        SMS_PHONE_WHITELIST=frozenset({ALLOWED_PHONE}),
    )
    def test_security_check_silent_when_seed_present(self):
        """配了种子就不报:检查只管「连种子都没有」这种必然漏配。"""
        self.assertNotIn(DEV_SMS_WITHOUT_ALLOWLIST_ID, self._ids(checks.run_checks()))

    @override_settings(
        DEBUG=False,
        TESTING=False,
        SMS_DEV_MODE=True,
        SMS_PHONE_WHITELIST=frozenset(),
        SMS_ALLOWLIST_STRICT="0",
    )
    def test_security_check_silent_when_strict_explicitly_off(self):
        """显式 ``SMS_ALLOWLIST_STRICT=0`` = 运营确认了封闭测试,本检查不再报 E001。

        issue #290:此前 hint 把这条列为出路,检查却不认,照着做 ``migrate`` 仍然红。
        这里钉住「hint 说的第三条路真的走得通」,同时与 ``services._strict()`` 同口径。
        """
        self.assertNotIn(DEV_SMS_WITHOUT_ALLOWLIST_ID, self._ids(checks.run_checks()))

    @override_settings(
        DEBUG=False,
        TESTING=False,
        SMS_DEV_MODE=True,
        SMS_PHONE_WHITELIST=frozenset(),
        SMS_ALLOWLIST_STRICT="1",
    )
    def test_security_check_flags_when_strict_explicitly_on(self):
        """显式 ``"1"`` 仍报错:逃生口只认 ``"0"``,别把「非空」当成「已确认」。"""
        self.assertIn(DEV_SMS_WITHOUT_ALLOWLIST_ID, self._ids(checks.run_checks()))

    @override_settings(
        DEBUG=False,
        TESTING=False,
        SMS_DEV_MODE=False,
        SMS_PHONE_WHITELIST=frozenset(),
    )
    def test_security_check_silent_when_dev_mode_off(self):
        """关掉固定码后名单为空不算事故:真实短信商才是要配的东西。"""
        self.assertNotIn(DEV_SMS_WITHOUT_ALLOWLIST_ID, self._ids(checks.run_checks()))
        self.assertTrue(settings.SMS_DEV_CODE)      # 固定码常量本身不动,只按开关生效
