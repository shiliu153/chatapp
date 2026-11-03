"""广场分页的两段式实现:顺序、总数与可见性必须与全量查询一致。

背景:2026-11-03 把「一次带聚合的全表查询」改成「先取当页 id,再聚合 10 条」
(见 docs/ops/scale-report.md)。这里钉住重构前后**对外行为不变**。
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from feed.models import Post
from feed.services import page_visible_posts, visible_posts
from users.models import Profile, ProfileStatus

User = get_user_model()


def _make_author(phone: str, status: str = ProfileStatus.COMPLETE):
    """造一个带资料的作者。

    Args:
        phone: 手机号。
        status: 资料状态(用于验证重封禁作者被排除)。

    Returns:
        新建用户。
    """
    user = User.objects.create_user(phone=phone)
    Profile.objects.create(user=user, nickname=phone, status=status)
    return user


class PageVisiblePostsTests(TestCase):
    """服务层:顺序、总数、可见性。"""

    def setUp(self):
        self.viewer = _make_author("13800138000")
        self.author = _make_author("13900139000")
        self.posts = [Post.objects.create(author=self.author, text=f"动态{i}")
                      for i in range(25)]

    def test_order_matches_full_queryset(self):
        """分页结果的顺序必须与「全量注解查询」一致。"""
        expected = [post.id for post in visible_posts(self.viewer)]
        rows, total = page_visible_posts(self.viewer, 0, 25)
        self.assertEqual([post.id for post in rows], expected)
        self.assertEqual(total, 25)

    def test_second_page_continues_without_overlap(self):
        """第二页从第 11 条开始,与第一页无重叠。"""
        first, _ = page_visible_posts(self.viewer, 0, 10)
        second, total = page_visible_posts(self.viewer, 10, 10)
        self.assertEqual(total, 25)
        self.assertEqual(len(first), 10)
        self.assertEqual(len(second), 10)
        self.assertFalse({p.id for p in first} & {p.id for p in second})

    def test_banned_author_is_excluded_from_count_and_rows(self):
        """重封禁作者既不出现在列表里,也不计入总数。"""
        banned = _make_author("13700137000", status=ProfileStatus.BANNED_HEAVY)
        Post.objects.create(author=banned, text="应被过滤")
        rows, total = page_visible_posts(self.viewer, 0, 50)
        self.assertEqual(total, 25)
        self.assertNotIn(banned.id, [post.author_id for post in rows])

    def test_empty_page_returns_empty_list(self):
        """越界页返回空列表,总数仍然正确。"""
        rows, total = page_visible_posts(self.viewer, 100, 10)
        self.assertEqual(rows, [])
        self.assertEqual(total, 25)


class PostsApiShapeTests(APITestCase):
    """接口层:响应结构保持不变(客户端依赖 count/next/previous/results)。"""

    def setUp(self):
        self.viewer = _make_author("13800138000")
        author = _make_author("13900139000")
        for index in range(15):
            Post.objects.create(author=author, text=f"动态{index}")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.viewer).access_token}")

    def test_response_keeps_limit_offset_contract(self):
        """首屏返回 count/next,第二页返回 previous。"""
        first = self.client.get("/api/v1/posts?limit=10&offset=0").json()
        self.assertEqual(first["count"], 15)
        self.assertIsNotNone(first["next"])
        self.assertIsNone(first["previous"])
        self.assertEqual(len(first["results"]), 10)

        second = self.client.get("/api/v1/posts?limit=10&offset=10").json()
        self.assertEqual(len(second["results"]), 5)
        self.assertIsNone(second["next"])
        self.assertIsNotNone(second["previous"])
