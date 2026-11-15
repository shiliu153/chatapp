"""并发写入的正确性:唯一约束 + ``get_or_create`` 在竞态下必须只留一行。

为什么单独一个文件:幂等逻辑在单线程测试里永远是对的。真正的风险是「两个请求
同时判断『还没赞过』然后同时 INSERT」——只有一个能成功,另一个必须被数据库唯一
约束挡下并回查,而不是 500。这里用线程池复现这个窗口。

用 ``TransactionTestCase``:``TestCase`` 把每个用例包在事务里,线程看不到未提交数据,
测不出竞态。
"""

from concurrent.futures import ThreadPoolExecutor

from django.contrib.auth import get_user_model
from django.test import TransactionTestCase
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken

from discovery.models import Match, Swipe, SwipeAction
from feed.models import Post, PostLike
from users.models import Photo, PhotoStatus, Profile, ProfileStatus

User = get_user_model()


def _make_user(phone: str) -> User:
    """造一个资料完善、带一张已过审照片的用户。

    参数说明:
        phone: 手机号(兼昵称)。

    返回参数:
        新建用户。

    使用示例:
        ``self.me = _make_user("13800138000")``(见本文件 ``setUp``)

    备注信息:
        资料写成 ``ProfileStatus.COMPLETE`` 且照片 ``APPROVED``,
        否则接口会因「资料未完善 / 照片待审」提前 403,测不到并发写本身。
    """
    user = User.objects.create_user(phone=phone)
    Profile.objects.create(user=user, nickname=phone, gender="female",
                           birthday="2000-01-01", city="上海", bio="你好",
                           status=ProfileStatus.COMPLETE)
    Photo.objects.create(user=user, file="photos/x.png", status=PhotoStatus.APPROVED)
    return user


class ConcurrentWriteTests(TransactionTestCase):
    """同一用户对同一资源的并发写:结果必须只有一行,且不出现 5xx。"""

    def setUp(self):
        self.me = _make_user("13800138000")
        self.other = _make_user("13900139000")
        self.post = Post.objects.create(author=self.other, text="并发测试")
        self.token = str(RefreshToken.for_user(self.me).access_token)

    def _client(self) -> APIClient:
        """返回一个带当前用户令牌的客户端(每个线程一个实例)。

        返回参数:
            已注入 Authorization 头的 ``APIClient``。

        使用示例:
            ``return self._client().post(url)``(见本文件的并发写用例)

        备注信息:
            ``APIClient`` 共享会有线程安全问题,所以每个线程各拿一个;
            令牌取自 ``setUp`` 里预生成的 ``self.token``。
        """
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {self.token}")
        return client

    def test_concurrent_like_creates_single_row(self):
        """6 个线程同时点赞:只有一行,且没有 5xx。"""
        url = f"/api/v1/posts/{self.post.id}/like"

        def hit(_):
            return self._client().post(url)

        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(hit, range(6)))

        self.assertFalse([r.status_code for r in responses if r.status_code >= 500])
        self.assertEqual(PostLike.objects.filter(post=self.post, user=self.me).count(), 1)
        # 只有一次是「新建」,其余都是幂等命中
        self.assertEqual(sum(1 for r in responses if r.status_code == 201), 1)

    def test_concurrent_swipe_creates_single_row_and_match(self):
        """6 个线程同时滑同一个人:一条 Swipe、一个 Match。"""
        Swipe.objects.create(swiper=self.other, target=self.me, action=SwipeAction.LIKE)
        url = "/api/v1/discovery/swipe"
        payload = {"target_user_id": self.other.id, "action": "like"}

        def hit(_):
            return self._client().post(url, payload, format="json")

        with ThreadPoolExecutor(max_workers=6) as pool:
            responses = list(pool.map(hit, range(6)))

        self.assertFalse([r.status_code for r in responses if r.status_code >= 500])
        self.assertEqual(Swipe.objects.filter(swiper=self.me, target=self.other).count(), 1)
        self.assertEqual(Match.objects.count(), 1)
        # 互喜的结论对所有并发请求一致
        self.assertTrue(all(r.json().get("matched") for r in responses if r.status_code == 200))
