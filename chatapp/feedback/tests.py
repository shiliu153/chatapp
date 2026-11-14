"""意见反馈接口的测试:鉴权、校验、限流与注销级联。

文件信息:
    文件名称          feedback/tests.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from unittest.mock import patch

from django.core.cache import cache
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import User
from users.models import Profile, ProfileStatus

from .models import Feedback, FeedbackStatus


class FeedbackCreateTests(APITestCase):
    """POST /api/v1/feedback:成功落库、边界校验、封禁与限流。"""

    URL = "/api/v1/feedback"

    def setUp(self):
        """准备已登录的完善资料用户,并清空缓存里的限流计数。

        备注信息:
            限流计数落在缓存里,用例之间必须清;令牌用 ``RefreshToken.for_user`` 现签。
        """
        cache.clear()   # 限流计数在缓存里,用例之间必须清
        self.user = self._make_user("13800138000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")

    def _make_user(self, phone, status=ProfileStatus.COMPLETE):
        """造一个带资料的用户。

        参数说明:
            phone: 手机号。
            status: 资料状态,默认 ``ProfileStatus.COMPLETE``。

        返回参数:
            新建的用户实例。

        使用示例:
            ``self._make_user("13800138000")``

        备注信息:
            手机号同时用作昵称,保证资料必填项齐全;状态可覆盖以模拟封禁。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=phone, status=status)
        return user

    def _post(self, **overrides):
        """提交一条反馈,允许覆盖任意字段。

        参数说明:
            **overrides: 要覆盖的请求字段。

        返回参数:
            接口响应。

        使用示例:
            ``self._post(content="太短了")``

        备注信息:
            默认载荷是一条合法反馈,只覆盖需要断言的字段。
        """
        payload = {"type": "feature", "content": "希望增加夜间模式开关", "contact": ""}
        payload.update(overrides)
        return self.client.post(self.URL, payload, format="json")

    def test_creates_pending_feedback(self):
        """提交成功:落库为待处理,回执不回显处理状态。

        参数说明:
            无。
        """
        resp = self._post(contact="a@b.com")
        self.assertEqual(resp.status_code, 201)
        body = resp.json()
        self.assertEqual(body["type"], "feature")
        self.assertEqual(body["content"], "希望增加夜间模式开关")
        self.assertEqual(body["contact"], "a@b.com")
        self.assertIn("created_at", body)
        self.assertNotIn("status", body)
        feedback = Feedback.objects.get()
        self.assertEqual(feedback.user, self.user)
        self.assertEqual(feedback.status, FeedbackStatus.PENDING)

    def test_trims_content(self):
        """内容前后空白被去掉后再落库。

        参数说明:
            无。
        """
        resp = self._post(content="  希望增加夜间模式开关  ")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Feedback.objects.get().content, "希望增加夜间模式开关")

    def test_rejects_unknown_type(self):
        """反馈类型不在枚举内被拒 400。

        参数说明:
            无。
        """
        self.assertEqual(self._post(type="spam").status_code, 400)

    def test_rejects_content_shorter_than_ten(self):
        """内容不足 10 字被拒 400。

        参数说明:
            无。
        """
        self.assertEqual(self._post(content="太短了").status_code, 400)

    def test_rejects_content_longer_than_500(self):
        """内容超过 500 字被拒 400。

        参数说明:
            无。
        """
        self.assertEqual(self._post(content="x" * 501).status_code, 400)

    def test_rejects_blank_content(self):
        """纯空白内容被拒 400(先去空白再判长度)。

        参数说明:
            无。
        """
        self.assertEqual(self._post(content="   ").status_code, 400)

    def test_rejects_contact_longer_than_64(self):
        """联系方式超过 64 字被拒 400。

        参数说明:
            无。
        """
        self.assertEqual(self._post(contact="x" * 65).status_code, 400)

    def test_requires_auth(self):
        """未带令牌提交被拒 401。

        参数说明:
            无。
        """
        self.client.credentials()
        self.assertEqual(self._post().status_code, 401)

    def test_heavy_banned_forbidden(self):
        """``banned_heavy`` 账号提交被全局权限类挡成 403。

        参数说明:
            无。
        """
        self.user.profile.status = ProfileStatus.BANNED_HEAVY
        self.user.profile.save(update_fields=["status"])
        self.assertEqual(self._post().status_code, 403)

    def test_light_banned_can_submit(self):
        """``banned_light`` 只禁滑卡,仍可提交反馈 201。

        参数说明:
            无。
        """
        self.user.profile.status = ProfileStatus.BANNED_LIGHT
        self.user.profile.save(update_fields=["status"])
        self.assertEqual(self._post().status_code, 201)

    def test_throttled(self):
        """超出限流额度后第二次提交返回 429。

        参数说明:
            无。
        """
        from .throttles import FeedbackThrottle
        with patch.object(FeedbackThrottle, "rate", "1/day", create=True):
            self.assertEqual(self._post().status_code, 201)
            self.assertEqual(self._post().status_code, 429)

    def test_deleted_with_account(self):
        """注销账号后其反馈被级联删除。

        参数说明:
            无。
        """
        self._post()
        self.user.delete()
        self.assertEqual(Feedback.objects.count(), 0)
