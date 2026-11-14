"""``dev_reset_pair`` 开发命令的用例:账号 id 解析口径与报错文案。

为什么单独一个文件:该命令曾经用 ``int(raw.lstrip("u"))`` 解析 ``--a`` / ``--b``,
``uu8``、``uuuu8`` 都会被静默解析成 8 —— 手误多打一个 ``u`` 就会把 8 号账号
的数据删掉,而且看起来像成功。这里的用例把口径钉成「只有 ``u<数字>`` 或纯数字算数」,
并锁住格式非法与账号不存在两种报错文案。
"""

import io

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from discovery.models import Match, Swipe, SwipeAction

User = get_user_model()


class DevResetPairCommandTests(TestCase):
    """``dev_reset_pair`` 的账号 id 解析与报错口径。"""

    def setUp(self):
        self.alice = User.objects.create_user(phone="13800138001")
        self.bob = User.objects.create_user(phone="13800138002")
        Swipe.objects.create(swiper=self.alice, target=self.bob, action=SwipeAction.LIKE)
        Match.objects.create(**Match.pair_kwargs(self.alice, self.bob))

    def _run(self, a, b):
        """跑一次命令并返回标准输出。

        Args:
            a: ``--a`` 的取值。
            b: ``--b`` 的取值。

        Returns:
            命令写进 stdout 的文本。
        """
        out = io.StringIO()
        call_command("dev_reset_pair", a=a, b=b, stdout=out)
        return out.getvalue()

    def test_u_prefix_and_plain_digits_resolve_same_account(self):
        text = self._run(f"u{self.alice.id}", str(self.bob.id))
        self.assertIn(f"已重置 u{self.alice.id} <-> u{self.bob.id}", text)
        self.assertFalse(Swipe.objects.exists())
        self.assertFalse(Match.objects.exists())

    def test_plain_digits_accepted_on_both_sides(self):
        text = self._run(str(self.alice.id), str(self.bob.id))
        self.assertIn(f"已重置 u{self.alice.id} <-> u{self.bob.id}", text)

    def test_uu_prefix_rejected_and_data_untouched(self):
        with self.assertRaisesMessage(CommandError, "格式不对"):
            self._run(f"uu{self.alice.id}", str(self.bob.id))
        self.assertTrue(Swipe.objects.exists())
        self.assertTrue(Match.objects.exists())

    def test_lone_u_rejected(self):
        with self.assertRaisesMessage(CommandError, "格式不对"):
            self._run("u", str(self.bob.id))

    def test_trailing_garbage_rejected(self):
        with self.assertRaisesMessage(CommandError, "格式不对"):
            self._run(f"u{self.alice.id}x", str(self.bob.id))

    def test_empty_value_rejected(self):
        with self.assertRaisesMessage(CommandError, "格式不对"):
            self._run("", str(self.bob.id))

    def test_unknown_account_rejected(self):
        with self.assertRaisesMessage(CommandError, "没有"):
            self._run("u999999999", str(self.bob.id))
