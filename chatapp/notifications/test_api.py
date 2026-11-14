"""站内通知接口(H-2)的测试:列表、未读数与标记已读。

覆盖场景:
    - 列表只返回自己的通知,按时间倒序,形状为 ``{count, next_cursor, has_more, results}``;
    - 90 天窗口:更早的通知不出现,也不进未读数;
    - 触发者摘要:账号 id / 昵称 / 首张已过审照片头像,无照片为 ``null``;
    - 未读数与列表同口径;
    - 标记已读:按 ids、按 all、幂等、只影响自己、空 body 400;
    - 限流:通知列表与未读数各按用户计数,超限 429(两个 scope 独立);
    - 未认证一律 401。

文件信息:
    文件名称          notifications/test_api.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from notifications.models import (InAppNotification, NotificationKind, NotificationPreference,
                                  NotificationTarget)
from notifications.throttles import NotificationsThrottle, NotificationsUnreadThrottle
from users.models import Photo, PhotoStatus, Profile

User = get_user_model()


def _notification(user, **overrides):
    """造一条通知(默认参数可被覆盖)。

    参数说明:
        user: 接收者。
        **overrides: 覆盖默认字段。

    返回参数:
        新建的 ``InAppNotification``。

    使用示例:
        ``_notification(self.me, actor=self.actor)``

    备注信息:
        默认落一条 post 类点赞通知:text 为「小明 赞了你的动态」,target_id=3。
    """
    fields = {
        "user": user,
        "kind": NotificationKind.POST_LIKE,
        "target_kind": NotificationTarget.POST,
        "target_id": 3,
        "text": "小明 赞了你的动态",
    }
    fields.update(overrides)
    return InAppNotification.objects.create(**fields)


class NotificationListApiTests(APITestCase):
    """GET /api/v1/notifications 与 /unread_count。"""

    def setUp(self):
        """每个用例前建好接收者与触发者,并给客户端带上接收者的 access token。

        备注信息:
            触发者带昵称「小明」,用于断言列表里的 actor 摘要。
        """
        self.me = User.objects.create_user(phone="13800138000")
        self.actor = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.actor, nickname="小明")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _get(self, path="/api/v1/notifications", **params):
        """发一次 GET。

        参数说明:
            path: 请求路径,默认通知列表。
            **params: 查询参数。

        返回参数:
            DRF 响应对象。

        使用示例:
            ``self._get("/api/v1/notifications/unread_count")``

        备注信息:
            查询参数按 dict 传入,由测试客户端拼成 query string。
        """
        return self.client.get(path, params)

    def test_returns_own_notifications_only(self):
        """列表只返回本人的通知,别人的一条都不出现。"""
        mine = _notification(self.me, actor=self.actor)
        other = User.objects.create_user(phone="13700137000")
        _notification(other)
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data["count"], 1)
        self.assertEqual([item["id"] for item in resp.data["results"]], [mine.id])

    def test_cursor_envelope_shape(self):
        """列表信封固定为 count、next_cursor、has_more、results 四个键。"""
        _notification(self.me)
        resp = self._get(limit=1)
        self.assertEqual(set(resp.data), {"count", "next_cursor", "has_more", "results"})
        self.assertFalse(resp.data["has_more"])

    def test_orders_newest_first(self):
        """列表按创建时间倒序,新通知排在前面。"""
        first = _notification(self.me, text="第一条")
        second = _notification(self.me, text="第二条")
        resp = self._get()
        self.assertEqual([item["id"] for item in resp.data["results"]],
                         [second.id, first.id])

    def test_item_shape_and_actor_summary(self):
        """单条通知字段齐全,触发者头像取首张已过审照片。"""
        Photo.objects.create(user=self.actor, file="photos/x.png", status=PhotoStatus.APPROVED)
        Photo.objects.create(user=self.actor, file="photos/pending.png",
                             status=PhotoStatus.PENDING)
        _notification(self.me, actor=self.actor)
        item = self._get().data["results"][0]
        self.assertEqual(set(item), {"id", "kind", "text", "is_read", "created_at",
                                     "actor", "target"})
        self.assertEqual(item["kind"], NotificationKind.POST_LIKE)
        self.assertFalse(item["is_read"])
        self.assertEqual(item["actor"]["id"], self.actor.id)
        self.assertEqual(item["actor"]["nickname"], "小明")
        self.assertIn("photos/x.png", item["actor"]["avatar"])
        self.assertEqual(item["target"], {"kind": "post", "id": 3})

    def test_actor_without_photo_has_null_avatar(self):
        """触发者没有已过审照片时头像为 null。"""
        _notification(self.me, actor=self.actor)
        item = self._get().data["results"][0]
        self.assertIsNone(item["actor"]["avatar"])

    def test_system_notification_has_null_actor(self):
        """系统通知没有触发者,target 为 none 且 id 为 null。"""
        _notification(self.me, kind=NotificationKind.SYSTEM, target_kind=NotificationTarget.NONE,
                      target_id=None, text="你的举报已处理")
        item = self._get().data["results"][0]
        self.assertIsNone(item["actor"])
        self.assertEqual(item["target"], {"kind": "none", "id": None})

    def test_old_notifications_are_hidden(self):
        """超出 90 天窗口的通知不出现在列表里。"""
        old = _notification(self.me, text="很久以前")
        InAppNotification.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=91))
        self.assertEqual(self._get().data["count"], 0)

    def test_unread_count_matches_window_and_flag(self):
        """未读数只统计窗口内且未读的通知。"""
        _notification(self.me)
        read = _notification(self.me, is_read=True)
        old = _notification(self.me)
        InAppNotification.objects.filter(pk=old.pk).update(
            created_at=timezone.now() - timedelta(days=91))
        resp = self._get("/api/v1/notifications/unread_count")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data, {"unread": 1})
        self.assertTrue(InAppNotification.objects.get(pk=read.pk).is_read)

    def test_list_is_throttled_per_user(self):
        """R4-C1:通知列表按用户限流,超限 429(生产额度 240/hour)。"""
        cache.clear()                      # 限流计数在缓存里,跨用例残留会误报
        self.addCleanup(cache.clear)
        with patch.dict(NotificationsThrottle.THROTTLE_RATES, {"notifications": "2/hour"}):
            responses = [self._get() for _ in range(3)]
        self.assertEqual([resp.status_code for resp in responses], [200, 200, 429])
        self.assertEqual(responses[-1].data["code"], 429)      # 统一错误信封
        self.assertIn("Retry-After", responses[-1])

    def test_unread_count_is_throttled_per_user(self):
        """R4-C1:未读数按用户限流,超限 429(生产额度 480/hour),与列表额度互不占用。"""
        cache.clear()
        self.addCleanup(cache.clear)
        path = "/api/v1/notifications/unread_count"
        with patch.dict(NotificationsUnreadThrottle.THROTTLE_RATES,
                        {"notifications_unread": "2/hour"}):
            responses = [self._get(path) for _ in range(3)]
        self.assertEqual([resp.status_code for resp in responses], [200, 200, 429])
        self.assertEqual(responses[-1].data["code"], 429)
        # 各自的 scope 独立计数:未读数被限了,列表照常可用
        self.assertEqual(self._get().status_code, 200)

    def test_requires_auth(self):
        """未登录访问列表与未读数都返回 401。"""
        self.client.credentials()
        self.assertEqual(self._get().status_code, 401)
        self.assertEqual(self._get("/api/v1/notifications/unread_count").status_code, 401)


class NotificationReadApiTests(APITestCase):
    """POST /api/v1/notifications/read。"""

    def setUp(self):
        """每个用例前建好本人与他人账号,并给客户端带上本人的 access token。

        备注信息:
            他人账号用来验证「不能标记别人的通知」。
        """
        self.me = User.objects.create_user(phone="13800138000")
        self.other = User.objects.create_user(phone="13900139000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def _read(self, body):
        """发一次标记已读。

        参数说明:
            body: JSON body(dict)。

        返回参数:
            DRF 响应对象。

        使用示例:
            ``self._read({"ids": [first.id]})``

        备注信息:
            固定 POST /api/v1/notifications/read,body 按 JSON 提交。
        """
        return self.client.post("/api/v1/notifications/read", body, format="json")

    def test_marks_given_ids(self):
        """按 ids 标记已读只影响指定的那几条。"""
        first = _notification(self.me)
        second = _notification(self.me)
        self.assertEqual(self._read({"ids": [first.id]}).status_code, 204)
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertTrue(first.is_read)
        self.assertFalse(second.is_read)

    def test_marks_all(self):
        """all=true 时把本人全部通知标记为已读。"""
        _notification(self.me)
        _notification(self.me)
        self.assertEqual(self._read({"all": True}).status_code, 204)
        self.assertFalse(InAppNotification.objects.filter(user=self.me, is_read=False).exists())

    def test_is_idempotent(self):
        """同一条通知重复标记已读都返回 204。"""
        notification = _notification(self.me)
        self.assertEqual(self._read({"ids": [notification.id]}).status_code, 204)
        self.assertEqual(self._read({"ids": [notification.id]}).status_code, 204)

    def test_cannot_mark_other_users_notification(self):
        """标记别人的通知返回 204,但那条记录保持未读。"""
        theirs = _notification(self.other)
        self.assertEqual(self._read({"ids": [theirs.id]}).status_code, 204)
        theirs.refresh_from_db()
        self.assertFalse(theirs.is_read)

    def test_all_does_not_touch_other_users(self):
        """all=true 不会碰到别人的通知。"""
        theirs = _notification(self.other)
        self._read({"all": True})
        theirs.refresh_from_db()
        self.assertFalse(theirs.is_read)

    def test_empty_body_rejected(self):
        """空 body 与空 ids 都返回 400。"""
        self.assertEqual(self._read({}).status_code, 400)
        self.assertEqual(self._read({"ids": []}).status_code, 400)

    def test_requires_auth(self):
        """未登录标记已读返回 401。"""
        self.client.credentials()
        self.assertEqual(self._read({"all": True}).status_code, 401)


class NotificationPreferenceApiTests(APITestCase):
    """``/push/preferences`` 新增 ``social`` 字段后的读写形状。"""

    def setUp(self):
        """每个用例前建好账号,并给客户端带上 access token。

        备注信息:
            只验证 social 字段的读写形状,不造通知数据。
        """
        self.me = User.objects.create_user(phone="13800138000")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.me).access_token}")

    def test_social_defaults_on_and_can_be_turned_off(self):
        """social 字段默认开,单独关掉后 system 仍是开。"""
        resp = self.client.get("/api/v1/push/preferences")
        self.assertTrue(resp.data["social"])
        resp = self.client.patch("/api/v1/push/preferences", {"social": False}, format="json")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.data["social"])
        self.assertTrue(NotificationPreference.for_user(self.me).system)


class NotificationModelWindowTests(TestCase):
    """窗口口径的纯模型断言(避免与接口测试混在一起)。"""

    def test_default_target_kind_is_none(self):
        """不传 target_kind 时默认落 NONE,且 target_id 为 null。"""
        user = User.objects.create_user(phone="13800138000")
        notification = InAppNotification.objects.create(
            user=user, kind=NotificationKind.SYSTEM, text="系统")
        self.assertEqual(notification.target_kind, NotificationTarget.NONE)
        self.assertIsNone(notification.target_id)
