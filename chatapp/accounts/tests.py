"""账号与鉴权应用的测试。

覆盖场景:
    - 建号管理器(手机号建号、admin 建号);
    - 健康检查与就绪探针(数据库/Redis 任一不可用时返回 503);
    - 发码:落码、60 秒重发间隔、入队失败回滚、手机号格式、IP 限流;
    - 封闭测试白名单(非受邀号码 403、空白名单不限制、纵深防御);
    - 准入名单落库(B-1c):库内命中/未命中/停用、停用优先于 `.env` 种子、快照缓存与失效;
    - 准入名单操作流水(R4-B2):种子导入逐条留 ``seed_import``(操作人为空),幂等跳过不写;
    - 校验登录:自动建号、幂等重放、错误/过期、连错锁定、IP 限流、响应头;
    - 验证码状态机(HMAC 存储、重放窗口、锁定、不存明文);
    - IM 账号约定 ``u{id}``、新用户导入与老用户「待踢旧会话」标记;
    - 令牌刷新与单设备登录(第二次登录作废第一个设备的两类令牌);
    - Web 的 Cookie 分支(登录/刷新/注销、轮换宽限);
    - 造数命令(资料完善、生日不小于 18 岁、号码续编、号池耗尽);
    - 压测令牌命令(一行一个账号的头集、令牌能过鉴权、不签运营账号、生产默认拒绝);
    - 认证通过时刷新在线状态。

文件信息:
    文件名称          accounts/tests.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import base64
import json
import shutil
import tempfile
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import F
from django.test import SimpleTestCase, TestCase, override_settings
from django_redis import get_redis_connection
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import AccessToken

from accounts import allowlist, services, sms_codes
from accounts import totp
from accounts.checks import DEV_SMS_WITHOUT_ALLOWLIST_ID, check_dev_sms_requires_allowlist
from accounts.exceptions import PhoneNotAllowed
from accounts.management.commands.seed_fake_users import Command
from accounts.models import PhoneAllowlist, PhoneAllowlistAction, PhoneAllowlistEvent
from im import tasks as im_tasks
from accounts.throttles import SmsSendThrottle
from accounts.tokens import SessionRefreshToken
from users.models import Photo, PhotoStatus, Profile, ProfileStatus, calculate_age

User = get_user_model()

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32   # 最小假 JPEG 内容(不校验格式,只当字节存)


class UserManagerTests(TestCase):
    """建号管理器:普通用户无可用密码,超级用户有真实密码。"""

    def test_create_user_requires_phone(self):
        """建普通用户只凭手机号,且没有可用密码。

        参数说明:
            无。
        """
        user = User.objects.create_user(phone="13800138000")
        self.assertEqual(user.phone, "13800138000")
        self.assertFalse(user.has_usable_password())  # 验证码登录:无密码

    def test_create_superuser(self):
        """建超级用户,``is_staff`` 与 ``is_superuser`` 同时为真。

        参数说明:
            无。
        """
        admin = User.objects.create_superuser(phone="13900139000", password="admin-pass")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)


class HealthTests(APITestCase):
    """存活探针:不触碰数据库与 Redis,恒定返回 ok。"""

    def test_health_ok(self):
        """存活探针返回 200 与固定的 JSON 体。

        参数说明:
            无。
        """
        resp = self.client.get("/api/v1/health")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})

    def test_health_throttled(self):
        """探针按 IP 限流,超限 429(L1)。

        参数说明:
            无。
        """
        from accounts.throttles import ProbeThrottle

        cache.clear()
        with patch.object(ProbeThrottle, "rate", "2/hour", create=True):
            self.assertEqual(self.client.get("/api/v1/health").status_code, 200)
            self.assertEqual(self.client.get("/api/v1/health").status_code, 200)
            self.assertEqual(self.client.get("/api/v1/health").status_code, 429)


class ReadyZTests(APITestCase):
    """就绪探针:逐项探测数据库与 Redis,任一不可用即 503。"""

    def test_readyz_ok(self):
        """数据库与 Redis 都正常时就绪探针返回 200。

        参数说明:
            无。
        """
        resp = self.client.get("/api/v1/readyz")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok", "checks": {"db": "ok", "redis": "ok"}})

    def test_readyz_db_down_returns_503(self):
        """数据库探测抛错时就绪探针返回 503,``db`` 标为 ``error``。

        参数说明:
            无。
        """
        with patch("accounts.views._probe_db", side_effect=RuntimeError("db down")):
            resp = self.client.get("/api/v1/readyz")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["checks"], {"db": "error", "redis": "ok"})

    def test_readyz_redis_down_returns_503(self):
        """Redis 探测抛错时就绪探针返回 503,``redis`` 标为 ``error``。

        参数说明:
            无。
        """
        with patch("accounts.views._probe_redis", side_effect=RuntimeError("redis down")):
            resp = self.client.get("/api/v1/readyz")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["checks"], {"db": "ok", "redis": "error"})


class SmsSendTests(APITestCase):
    """发送验证码:落码、重发间隔、入队失败回滚、格式校验与 IP 限流。"""

    def setUp(self):
        """清空进程级缓存,并登记用例结束后的再次清理。"""
        cache.clear()               # 缓存是进程级的,测试之间必须清
        self.addCleanup(cache.clear)

    def test_send_stores_code_and_returns_ok(self):
        """发码成功即落码,并按手机号与验证码投递短信任务。

        参数说明:
            无。
        """
        with patch("notifications.tasks.send_sms_code.delay") as delay:
            resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), {"status": "ok"})
        self.assertIs(sms_codes.verify("13800138000", "123456"), sms_codes.CodeResult.OK)
        delay.assert_called_once_with("13800138000", "123456")

    def test_send_twice_within_interval_is_throttled(self):
        """60 秒内二次发码被 42901 拦下,响应带 ``Retry-After``。

        参数说明:
            无。
        """
        with patch("notifications.tasks.send_sms_code.delay"):
            self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
            resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["code"], 42901)
        self.assertIn("Retry-After", resp.headers)

    def test_enqueue_failure_rolls_back_and_returns_503(self):
        """短信任务入队失败时回滚落码并返回 50301,随后可立即重发。

        参数说明:
            无。
        """
        with patch("notifications.tasks.send_sms_code.delay", side_effect=Exception("broker down")):
            resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.json()["code"], 50301)
        # 已回滚:立刻重发应成功(而不是被 60 秒间隔卡住)
        with patch("notifications.tasks.send_sms_code.delay"):
            resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138000"}, format="json")
        self.assertEqual(resp.status_code, 200)

    def test_send_invalid_phone_rejected(self):
        """手机号格式非法时直接返回 400。

        参数说明:
            无。
        """
        resp = self.client.post("/api/v1/auth/sms/send", {"phone": "12345"}, format="json")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 400)

    def test_send_ip_throttle(self):
        # DRF 的 THROTTLE_RATES 是类属性快照,测试里直接临时改 rate 才生效
        """同一 IP 超过发码速率后返回 429。

        参数说明:
            无。
        """
        with patch.object(SmsSendThrottle, "rate", "2/hour", create=True):
            for i in range(2):
                resp = self.client.post("/api/v1/auth/sms/send", {"phone": f"1380013800{i}"}, format="json")
                self.assertEqual(resp.status_code, 200)
            resp = self.client.post("/api/v1/auth/sms/send", {"phone": "13800138009"}, format="json")
            self.assertEqual(resp.status_code, 429)

    @override_settings(SMS_DEV_MODE=True)
    def test_dev_mode_logs_masked_phone_and_code(self):
        """开发模式:日志里有验证码,但手机号必须脱敏(H-3)。

        参数说明:
            无。
        """
        cache.clear()
        with self.assertLogs("accounts", level="INFO") as captured:
            code = services.issue_code("13800138000")
        joined = "\n".join(captured.output)
        self.assertIn(code, joined)
        self.assertIn("138****8000", joined)
        self.assertNotIn("13800138000", joined)

    @override_settings(SMS_DEV_MODE=False)
    def test_production_mode_never_logs_code(self):
        """非开发模式:日志里不能出现验证码(接真实短信商后,H-3)。

        参数说明:
            无。
        """
        cache.clear()
        with self.assertNoLogs("accounts", level="INFO"):
            services.issue_code("13800138000")

    @override_settings(SMS_DEV_MODE=False)
    def test_production_mode_code_is_six_digits(self):
        """非开发模式:验证码是 6 位数字,且不再固定为 123456。

        参数说明:
            无。
        """
        cache.clear()
        with patch("accounts.services.sms_codes.store") as store:
            code = services.issue_code("13800138000")
        self.assertRegex(code, r"^\d{6}$")
        store.assert_called_once_with("13800138000", code)


class SmsVerifyTests(APITestCase):
    """校验验证码并登录:建号、令牌、错误分支、锁定、重放与限流。"""

    def setUp(self):
        """清空缓存并固定测试手机号。"""
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800138000"

    def issue_code(self, phone=None):
        """直接往 Redis 里放一个验证码,绕开 60 秒重发间隔。

        参数说明:
            phone: 目标手机号;``None`` 表示用 ``self.phone``。

        返回参数:
            写入的验证码(开发模式下固定为 ``settings.SMS_DEV_CODE``)。

        使用示例:
            ``self.issue_code()`` 或 ``self.issue_code("13900139000")``

        备注信息:
            先删 ``sms:send:{phone}`` 占位键,否则第二次发码会被 60 秒间隔挡下。
        """
        phone = phone or self.phone
        cache.delete(f"sms:send:{phone}")   # 测试里绕过 60 秒重发间隔的服务端占位
        sms_codes.store(phone, settings.SMS_DEV_CODE)
        return settings.SMS_DEV_CODE

    def verify(self, code, phone=None):
        """调用校验接口。

        参数说明:
            code: 提交的验证码。
            phone: 目标手机号;``None`` 表示用 ``self.phone``。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self.verify(self.issue_code())``

        备注信息:
            只发请求不断言;状态码与响应体由调用方自行校验。
        """
        return self.client.post("/api/v1/auth/sms/verify",
                                {"phone": phone or self.phone, "code": code}, format="json")

    def test_verify_creates_user_and_returns_tokens(self):
        """首次校验即建号并返回令牌,``user_id`` claim 是字符串。

        参数说明:
            无。
        """
        code = self.issue_code()
        resp = self.verify(code)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["is_new_user"])
        user = User.objects.get(phone=self.phone)
        self.assertEqual(data["user_id"], user.id)
        self.assertEqual(AccessToken(data["access"])["user_id"], str(user.id))  # claim 是字符串

    def test_verify_second_time_is_not_new_user(self):
        """同一号码二次登录复用已有账号,``is_new_user`` 为假。

        参数说明:
            无。
        """
        self.verify(self.issue_code())
        code = self.issue_code()
        resp = self.verify(code)
        self.assertFalse(resp.json()["is_new_user"])
        self.assertEqual(User.objects.filter(phone=self.phone).count(), 1)

    def test_staff_account_cannot_login_by_sms(self):
        """C-1:运营账号不走短信登录,固定验证码不能换来最高权限的 API 身份。

        参数说明:
            无。
        """
        User.objects.create(phone=self.phone, is_staff=True, is_superuser=True)
        resp = self.verify(self.issue_code())
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], 403)
        self.assertIn("运营后台", resp.json()["message"])
        self.assertNotIn("access", resp.json())

    def test_staff_account_can_login_when_explicitly_allowed(self):
        """封闭测试用 SMS_ALLOW_STAFF_LOGIN=1 显式放开;生产必须保持 0。

        参数说明:
            无。
        """
        User.objects.create(phone=self.phone, is_staff=True, is_superuser=True)
        with self.settings(SMS_ALLOW_STAFF_LOGIN=True):
            resp = self.verify(self.issue_code())
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", resp.json())

    def test_verify_wrong_code(self):
        """验证码错误返回 40002,且不建号。

        参数说明:
            无。
        """
        self.issue_code()
        resp = self.verify("000000")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 40002)
        self.assertFalse(User.objects.filter(phone=self.phone).exists())

    def test_verify_expired_code(self):
        """从未发过码时校验返回 40001(按过期处理)。

        参数说明:
            无。
        """
        resp = self.verify("123456")   # 从没发过码
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()["code"], 40001)

    def test_lock_after_five_failures(self):
        """连错 5 次后锁定,锁定期内即使码对也返回 42902。

        参数说明:
            无。
        """
        code = self.issue_code()
        for _ in range(5):
            self.verify("000000")
        resp = self.verify("000000")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.json()["code"], 42902)
        resp = self.verify(code)       # 锁定期间即使码对也不行
        self.assertEqual(resp.status_code, 429)

    def test_replay_within_window_issues_new_tokens(self):
        """重放窗口内同一验证码可再换一对新令牌。

        参数说明:
            无。
        """
        code = self.issue_code()
        first = self.verify(code)
        self.assertEqual(first.status_code, 200)
        second = self.verify(code)     # 60 秒重放窗口内:同码可再换令牌
        self.assertEqual(second.status_code, 200)
        self.assertNotEqual(first.json()["access"], second.json()["access"])

    def test_verify_ip_throttle(self):
        """校验接口按 IP 限流,超出额度返回 429。

        参数说明:
            无。
        """
        from accounts.throttles import SmsVerifyThrottle
        with patch.object(SmsVerifyThrottle, "rate", "3/hour", create=True):
            for i in range(3):
                resp = self.verify("000000", phone=f"1380013800{i}")
                self.assertEqual(resp.status_code, 400)   # 码错(限流额度内)
            resp = self.verify("000000", phone="13800138009")
        self.assertEqual(resp.status_code, 429)

    def test_lock_response_carries_retry_after(self):
        """锁定响应带 ``Retry-After``,值等于 ``SMS_LOCK_TTL``。

        参数说明:
            无。
        """
        self.issue_code()
        for _ in range(settings.SMS_MAX_ATTEMPTS):
            self.verify("000000")
        resp = self.verify("000000")
        self.assertEqual(resp.status_code, 429)
        self.assertEqual(resp.headers.get("Retry-After"), str(settings.SMS_LOCK_TTL))

    def test_verify_path_never_calls_im_rest(self):
        """响应路径零外部调用:登录成功只入队任务,绝不同步打 IM(第 1 期铁律的回归)。

        参数说明:
            无。
        """
        code = self.issue_code()
        with patch("im.self_client._post") as rest, \
                patch("im.tasks.import_account.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.verify(code)
        self.assertEqual(resp.status_code, 200)
        rest.assert_not_called()


class SmsPhoneWhitelistTests(APITestCase):
    """封闭测试白名单(B-1 / K-1):非受邀号码拿不到码,也登不上。"""

    ALLOWED = "13900139000"
    OUTSIDER = "13800138000"

    def setUp(self):
        """清空进程级缓存,并登记用例结束后的再次清理。"""
        cache.clear()
        self.addCleanup(cache.clear)

    def send(self, phone):
        """调用发码接口。

        参数说明:
            phone: 目标手机号。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self.send(self.ALLOWED)``

        备注信息:
            不 mock 短信任务,需要时由调用方自行 patch ``send_sms_code.delay``。
        """
        return self.client.post("/api/v1/auth/sms/send", {"phone": phone}, format="json")

    def verify(self, phone, code=None):
        """调用校验登录接口。

        参数说明:
            phone: 目标手机号。
            code: 提交的验证码;``None`` 表示用开发模式的固定码。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self.verify(self.OUTSIDER)``

        备注信息:
            固定码取自 ``settings.SMS_DEV_CODE``,仅在开发/测试口径下可用。
        """
        return self.client.post("/api/v1/auth/sms/verify",
                                {"phone": phone, "code": code or settings.SMS_DEV_CODE},
                                format="json")

    @override_settings(SMS_PHONE_WHITELIST=frozenset({ALLOWED}))
    def test_outsider_cannot_request_code(self):
        """非白名单号码发码:403 + 专属业务码,且不落码、不入队、不占限流键。

        参数说明:
            无。
        """
        with patch("notifications.tasks.send_sms_code.delay") as delay:
            resp = self.send(self.OUTSIDER)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], 40301)
        delay.assert_not_called()
        self.assertIs(sms_codes.verify(self.OUTSIDER, settings.SMS_DEV_CODE),
                      sms_codes.CodeResult.EXPIRED)
        # 没有占限流键:白名单放开后立刻能发,不用等 60 秒
        self.assertIsNone(cache.get(f"sms:send:{self.OUTSIDER}"))

    @override_settings(SMS_PHONE_WHITELIST=frozenset({ALLOWED}))
    def test_outsider_cannot_login_even_with_code(self):
        """纵深防御:码已在白名单收紧前下发,校验入口仍必须拦住。

        参数说明:
            无。
        """
        sms_codes.store(self.OUTSIDER, settings.SMS_DEV_CODE)
        resp = self.verify(self.OUTSIDER)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], 40301)
        self.assertNotIn("access", resp.json())
        self.assertFalse(User.objects.filter(phone=self.OUTSIDER).exists())

    @override_settings(SMS_PHONE_WHITELIST=frozenset({ALLOWED}))
    def test_whitelisted_phone_logs_in(self):
        """白名单内号码:发码与登录都正常。

        参数说明:
            无。
        """
        with patch("notifications.tasks.send_sms_code.delay"):
            resp = self.send(self.ALLOWED)
        self.assertEqual(resp.status_code, 200)
        with patch("im.tasks.import_account.delay"), \
                patch("im.tasks.sync_session_version.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.verify(self.ALLOWED)
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["is_new_user"])

    @override_settings(SMS_PHONE_WHITELIST=frozenset())
    def test_empty_whitelist_allows_any_phone(self):
        """白名单为空 = 不限制(开发/测试默认),避免本地和 CI 全被拦。

        参数说明:
            无。
        """
        with patch("notifications.tasks.send_sms_code.delay"):
            resp = self.send(self.OUTSIDER)
        self.assertEqual(resp.status_code, 200)

    def test_ensure_phone_allowed_service(self):
        """服务层:空白名单放行;命中白名单放行;未命中抛 PhoneNotAllowed。

        参数说明:
            无。
        """
        services.ensure_phone_allowed(self.OUTSIDER)   # 默认设置下白名单为空
        with override_settings(SMS_PHONE_WHITELIST=frozenset({self.OUTSIDER})):
            services.ensure_phone_allowed(self.OUTSIDER)
            with self.assertRaises(PhoneNotAllowed):
                services.ensure_phone_allowed(self.ALLOWED)


class PhoneAllowlistDbTests(APITestCase):
    """准入名单落库(B-1c):库内命中 / 未命中 / 停用,以及写路径的缓存失效。"""

    ALLOWED = "13900139000"
    OUTSIDER = "13800138000"

    def setUp(self):
        """清空进程级缓存,并登记用例结束后的再次清理。"""
        cache.clear()
        self.addCleanup(cache.clear)

    def send(self, phone):
        """调用发码接口。

        参数说明:
            phone: 目标手机号。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self.send(self.ALLOWED)``

        备注信息:
            不 mock 短信任务,需要时由调用方自行 patch ``send_sms_code.delay``。
        """
        return self.client.post("/api/v1/auth/sms/send", {"phone": phone}, format="json")

    def verify(self, phone):
        """用开发模式固定码调用校验登录接口。

        参数说明:
            phone: 目标手机号。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self.verify(self.ALLOWED)``

        备注信息:
            固定码取自 ``settings.SMS_DEV_CODE``;调用前需先让验证码落库或落缓存。
        """
        return self.client.post("/api/v1/auth/sms/verify",
                                {"phone": phone, "code": settings.SMS_DEV_CODE},
                                format="json")

    def test_db_entry_allows_phone(self):
        """库内启用 + 种子为空:该号码能正常发码(名单已由数据库接管)。

        参数说明:
            无。
        """
        PhoneAllowlist.objects.create(phone=self.ALLOWED)
        with patch("notifications.tasks.send_sms_code.delay"):
            resp = self.send(self.ALLOWED)
        self.assertEqual(resp.status_code, 200)

    def test_db_entry_allows_login(self):
        """库内启用:登录链路完整可用(发码 → 校验 → 拿到 access)。

        参数说明:
            无。
        """
        PhoneAllowlist.objects.create(phone=self.ALLOWED)
        with patch("notifications.tasks.send_sms_code.delay"):
            self.assertEqual(self.send(self.ALLOWED).status_code, 200)
        with patch("im.tasks.import_account.delay"), \
                patch("im.tasks.sync_session_version.delay"):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.verify(self.ALLOWED)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", resp.json())

    def test_outsider_denied_when_db_has_entries(self):
        """库里已有别人 → 名单由数据库接管,未列出的号码 403 + 40301。

        参数说明:
            无。
        """
        PhoneAllowlist.objects.create(phone=self.ALLOWED)
        with patch("notifications.tasks.send_sms_code.delay") as delay:
            resp = self.send(self.OUTSIDER)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], 40301)
        delay.assert_not_called()

    def test_disabled_entry_denied_even_if_in_env_seed(self):
        """停用优先于 `.env` 种子 —— 否则「停用」停不掉还留在 `.env` 里的老号。

        参数说明:
            无。
        """
        PhoneAllowlist.objects.create(phone=self.ALLOWED, is_active=False)
        with override_settings(SMS_PHONE_WHITELIST=frozenset({self.ALLOWED})):
            with patch("notifications.tasks.send_sms_code.delay") as delay:
                resp = self.send(self.ALLOWED)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], 40301)
        delay.assert_not_called()

    def test_disabled_phone_cannot_login_with_already_sent_code(self):
        """纵深防御:码已下发后再停用,校验入口仍拦住(快照随写路径立刻失效)。

        参数说明:
            无。
        """
        record = PhoneAllowlist.objects.create(phone=self.ALLOWED)
        sms_codes.store(self.ALLOWED, settings.SMS_DEV_CODE)
        services.ensure_phone_allowed(self.ALLOWED)      # 先把快照缓存写热
        record.is_active = False
        record.save(update_fields=["is_active"])
        allowlist.invalidate()
        resp = self.verify(self.ALLOWED)
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], 40301)

    def test_seed_still_allows_when_db_empty(self):
        """库里一条记录都没有时,`.env` 种子兜底放行(首次导入前的过渡态)。

        参数说明:
            无。
        """
        with override_settings(SMS_PHONE_WHITELIST=frozenset({self.OUTSIDER})):
            services.ensure_phone_allowed(self.OUTSIDER)
            with self.assertRaises(PhoneNotAllowed):
                services.ensure_phone_allowed(self.ALLOWED)

    def test_db_and_seed_both_empty_allows_any(self):
        """库与种子都空 = 不限制(开发/测试默认);有记录才收紧。

        参数说明:
            无。
        """
        services.ensure_phone_allowed(self.OUTSIDER)
        PhoneAllowlist.objects.create(phone=self.ALLOWED)
        allowlist.invalidate()      # 写路径都会清快照,这里显式模拟
        with self.assertRaises(PhoneNotAllowed):
            services.ensure_phone_allowed(self.OUTSIDER)

    def test_snapshot_cached_until_invalidated(self):
        """快照命中缓存时不查库;失效后立刻回到数据库真值。

        参数说明:
            无。
        """
        PhoneAllowlist.objects.create(phone=self.ALLOWED)
        services.ensure_phone_allowed(self.ALLOWED)      # 第一次:查库 + 回填
        with self.assertNumQueries(0):
            services.ensure_phone_allowed(self.ALLOWED)  # 第二次:纯缓存
        allowlist.invalidate()
        with self.assertNumQueries(1):
            services.ensure_phone_allowed(self.ALLOWED)  # 失效后:再查一次


class SmsCodeStateTests(TestCase):
    """验证码状态机:HMAC 存储 + Lua 原子校验 + 重放窗口。"""

    def setUp(self):
        """清空缓存并固定测试手机号。"""
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800138000"

    def test_store_then_verify_ok(self):
        """落码后用正确验证码校验返回 ``OK``。

        参数说明:
            无。
        """
        sms_codes.store(self.phone, "123456")
        self.assertIs(sms_codes.verify(self.phone, "123456"), sms_codes.CodeResult.OK)

    def test_verify_wrong_code(self):
        """验证码错误返回 ``WRONG``。

        参数说明:
            无。
        """
        sms_codes.store(self.phone, "123456")
        self.assertIs(sms_codes.verify(self.phone, "000000"), sms_codes.CodeResult.WRONG)

    def test_verify_without_code_is_expired(self):
        """没落过码时校验返回 ``EXPIRED``。

        参数说明:
            无。
        """
        self.assertIs(sms_codes.verify(self.phone, "123456"), sms_codes.CodeResult.EXPIRED)

    def test_five_wrong_attempts_lock(self):
        """第 5 次错码触发 ``JUST_LOCKED``,之后即使码对也是 ``LOCKED``。

        参数说明:
            无。
        """
        sms_codes.store(self.phone, "123456")
        for _ in range(settings.SMS_MAX_ATTEMPTS - 1):
            self.assertIs(sms_codes.verify(self.phone, "000000"), sms_codes.CodeResult.WRONG)
        self.assertIs(sms_codes.verify(self.phone, "000000"), sms_codes.CodeResult.JUST_LOCKED)
        self.assertIs(sms_codes.verify(self.phone, "123456"), sms_codes.CodeResult.LOCKED)

    def test_success_shrinks_ttl_to_replay_window_and_allows_replay(self):
        """校验成功后 TTL 收缩到重放窗口,窗口内可再次校验通过。

        参数说明:
            无。
        """
        sms_codes.store(self.phone, "123456")
        sms_codes.verify(self.phone, "123456")
        ttl = get_redis_connection("default").ttl(f"sms:code:{self.phone}")
        self.assertLessEqual(ttl, settings.SMS_REPLAY_TTL)
        self.assertIs(sms_codes.verify(self.phone, "123456"), sms_codes.CodeResult.OK)

    def test_code_is_not_stored_in_plaintext(self):
        """Redis 里只存 HMAC 摘要,不含明文验证码。

        参数说明:
            无。
        """
        sms_codes.store(self.phone, "123456")
        stored = get_redis_connection("default").hgetall(f"sms:code:{self.phone}")
        self.assertNotIn(b"123456", stored.values())


class ImUserIdTests(TestCase):
    """IM 账号约定:一律是 ``u{账号 id}``。"""

    def test_im_user_id_is_u_prefixed_id(self):
        """``im_user_id`` 恒为 ``u{账号 id}``。

        参数说明:
            无。
        """
        user = User.objects.create_user(phone="13800138000")
        self.assertEqual(user.im_user_id, f"u{user.id}")


class ImImportOnRegisterTests(APITestCase):
    """登录时的 IM 副作用:新用户导入、老用户标记待踢、入队失败不阻断登录。"""

    def setUp(self):
        """清空缓存并固定测试手机号。"""
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800138000"

    def issue_code(self):
        """直接落一个验证码,绕开重发间隔。

        参数说明:
            无。

        返回参数:
            写入的验证码。

        使用示例:
            ``self.issue_code()``

        备注信息:
            先删 ``sms:send:{phone}`` 占位键,否则二次发码会被 60 秒间隔挡下。
        """
        cache.delete(f"sms:send:{self.phone}")
        sms_codes.store(self.phone, settings.SMS_DEV_CODE)
        return settings.SMS_DEV_CODE

    def verify(self):
        """走一次完整的校验登录流程。

        参数说明:
            无。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self.verify()``

        备注信息:
            内部会重新落码;事务回调需 ``captureOnCommitCallbacks(execute=True)`` 才会执行。
        """
        return self.client.post("/api/v1/auth/sms/verify",
                                {"phone": self.phone, "code": self.issue_code()}, format="json")

    def test_new_user_triggers_import(self):
        """新用户登录后在事务提交时入队 IM 账号导入。

        参数说明:
            无。
        """
        with patch("im.tasks.import_account.delay") as delay:
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.verify()
        self.assertEqual(resp.status_code, 200)
        user = User.objects.get(phone=self.phone)
        delay.assert_called_once_with(user.id)

    def test_existing_login_marks_kick_pending(self):
        """老用户再次登录写入「待踢旧会话」标记并投递兜底任务。

        参数说明:
            无。
        """
        self.verify()
        user = User.objects.get(phone=self.phone)
        cache.delete(im_tasks.kick_pending_key(user.id, "app"))
        with patch("im.tasks.kick_pending.apply_async") as enqueue:
            with self.captureOnCommitCallbacks(execute=True):
                self.verify()
        self.assertEqual(cache.get(im_tasks.kick_pending_key(user.id, "app")), 1)
        enqueue.assert_called_once_with(args=[user.id, "app"],
                                        countdown=im_tasks.KICK_BACKSTOP_DELAY)

    def test_enqueue_failure_does_not_break_login(self):
        """入队失败不影响登录返回 200(``on_commit(robust=True)`` 兜住)。

        参数说明:
            无。
        """
        with patch("im.tasks.import_account.delay", side_effect=Exception("broker down")):
            with self.captureOnCommitCallbacks(execute=True):
                resp = self.verify()
        self.assertEqual(resp.status_code, 200)   # on_commit(robust=True)兜住


class TokenRefreshTests(APITestCase):
    """刷新令牌:换发新的 access + refresh,旧 refresh 立即进黑名单。"""

    def setUp(self):
        """清空缓存并建一个普通用户。"""
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(phone="13800138000")

    def test_refresh_rotates_and_returns_new_pair(self):
        """刷新换发新的一对令牌,新 refresh 可继续换发。

        参数说明:
            无。
        """
        old = str(SessionRefreshToken.for_user(self.user))
        resp = self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", resp.json())
        new = resp.json()["refresh"]
        self.assertNotEqual(new, old)
        # 新 refresh 可以继续换发下一轮
        again = self.client.post("/api/v1/auth/token/refresh", {"refresh": new}, format="json")
        self.assertEqual(again.status_code, 200)

    def test_reuse_within_grace_returns_same_new_pair(self):
        """多标签页并发刷新:后到者拿旧 token 仍能拿到同一对新令牌。

        参数说明:
            无。
        """
        old = str(SessionRefreshToken.for_user(self.user))
        first = self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        new = first.json()["refresh"]
        second = self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json()["refresh"], new)
        self.assertIn("access", second.json())

    @override_settings(REFRESH_REUSE_GRACE=0)
    def test_reuse_after_grace_is_rejected(self):
        """超出宽限期的重复使用视为泄露重放。

        参数说明:
            无。
        """
        old = str(SessionRefreshToken.for_user(self.user))
        self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        again = self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        self.assertEqual(again.status_code, 401)
        self.assertEqual(again.json()["code"], 401)

    def test_grace_does_not_revive_kicked_session(self):
        """宽限期不能绕过单设备登录:账号已被顶下线时旧 token 仍然 40101。

        参数说明:
            无。
        """
        old = str(SessionRefreshToken.for_user(self.user))
        self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        User.objects.filter(pk=self.user.pk).update(session_version=F("session_version") + 1)
        again = self.client.post("/api/v1/auth/token/refresh", {"refresh": old}, format="json")
        self.assertEqual(again.status_code, 401)
        self.assertEqual(again.json()["code"], 40101)

    def test_missing_refresh_is_rejected(self):
        """请求体缺 refresh 时返回 401。

        参数说明:
            无。
        """
        resp = self.client.post("/api/v1/auth/token/refresh", {}, format="json")
        self.assertEqual(resp.status_code, 401)


class WebCookieAuthTests(APITestCase):
    """Web 分支:refresh 走 HttpOnly Cookie,响应体不返回 refresh。"""

    def setUp(self):
        """清空缓存,建号并固定手机号。"""
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800138000"
        self.user = User.objects.create_user(phone=self.phone)

    def issue_code(self):
        """绕过 60 秒重发间隔写入验证码。

        参数说明:
            无。

        返回参数:
            写入的验证码(开发模式下固定为 ``settings.SMS_DEV_CODE``)。

        使用示例:
            ``self.issue_code()``

        备注信息:
            先删 ``sms:send:{phone}`` 占位键,否则二次发码会被 60 秒间隔挡下。
        """
        cache.delete(f"sms:send:{self.phone}")
        sms_codes.store(self.phone, settings.SMS_DEV_CODE)
        return settings.SMS_DEV_CODE

    def web_login(self):
        """带 ``X-Client: web`` 走一次校验登录。

        参数说明:
            无。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``self.web_login().cookies[settings.REFRESH_COOKIE_NAME].value``

        备注信息:
            请求头决定服务端走 Cookie 分支,响应体不会返回 refresh。
        """
        return self.client.post("/api/v1/auth/sms/verify",
                                {"phone": self.phone, "code": self.issue_code()},
                                format="json", HTTP_X_CLIENT="web")

    def test_web_login_sets_cookie_and_hides_refresh(self):
        """Web 登录把 refresh 写进 HttpOnly Cookie,响应体不含 refresh。

        参数说明:
            无。
        """
        resp = self.web_login()
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("refresh", resp.json())
        cookie = resp.cookies[settings.REFRESH_COOKIE_NAME]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Strict")
        self.assertEqual(cookie["path"], "/api/v1/auth/")
        self.assertTrue(cookie.value)

    def test_app_login_returns_refresh_without_cookie(self):
        """App 登录在响应体返回 refresh,且不下发 Cookie。

        参数说明:
            无。
        """
        resp = self.client.post("/api/v1/auth/sms/verify",
                                {"phone": self.phone, "code": self.issue_code()}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("refresh", resp.json())
        self.assertNotIn(settings.REFRESH_COOKIE_NAME, resp.cookies)

    def test_cookie_refresh_rotates_and_sets_new_cookie(self):
        """Cookie 刷新换发新 Cookie,值与原 Cookie 不同。

        参数说明:
            无。
        """
        raw = self.web_login().cookies[settings.REFRESH_COOKIE_NAME].value
        self.client.cookies[settings.REFRESH_COOKIE_NAME] = raw
        resp = self.client.post("/api/v1/auth/token/refresh", {}, format="json",
                                HTTP_X_CLIENT="web")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("access", resp.json())
        self.assertNotIn("refresh", resp.json())
        rotated = resp.cookies[settings.REFRESH_COOKIE_NAME].value
        self.assertNotEqual(rotated, raw)

    def test_cookie_refresh_without_client_header_still_works(self):
        """带了 Cookie 就按 Web 处理,不强制要求 X-Client 头(容错)。

        参数说明:
            无。
        """
        raw = self.web_login().cookies[settings.REFRESH_COOKIE_NAME].value
        self.client.cookies[settings.REFRESH_COOKIE_NAME] = raw
        resp = self.client.post("/api/v1/auth/token/refresh", {}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertNotIn("refresh", resp.json())

    @override_settings(DEBUG=False)
    def test_cross_site_refresh_is_rejected(self):
        """Origin 与 Host 不同源时拒绝刷新(Cookie 的 CSRF 兜底,M-3/L-4)。

        参数说明:
            无。
        """
        raw = self.web_login().cookies[settings.REFRESH_COOKIE_NAME].value
        self.client.cookies[settings.REFRESH_COOKIE_NAME] = raw
        resp = self.client.post("/api/v1/auth/token/refresh", {}, format="json",
                                HTTP_X_CLIENT="web", HTTP_ORIGIN="https://evil.example.com")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], 403)

    @override_settings(DEBUG=False)
    def test_same_origin_refresh_is_allowed(self):
        """同源 Origin 正常放行。

        参数说明:
            无。
        """
        raw = self.web_login().cookies[settings.REFRESH_COOKIE_NAME].value
        self.client.cookies[settings.REFRESH_COOKIE_NAME] = raw
        resp = self.client.post("/api/v1/auth/token/refresh", {}, format="json",
                                HTTP_X_CLIENT="web", HTTP_ORIGIN="http://testserver")
        self.assertEqual(resp.status_code, 200)

    def test_logout_is_throttled(self):
        """注销按 IP 限流,避免匿名调用刷黑名单表(L-5)。

        参数说明:
            无。
        """
        from accounts.throttles import LogoutThrottle

        with patch.object(LogoutThrottle, "rate", "1/hour", create=True):
            first = self.client.post("/api/v1/auth/logout", {}, format="json")
            second = self.client.post("/api/v1/auth/logout", {}, format="json")
        self.assertEqual(first.status_code, 204)
        self.assertEqual(second.status_code, 429)

    def test_logout_blacklists_refresh_and_clears_cookie(self):
        """注销把 refresh 拉黑并清 Cookie,之后刷新返回 401。

        参数说明:
            无。
        """
        raw = self.web_login().cookies[settings.REFRESH_COOKIE_NAME].value
        self.client.cookies[settings.REFRESH_COOKIE_NAME] = raw
        resp = self.client.post("/api/v1/auth/logout", {}, format="json", HTTP_X_CLIENT="web")
        self.assertEqual(resp.status_code, 204)
        cleared = resp.cookies[settings.REFRESH_COOKIE_NAME]
        self.assertEqual(cleared["max-age"], 0)
        # 被拉黑后不能再刷新
        self.client.cookies[settings.REFRESH_COOKIE_NAME] = raw
        again = self.client.post("/api/v1/auth/token/refresh", {}, format="json",
                                 HTTP_X_CLIENT="web")
        self.assertEqual(again.status_code, 401)

    def test_logout_is_idempotent(self):
        """未登录注销也返回 204,并下发清 Cookie 指令。

        参数说明:
            无。
        """
        resp = self.client.post("/api/v1/auth/logout", {}, format="json")
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.cookies[settings.REFRESH_COOKIE_NAME]["max-age"], 0)


class SingleDeviceSessionTests(APITestCase):
    """单设备登录:后登录的设备作废先登录设备的 access/refresh(40101)。"""

    def setUp(self):
        """清空缓存并固定测试手机号。"""
        cache.clear()
        self.addCleanup(cache.clear)
        self.phone = "13800138000"

    def login(self):
        """走一次完整的校验登录,返回响应。

        参数说明:
            无。

        返回参数:
            DRF 测试客户端的响应对象,``json()`` 内含 access / refresh。

        使用示例:
            ``first = self.login().json()["access"]``

        备注信息:
            先删 ``sms:send`` 占位键绕过 60 秒间隔;每次调用都会递增会话版本,作废上一对令牌。
        """
        cache.delete(f"sms:send:{self.phone}")   # 绕过 60 秒重发间隔的服务端占位
        code = settings.SMS_DEV_CODE
        sms_codes.store(self.phone, code)
        return self.client.post("/api/v1/auth/sms/verify",
                                {"phone": self.phone, "code": code}, format="json")

    def test_second_login_invalidates_first_access_token(self):
        """第二次登录后旧 access 访问接口返回 40101,新 access 正常。

        参数说明:
            无。
        """
        first = self.login().json()["access"]
        second = self.login().json()["access"]
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {first}")
        resp = self.client.get("/api/v1/users/me")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["code"], 40101)
        self.assertIn("其他设备", resp.json()["message"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {second}")
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 200)

    def test_second_login_invalidates_first_refresh_token(self):
        """第二次登录后旧 refresh 刷新返回 40101。

        参数说明:
            无。
        """
        first_refresh = self.login().json()["refresh"]
        self.login()
        resp = self.client.post("/api/v1/auth/token/refresh", {"refresh": first_refresh}, format="json")
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["code"], 40101)

class AllowlistSeedImportTests(TestCase):
    """种子导入命令 allowlist_seed_import:幂等补齐,但不把已停用的号放回来。"""

    def setUp(self):
        """清空进程级缓存,并登记用例结束后的再次清理。"""
        cache.clear()
        self.addCleanup(cache.clear)

    def run_cmd(self, **kwargs):
        """跑一次导入命令并返回标准输出。

        参数说明:
            **kwargs: 透传给 ``call_command`` 的选项(dry_run / note)。

        返回参数:
            命令的标准输出文本。

        使用示例:
            ``self.run_cmd(dry_run=True)``

        备注信息:
            用 ``StringIO`` 捕获标准输出;``**kwargs`` 原样透传给 ``call_command``。
        """
        out = StringIO()
        call_command("allowlist_seed_import", stdout=out, **kwargs)
        return out.getvalue()

    @override_settings(SMS_PHONE_WHITELIST=frozenset({"13900139000", "13900139001"}))
    def test_imports_missing_numbers(self):
        """把种子号码补进库,备注写默认说明。

        参数说明:
            无。
        """
        self.run_cmd()
        self.assertEqual(PhoneAllowlist.objects.count(), 2)
        self.assertTrue(all(r.note == "从 .env 种子导入" for r in PhoneAllowlist.objects.all()))

    @override_settings(SMS_PHONE_WHITELIST=frozenset({"13900139000"}))
    def test_dry_run_writes_nothing(self):
        """--dry-run 只打印,不写库。

        参数说明:
            无。
        """
        output = self.run_cmd(dry_run=True)
        self.assertIn("139****9000", output)
        self.assertFalse(PhoneAllowlist.objects.exists())

    @override_settings(SMS_PHONE_WHITELIST=frozenset({"13900139000", "13900139001"}))
    def test_idempotent_and_keeps_disabled_entries(self):
        """重复执行不重复插入,且**不会**把已停用的号码重新启用。

        参数说明:
            无。
        """
        disabled = PhoneAllowlist.objects.create(phone="13900139000",
                                                 note="手工加的", is_active=False)
        self.run_cmd()
        self.run_cmd()
        self.assertEqual(PhoneAllowlist.objects.count(), 2)
        disabled.refresh_from_db()
        self.assertFalse(disabled.is_active)
        self.assertEqual(disabled.note, "手工加的")

    @override_settings(SMS_PHONE_WHITELIST=frozenset())
    def test_empty_seed_is_noop(self):
        """种子为空时什么都不做。

        参数说明:
            无。
        """
        output = self.run_cmd()
        self.assertIn("没有可导入的号码", output)
        self.assertFalse(PhoneAllowlist.objects.exists())

    @override_settings(SMS_PHONE_WHITELIST=frozenset({"13900139000", "13900139001"}))
    def test_import_records_seed_event_without_operator(self):
        """每条导入写一条 ``seed_import`` 流水,``operator`` 为空(命令没有操作人)。

        参数说明:
            无。
        """
        self.run_cmd(note="老号迁移")
        events = PhoneAllowlistEvent.objects.order_by("phone")
        self.assertEqual(events.count(), 2)
        self.assertEqual(
            set(events.values_list("phone", flat=True)),
            {"13900139000", "13900139001"},
        )
        self.assertEqual({e.action for e in events}, {PhoneAllowlistAction.SEED_IMPORT})
        self.assertTrue(all(e.operator is None for e in events))
        self.assertEqual({e.note for e in events}, {"老号迁移"})

    @override_settings(SMS_PHONE_WHITELIST=frozenset({"13900139000"}))
    def test_rerun_records_no_extra_event(self):
        """幂等跳过的不写流水:重复执行不会把审计表刷成噪声。

        参数说明:
            无。
        """
        self.run_cmd()
        self.run_cmd()
        self.assertEqual(PhoneAllowlistEvent.objects.count(), 1)

    @override_settings(SMS_PHONE_WHITELIST=frozenset({"13900139000"}))
    def test_dry_run_records_no_event(self):
        """``--dry-run`` 不落库,自然也没有流水。

        参数说明:
            无。
        """
        self.run_cmd(dry_run=True)
        self.assertFalse(PhoneAllowlistEvent.objects.exists())


class SeedFakeUsersTests(TestCase):
    """造数命令 seed_fake_users:建「资料已完善 + 过审照片」的女号(手测发现页用)。"""

    def setUp(self):
        """建一个既有账号,并给 IM 客户端与图片下载打桩。"""
        self.origin = User.objects.create_user(phone="13800138000")
        self.im = patch("accounts.management.commands.seed_fake_users.im_client")
        self.im_mock = self.im.start()
        self.addCleanup(self.im.stop)
        self.dl = patch("accounts.management.commands.seed_fake_users._download", return_value=JPEG)
        self.dl_mock = self.dl.start()
        self.addCleanup(self.dl.stop)

    def seed(self, count):
        """跑一次造数命令。

        参数说明:
            count: 要创建的人数。

        返回参数:
            无返回值。

        使用示例:
            ``self.seed(3)``

        备注信息:
            标准输出置 ``None``,避免污染测试输出;号码从 13900000001 起按序分配。
        """
        call_command("seed_fake_users", count=count, stdout=None)

    def created(self, origin_id):
        """取出本次造数新建的用户。

        参数说明:
            origin_id: 造数前已存在的最大用户 id。

        返回参数:
            新建的用户列表,按 id 升序。

        使用示例:
            ``users = self.created(self.origin.id)``

        备注信息:
            只按 id 过滤,不区分号码段;顺序与号码分配顺序一致。
        """
        return list(User.objects.filter(id__gt=origin_id).order_by("id"))

    def test_creates_complete_female_profiles_with_photos(self):
        """造出资料完整、照片过审的女号,并同步 IM 昵称与头像。

        参数说明:
            无。
        """
        self.seed(3)
        users = self.created(self.origin.id)
        self.assertEqual(len(users), 3)

        # 号码段从 13900000001 起,按序分配
        self.assertEqual([u.phone for u in users], ["13900000001", "13900000002", "13900000003"])
        for user in users:
            profile = user.profile
            self.assertEqual(profile.gender, "female")
            self.assertEqual(profile.status, ProfileStatus.COMPLETE)
            self.assertTrue(profile.nickname and profile.city and profile.bio and profile.birthday)
            self.assertGreaterEqual(profile.age, 18)
            self.assertLessEqual(profile.age, 45)
            self.assertGreaterEqual(profile.tags.count(), 1)
            self.assertEqual(profile.preference.target_gender, "male")

            photos = list(user.photos.all())
            self.assertEqual(len(photos), 2)
            self.assertEqual([p.status for p in photos], [PhotoStatus.APPROVED] * 2)
            self.assertEqual([p.order for p in photos], [0, 1])
            self.assertTrue(all(p.file.name for p in photos))

            # IM 三件事:导入账号、同步昵称、同步头像
            self.im_mock.ensure_account.assert_any_call(user.im_user_id, profile.nickname)
            self.im_mock.set_profile_nick.assert_any_call(user.im_user_id, profile.nickname)
            self.im_mock.set_profile_avatar.assert_any_call(user.im_user_id, photos[0].file.url)

    def test_random_birthday_never_yields_under_18(self):
        """回归(2026-10-13 CI 实测红):抽到 age=18 且月/日取到「晚于今天」的最坏值时,算出来是 17。

        造数命令承诺 18–45,但「age 年前的随机月/日」在**今年的生日还没过**时会被
        `calculate_age` 算成 age-1 —— 于是可能造出未满 18 岁的账号(平台明令禁止)。
        这里把随机源钉在「最坏组合」:年龄取下界 18,月与日都取各自上界。

        参数说明:
            无。
        """
        cmd = Command()
        today = date(2026, 10, 13)

        def worst_case(a, b):
            return 18 if (a, b) == (18, 45) else b   # 年龄取下界;其余一律取上界

        with patch("accounts.management.commands.seed_fake_users.random.randint",
                   side_effect=worst_case), \
                patch("django.utils.timezone.localdate", return_value=today):
            birthday = cmd._random_birthday()

        self.assertEqual(calculate_age(birthday, today=today), 18,
                         msg=f"birthday={birthday}")

    def test_rerun_continues_after_existing_numbers(self):
        # 号码从「已分配的最大序号 + 1」续编;跑满 99 后再跑 = 号码段耗尽
        """重复造数从已分配的最大序号续编,不重复建号。

        参数说明:
            无。
        """
        self.seed(3)
        self.seed(3)
        users = self.created(self.origin.id)
        self.assertEqual([u.phone for u in users],
                         ["13900000001", "13900000002", "13900000003",
                          "13900000004", "13900000005", "13900000006"])
        self.assertEqual(User.objects.count(), 7)   # 没有重复建号

    def test_phone_pool_overflow_raises(self):
        """号码段耗尽时命令抛 ``CommandError``。

        参数说明:
            无。
        """
        User.objects.create_user(phone="13900000099")   # 占满号码段末位
        with self.assertRaises(CommandError):
            self.seed(3)

    def test_skip_im_still_creates_users(self):
        """``skip_im=True`` 时只建号,不调 IM。

        参数说明:
            无。
        """
        call_command("seed_fake_users", count=2, skip_im=True, stdout=None)
        self.assertEqual(len(self.created(self.origin.id)), 2)
        self.im_mock.ensure_account.assert_not_called()


@override_settings(DEBUG=True)   # 命令默认只在非生产(DEBUG=1)签发,见下一个用例
class PerfTokensTests(APITestCase):
    """压测令牌命令:写场景要多账号,令牌签错就等于压出 401 而自己不知道。"""

    def setUp(self):
        """建三个 199 号段的测试号(命令只签这个号段)。"""
        self.users = [User.objects.create_user(phone=str(19_900_000_000 + i))
                      for i in range(1, 4)]

    def _out_file(self) -> Path:
        """造一个临时输出路径(测试结束自动清理)。

        参数说明:
            无。

        返回参数:
            临时文件路径。

        使用示例:
            ``out = self._out_file()``

        备注信息:
            目录由 ``tempfile.mkdtemp`` 建,``addCleanup`` 负责删,不会残留到仓库里。
        """
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        return Path(tmp) / "headers.jsonl"

    def _mint(self, **kwargs) -> list[dict]:
        """跑一次命令并读回头集。

        参数说明:
            **kwargs: 传给命令的参数。

        返回参数:
            解析后的头集列表,每项是一行的内容。

        使用示例:
            ``sets = self._mint(count=2)``

        备注信息:
            命令产出 JSONL,一行一个头集;每行两个头 ``Authorization`` 与 ``X-Forwarded-For``。
        """
        out = self._out_file()
        call_command("perf_tokens", out=str(out), stdout=StringIO(), **kwargs)
        return [json.loads(line)
                for line in out.read_text(encoding="utf-8").splitlines()]

    def test_emits_one_header_set_per_account(self):
        """每个账号产出一行头集,``X-Forwarded-For`` 互不相同。

        参数说明:
            无。
        """
        sets = self._mint(count=2)
        self.assertEqual(len(sets), 2)
        for item in sets:
            self.assertEqual(set(item), {"Authorization", "X-Forwarded-For"})
            self.assertTrue(item["Authorization"].startswith("Bearer "))
        # X-Forwarded-For 要错开,否则 IP 维度的限流会把所有连接算成同一个来源
        self.assertNotEqual(sets[0]["X-Forwarded-For"], sets[1]["X-Forwarded-For"])

    def test_minted_token_passes_authentication(self):
        """签出来的 access 必须和登录拿到的一样能过鉴权(带 session_version claim)。

        参数说明:
            无。
        """
        token = self._mint(count=1)[0]["Authorization"].removeprefix("Bearer ")
        self.assertEqual(AccessToken(token)["session_version"], self.users[0].session_version)
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        self.assertEqual(self.client.get("/api/v1/users/me").status_code, 200)

    def test_skips_staff_and_out_of_range_accounts(self):
        """只签非运营、且在 199 号段内的账号。

        参数说明:
            无。
        """
        User.objects.create_user(phone="19900000009", is_staff=True)
        User.objects.create_user(phone="13800138000")
        sets = self._mint(count=10)
        self.assertEqual(len(sets), 3)

    def test_start_offset_picks_another_batch(self):
        """``start`` 偏移改变取号起点,产出不同令牌。

        参数说明:
            无。
        """
        first = self._mint(count=1, start=0)[0]["Authorization"]
        second = self._mint(count=1, start=1)[0]["Authorization"]
        self.assertNotEqual(first, second)

    def test_refuses_production_without_opt_in(self):
        """生产环境(``DEBUG=0``)未显式放行时命令抛 ``CommandError``。

        参数说明:
            无。
        """
        with override_settings(DEBUG=False), self.assertRaises(CommandError):
            call_command("perf_tokens", out=str(self._out_file()), stdout=StringIO())

    def test_refuses_when_no_test_accounts(self):
        """没有可签账号时命令抛 ``CommandError``。

        参数说明:
            无。
        """
        User.objects.all().delete()
        with self.assertRaises(CommandError):
            call_command("perf_tokens", out=str(self._out_file()), stdout=StringIO())



class PresenceHookTests(APITestCase):
    """在线状态钩子:认证通过即刷新,匿名与被顶号的旧令牌都不算活跃。"""

    def setUp(self):
        """清空缓存并建一个普通用户。"""
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(phone="13800138000")

    def _login(self):
        """给测试客户端装上当前用户的令牌。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``self._login()``

        备注信息:
            令牌用 ``SessionRefreshToken.for_user`` 现签,省去走登录接口;``session_version`` 取自当前库内值。
        """
        token = SessionRefreshToken.for_user(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_authenticated_request_touches_presence(self):
        """认证请求后写入 ``presence:{id}`` 缓存。

        参数说明:
            无。
        """
        self._login()
        resp = self.client.get("/api/v1/users/me")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(cache.get(f"presence:{self.user.id}"))

    def test_anonymous_request_does_not_touch(self):
        """匿名请求不写在线状态。

        参数说明:
            无。
        """
        self.client.get("/api/v1/health")
        self.assertIsNone(cache.get(f"presence:{self.user.id}"))

    def test_rejected_stale_token_does_not_touch(self):
        # 被顶号的旧令牌(40101)不算一次「活跃」
        """被顶号的旧令牌返回 401,且不算一次活跃。

        参数说明:
            无。
        """
        self._login()
        self.user.session_version += 1
        self.user.save(update_fields=["session_version"])
        resp = self.client.get("/api/v1/users/me")
        self.assertEqual(resp.status_code, 401)
        self.assertIsNone(cache.get(f"presence:{self.user.id}"))


class TotpTests(SimpleTestCase):
    """TOTP:标准测试向量、时间窗、密钥与 otpauth 地址(H6)。"""

    def test_matches_rfc6238_sha1_vector(self):
        """RFC 6238 的 SHA1 向量(取 6 位)必须一致。

        参数说明:
            无。
        """
        secret = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
        self.assertEqual(totp.code_at(secret, 59), "287082")

    def test_verify_allows_one_step_window(self):
        """前后一个时间步内都算有效,超出则拒绝。

        参数说明:
            无。
        """
        secret = totp.generate_secret()
        code = totp.code_at(secret, 1_700_000_000)
        self.assertTrue(totp.verify(secret, code, moment=1_700_000_000))
        self.assertTrue(totp.verify(secret, code, moment=1_700_000_030))
        self.assertFalse(totp.verify(secret, code, moment=1_700_000_120))
        self.assertFalse(totp.verify(secret, "000000", moment=1_700_000_000))

    def test_provisioning_uri_contains_secret_and_issuer(self):
        """otpauth 地址要带密钥、发行方与 6 位/30 秒参数。

        参数说明:
            无。
        """
        uri = totp.provisioning_uri("ABC234", "13800138000")
        self.assertTrue(uri.startswith("otpauth://totp/"))
        self.assertIn("secret=ABC234", uri)
        self.assertIn("issuer=chat_app", uri)
        self.assertIn("digits=6", uri)
        self.assertIn("period=30", uri)


class LoginThrottleTests(TestCase):
    """后台登录失败锁定:账号维度达到上限后,正确密码也拒绝(H6)。"""

    def setUp(self):
        """建一个可登录的运营账号,并清空失败计数。"""
        cache.clear()
        self.addCleanup(cache.clear)
        self.staff = User.objects.create_user(phone="13700137000", is_staff=True)
        self.staff.set_password("ops-pass-123")
        self.staff.save(update_fields=["password"])

    def test_locks_after_max_attempts(self):
        """连续 5 次错密码后,第 6 次即使密码正确也返回 None。

        参数说明:
            无。
        """
        for _ in range(5):
            self.assertIsNone(authenticate(username="13700137000", password="wrong"))
        self.assertIsNone(authenticate(username="13700137000", password="ops-pass-123"))
        self.assertEqual(int(cache.get("ops:login:fail:account:13700137000")), 5)

    def test_success_clears_account_counter(self):
        """失败几次后登录成功,账号维度的计数被清空。

        参数说明:
            无。
        """
        for _ in range(3):
            authenticate(username="13700137000", password="wrong")
        self.assertIsNotNone(authenticate(username="13700137000", password="ops-pass-123"))
        self.assertIsNone(cache.get("ops:login:fail:account:13700137000"))


class DevSmsDeployCheckTests(SimpleTestCase):
    """``accounts.E001``:固定验证码 + 空白名单必须在 ``manage.py check`` 里报错。"""

    def _check(self):
        """跑一次 E001 检查(不依赖数据库)。

        参数说明:
            无。

        返回参数:
            检查返回的 ``Error`` 列表(空列表表示通过)。

        使用示例:
            ``errors = self._check()``

        备注信息:
            不依赖数据库,``SimpleTestCase`` 里可直接调;``None`` 是传给 ``register`` 的 app_configs 占位。
        """
        return check_dev_sms_requires_allowlist(None)

    @override_settings(TESTING=False, DEBUG=False, SMS_DEV_MODE=True,
                       SMS_PHONE_WHITELIST=[], SMS_ALLOWLIST_STRICT="")
    def test_error_when_dev_sms_without_allowlist(self):
        """生产口径(DEBUG=0 + 固定码 + 空白名单 + 严格留空)必须报一条 E001。

        ``SMS_ALLOWLIST_STRICT`` 显式钉成空串:检查认这个开关(issue #290)之后,
        不钉的话结果会跟着本机 ``.env`` 走 —— 照 hint 设过 ``=0`` 的机器上会静默变绿。

        参数说明:
            无。
        """
        errors = self._check()
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].id, DEV_SMS_WITHOUT_ALLOWLIST_ID)

    @override_settings(TESTING=False, DEBUG=False, SMS_DEV_MODE=True,
                       SMS_PHONE_WHITELIST=["13700137000"])
    def test_ok_when_seed_present(self):
        """有兜底种子时不报错。

        参数说明:
            无。
        """
        self.assertEqual(self._check(), [])

    @override_settings(TESTING=False, DEBUG=False, SMS_DEV_MODE=False,
                       SMS_PHONE_WHITELIST=[])
    def test_ok_when_dev_sms_disabled(self):
        """固定码关掉后不报错。

        参数说明:
            无。
        """
        self.assertEqual(self._check(), [])

    @override_settings(TESTING=False, DEBUG=True, SMS_DEV_MODE=True,
                       SMS_PHONE_WHITELIST=[])
    def test_skipped_in_debug(self):
        """开发环境(DEBUG=1)不报错 —— 这正是 CI 里永远看不到它的原因。

        参数说明:
            无。
        """
        self.assertEqual(self._check(), [])

    @override_settings(TESTING=True, DEBUG=False, SMS_DEV_MODE=True,
                       SMS_PHONE_WHITELIST=[])
    def test_skipped_in_tests(self):
        """测试运行中不报错(用例会临时改设置)。

        参数说明:
            无。
        """
        self.assertEqual(self._check(), [])
