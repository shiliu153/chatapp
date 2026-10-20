"""意见反馈接口的测试:鉴权、校验、限流与注销级联。"""

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
        cache.clear()   # 限流计数在缓存里,用例之间必须清
        self.user = self._make_user("13800138000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")

    def _make_user(self, phone, status=ProfileStatus.COMPLETE):
        """造一个带资料的用户。

        Args:
            phone: 手机号。
            status: 资料状态,默认完善。

        Returns:
            新建的用户实例。
        """
        user = User.objects.create_user(phone=phone)
        Profile.objects.create(user=user, nickname=phone, status=status)
        return user

    def _post(self, **overrides):
        """提交一条反馈,允许覆盖任意字段。

        Args:
            **overrides: 要覆盖的请求字段。

        Returns:
            接口响应。
        """
        payload = {"type": "feature", "content": "希望增加夜间模式开关", "contact": ""}
        payload.update(overrides)
        return self.client.post(self.URL, payload, format="json")

    def test_creates_pending_feedback(self):
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
        resp = self._post(content="  希望增加夜间模式开关  ")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(Feedback.objects.get().content, "希望增加夜间模式开关")

    def test_rejects_unknown_type(self):
        self.assertEqual(self._post(type="spam").status_code, 400)

    def test_rejects_content_shorter_than_ten(self):
        self.assertEqual(self._post(content="太短了").status_code, 400)

    def test_rejects_content_longer_than_500(self):
        self.assertEqual(self._post(content="x" * 501).status_code, 400)

    def test_rejects_blank_content(self):
        self.assertEqual(self._post(content="   ").status_code, 400)

    def test_rejects_contact_longer_than_64(self):
        self.assertEqual(self._post(contact="x" * 65).status_code, 400)

    def test_requires_auth(self):
        self.client.credentials()
        self.assertEqual(self._post().status_code, 401)

    def test_heavy_banned_forbidden(self):
        self.user.profile.status = ProfileStatus.BANNED_HEAVY
        self.user.profile.save(update_fields=["status"])
        self.assertEqual(self._post().status_code, 403)

    def test_light_banned_can_submit(self):
        self.user.profile.status = ProfileStatus.BANNED_LIGHT
        self.user.profile.save(update_fields=["status"])
        self.assertEqual(self._post().status_code, 201)

    def test_throttled(self):
        from .throttles import FeedbackThrottle
        with patch.object(FeedbackThrottle, "rate", "1/day", create=True):
            self.assertEqual(self._post().status_code, 201)
            self.assertEqual(self._post().status_code, 429)

    def test_deleted_with_account(self):
        self._post()
        self.user.delete()
        self.assertEqual(Feedback.objects.count(), 0)
