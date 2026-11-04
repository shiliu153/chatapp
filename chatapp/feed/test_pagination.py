"""广场分页:两段式取数 + 复合游标(keyset)。

两层断言:
    1. **服务层** ``page_visible_posts``:顺序、总数、可见性与「全量注解查询」一致
       (2026-11-03 把「一次带聚合的全表查询」改成「先取当页 id,再聚合几条」时钉住的);
    2. **接口层**:游标协议(``before`` / ``next_cursor`` / ``has_more``)翻页不重不漏,
       且翻页期间有人发新动态也不会重复或漏读(审查 N-5);``offset`` 老路径保持原样,
       因为线上还有没升级的客户端。
"""

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from config.cursor import decode_cursor
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
    """服务层:顺序、总数、可见性、游标连续性。"""

    def setUp(self):
        self.viewer = _make_author("13800138000")
        self.author = _make_author("13900139000")
        self.posts = [Post.objects.create(author=self.author, text=f"动态{i}")
                      for i in range(25)]

    def test_order_matches_full_queryset(self):
        """分页结果的顺序必须与「全量注解查询」一致。"""
        expected = [post.id for post in visible_posts(self.viewer)]
        page = page_visible_posts(self.viewer, 25)
        self.assertEqual([post.id for post in page.rows], expected)
        self.assertEqual(page.total, 25)
        self.assertFalse(page.has_more)
        self.assertIsNone(page.next_cursor)

    def test_second_page_continues_without_overlap(self):
        """第二页接着游标走,与第一页无重叠。"""
        first = page_visible_posts(self.viewer, 10)
        self.assertTrue(first.has_more)
        self.assertIsNotNone(first.next_cursor)
        second = page_visible_posts(self.viewer, 10,
                                    before=decode_cursor(first.next_cursor))
        self.assertEqual(second.total, 25)
        self.assertEqual(len(first.rows), 10)
        self.assertEqual(len(second.rows), 10)
        self.assertFalse({post.id for post in first.rows} & {post.id for post in second.rows})

    def test_cursor_survives_new_post_between_pages(self):
        """翻页期间有人发了新动态:第二页不重复第 1 页的行,也不漏掉第 11 条。"""
        first = page_visible_posts(self.viewer, 10)
        Post.objects.create(author=self.author, text="翻页之间插入的新动态")
        second = page_visible_posts(self.viewer, 10,
                                    before=decode_cursor(first.next_cursor))
        ids = [post.id for post in first.rows + second.rows]
        self.assertEqual(len(ids), len(set(ids)))                        # 不重复
        self.assertEqual(len(ids), 20)
        self.assertEqual({post.id for post in second.rows},
                         {post.id for post in self.posts[::-1][10:20]})   # 不漏读

    def test_legacy_offset_slice_still_works(self):
        """老客户端仍按 offset 切片:第 11 条开始、与第一页不重叠。"""
        first = page_visible_posts(self.viewer, 10)
        second = page_visible_posts(self.viewer, 10, offset=10)
        self.assertFalse({post.id for post in first.rows} & {post.id for post in second.rows})
        self.assertEqual([post.id for post in second.rows],
                         [post.id for post in self.posts[::-1][10:20]])

    def test_banned_author_is_excluded_from_count_and_rows(self):
        """重封禁作者既不出现在列表里,也不计入总数。"""
        banned = _make_author("13700137000", status=ProfileStatus.BANNED_HEAVY)
        Post.objects.create(author=banned, text="应被过滤")
        page = page_visible_posts(self.viewer, 50)
        self.assertEqual(page.total, 25)
        self.assertNotIn(banned.id, [post.author_id for post in page.rows])

    def test_empty_page_returns_empty_list(self):
        """越界页返回空列表,总数仍然正确。"""
        page = page_visible_posts(self.viewer, 10, offset=100)
        self.assertEqual(page.rows, [])
        self.assertEqual(page.total, 25)
        self.assertFalse(page.has_more)


class PostsApiShapeTests(APITestCase):
    """接口层:游标协议 + offset 兼容路径的响应形状。"""

    def setUp(self):
        self.viewer = _make_author("13800138000")
        self.author = _make_author("13900139000")
        for index in range(15):
            Post.objects.create(author=self.author, text=f"动态{index}")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.viewer).access_token}")

    def test_cursor_contract(self):
        """首屏给 next_cursor + has_more,末页把两者都收掉。"""
        first = self.client.get("/api/v1/posts?limit=10").json()
        self.assertEqual(first["count"], 15)
        self.assertTrue(first["has_more"])
        self.assertEqual(len(first["results"]), 10)
        self.assertNotIn("next", first)
        second = self.client.get(
            "/api/v1/posts", {"limit": 10, "before": first["next_cursor"]}).json()
        self.assertEqual(len(second["results"]), 5)
        self.assertFalse(second["has_more"])
        self.assertIsNone(second["next_cursor"])
        first_ids = [item["id"] for item in first["results"]]
        second_ids = [item["id"] for item in second["results"]]
        self.assertFalse(set(first_ids) & set(second_ids))

    def test_invalid_cursor_is_400(self):
        """游标坏了给 400 + 统一错误信封,不能漏成 500。"""
        response = self.client.get("/api/v1/posts?limit=10&before=not-a-cursor")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], 400)
        self.assertIn("游标", response.json()["message"])

    def test_offset_request_keeps_limit_offset_contract(self):
        """带 offset 的老客户端:仍是 count/next/previous/results。"""
        first = self.client.get("/api/v1/posts?limit=10&offset=0").json()
        self.assertEqual(first["count"], 15)
        self.assertIsNotNone(first["next"])
        self.assertIsNone(first["previous"])
        self.assertEqual(len(first["results"]), 10)

        second = self.client.get("/api/v1/posts?limit=10&offset=10").json()
        self.assertEqual(len(second["results"]), 5)
        self.assertIsNone(second["next"])
        self.assertIsNotNone(second["previous"])
