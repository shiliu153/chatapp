"""IM 应用的测试:客户端门面、Celery 副作用任务、管理命令与接口。

覆盖场景:
    - 客户端门面(``im/client.py``):每个业务函数只转调 ``self_client``,
      配对灰条双向发、系统通知用 ``system_notice`` 身份;
    - 动态评论通知:任务侧收件人、自己评自己不发送、评论已删则静默;
    - 管理命令:``im_send``(文本与灰条互斥)、``im_setup_system_account``、
      ``im_sync_nicknames``(含失败计数)、``im_sync_pairs``(回填配对);
    - IM 凭证接口:签发自建 token、重封禁 403、会话版本同步失败则 fail-closed、
      踢旧会话必须先于签发;
    - 副作用任务:``False`` 转异常以触发重试、缺用户时静默、注销删号不查库、
      解除配对时双向拉黑。

文件信息:
    文件名称          im/tests.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import io
import json
import os
import shutil
import subprocess
import tempfile
import time
from datetime import timedelta
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone
from PIL import Image
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import Photo, PhotoStatus, Profile, ProfileStatus
from users.services import get_profile

from discovery.models import Match

from feed.models import Post, PostComment

from . import media_sign, voice
from .client import (black_list_add, black_list_delete, delete_account,
                     ensure_account, import_account, kick_user, pair_add,
                     send_ban_lifted, send_ban_notice, send_custom_elem,
                     send_match_notice, send_post_commented, send_post_replied,
                     send_report_handled, send_text, set_profile_avatar,
                     set_profile_nick, set_session_version)
from .models import ChatImage, ChatImageStatus, ChatVoice, ChatVoiceStatus
from .throttles import ChatImageThrottle
from .token import mint_im_token, verify_im_token
from .tasks import (ban_lifted, ban_notice, blacklist_add, blacklist_remove,
                    delete_account as delete_account_task,
                    import_account as import_account_task, kick_device,
                    kick_pending, kick_pending_key,
                    post_commented as post_commented_task,
                    report_handled as report_handled_task, sync_profile,
                    unmatch_blacklist)
from .tasks import send_match_notice as send_match_notice_task

User = get_user_model()

# 1×1 透明 PNG:最小合法图片,用于上传类用例
PNG_1PX = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
           b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
           b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")

# 腾讯云 IM 分支已于 2026-11-08 删除(backlog D-4):客户端层只剩「转调 self_client」,
# 所以这里断言的是**委托关系**而不是 REST 报文。
class ClientFacadeTests(SimpleTestCase):
    """``im/client.py`` 门面:每个业务函数都只转调 ``self_client``。"""

    def test_send_custom_elem_delegates(self):
        """自定义消息(灰条/系统通知)直接转调自建客户端。"""
        with patch("im.client.self_client.send_custom_elem", return_value=True) as send:
            self.assertTrue(send_custom_elem("u1", "u2", {"type": "x"}, "hi"))
        send.assert_called_once_with("u1", "u2", {"type": "x"}, "hi")

    def test_match_notice_sends_both_directions(self):
        """配对灰条要双向各发一条,任一条失败整体失败。"""
        with patch("im.client.self_client.send_custom_elem", return_value=True) as send:
            self.assertTrue(send_match_notice("u1", "u2"))
        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args_list[0][0][:2], ("u1", "u2"))
        self.assertEqual(send.call_args_list[1][0][:2], ("u2", "u1"))

    def test_import_account_is_idempotent_ensure(self):
        """``import_account`` 收敛到幂等建号(自建没有独立「导入」概念)。"""
        with patch("im.client.self_client.ensure_account", return_value=True) as ensure:
            self.assertTrue(import_account("u9", "小明"))
        ensure.assert_called_once_with("u9", "小明")

    def test_profile_and_session_helpers_delegate(self):
        """资料/会话版本/配对/踢人这些辅助函数同样只转调。"""
        with patch("im.client.self_client.set_profile_nick", return_value=True) as nick, \
                patch("im.client.self_client.set_profile_avatar", return_value=True) as avatar, \
                patch("im.client.self_client.set_session_version", return_value=True) as sync, \
                patch("im.client.self_client.pair_add", return_value=True) as pair, \
                patch("im.client.self_client.kick_user", return_value=True) as kick:
            self.assertTrue(set_profile_nick("u9", "小明"))
            self.assertTrue(set_profile_avatar("u9", "https://x/a.png"))
            self.assertTrue(set_session_version("u9", 3, "web"))
            self.assertTrue(pair_add("u1", "u2"))
            self.assertTrue(kick_user("u9", True, "app"))
        nick.assert_called_once_with("u9", "小明")
        avatar.assert_called_once_with("u9", "https://x/a.png")
        sync.assert_called_once_with("u9", 3, "web")
        pair.assert_called_once_with("u1", "u2")
        kick.assert_called_once_with("u9", True, "app")

    def test_system_notices_use_system_identity(self):
        """封禁/举报/评论通知都以 ``system_notice`` 身份发出,文案不变。"""
        with patch("im.client.self_client.send_custom_elem", return_value=True) as send:
            self.assertTrue(send_ban_notice("u9", "light", "违规"))
            self.assertTrue(send_report_handled("u9"))
            self.assertTrue(send_post_commented("u9", "小红", "好漂亮"))
            self.assertTrue(send_post_replied("u9", "小红", "好漂亮"))
        self.assertEqual(send.call_count, 4)
        for call in send.call_args_list:
            self.assertEqual(call[0][0], "system_notice")
            self.assertEqual(call[0][1], "u9")
        self.assertEqual(send.call_args_list[1][0][2], {"type": "report_handled"})
        self.assertEqual(send.call_args_list[2][0][3], "小红 评论了你的动态:好漂亮")


class PostCommentedTaskTests(TestCase):
    """动态评论通知的任务层:收件人是作者,自己评自己不打扰,评论已删则静默。"""

    def setUp(self):
        """创建动态作者、评论者与一条动态。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``unittest`` 在每条用例前自动调用 ``setUp()``。

        备注信息:
            评论者资料带昵称「小红」,评论通知文案会用到它。
        """
        self.author = User.objects.create_user(phone="13800138000")
        self.commenter = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.commenter, nickname="小红")
        self.post = Post.objects.create(author=self.author, text="动态")

    def test_task_sends_notice_to_author(self):
        """评论后给动态作者发通知,收件人是作者的 IM 账号。

        参数说明:
            无。
        """
        comment = PostComment.objects.create(post=self.post, author=self.commenter,
                                             text="好漂亮")
        with patch("im.client.send_post_commented", return_value=True) as send:
            post_commented_task.run(comment.id)
        send.assert_called_once_with(self.author.im_user_id, "小红", "好漂亮")

    def test_self_comment_not_sent(self):
        """自己评论自己的动态不发送通知。

        参数说明:
            无。
        """
        comment = PostComment.objects.create(post=self.post, author=self.author, text="自评")
        with patch("im.client.send_post_commented") as send:
            post_commented_task.run(comment.id)
        send.assert_not_called()

    def test_missing_comment_is_silent(self):
        """评论已被删除时任务静默返回,不抛异常。

        参数说明:
            无。
        """
        post_commented_task.run(999999)   # 不抛异常


class ImSendCommandTests(SimpleTestCase):
    """``im_send`` 命令:文本与灰条互斥,发送失败要抛 CommandError。"""

    def test_text_and_notice_are_mutually_exclusive(self):
        """文本与灰条必须二选一,两者都缺或都给都要抛 CommandError。

        参数说明:
            无。
        """
        with self.assertRaises(CommandError):
            call_command("im_send", sender="u1", receiver="u2", text="hi", notice=True)
        with self.assertRaises(CommandError):
            call_command("im_send", sender="u1", receiver="u2")

    def test_sends_text(self):
        """``--text`` 走 ``send_text``,账号与正文原样透传。

        参数说明:
            无。
        """
        with patch("im.management.commands.im_send.send_text", return_value=True) as send:
            call_command("im_send", sender="u1", receiver="u2", text="hi")
        send.assert_called_once_with("u1", "u2", "hi")

    def test_sends_match_notice(self):
        """``--notice`` 走 ``send_custom_elem``,元素类型是 ``match_notice``。

        参数说明:
            无。
        """
        with patch("im.management.commands.im_send.send_custom_elem", return_value=True) as send:
            call_command("im_send", sender="u1", receiver="u2", notice=True)
        args = send.call_args[0]
        self.assertEqual(args[:2], ("u1", "u2"))
        self.assertEqual(args[2], {"type": "match_notice"})

    def test_send_failure_raises(self):
        """发送返回 ``False`` 时命令抛 CommandError,便于 crontab 判失败。

        参数说明:
            无。
        """
        with patch("im.management.commands.im_send.send_text", return_value=False):
            with self.assertRaises(CommandError):
                call_command("im_send", sender="u1", receiver="u2", text="hi")


class ImSetupSystemAccountCommandTests(SimpleTestCase):
    """``im_setup_system_account`` 命令:建「系统通知」账号,失败要抛 CommandError。"""

    def test_command_creates_system_account(self):
        """按固定身份 ``system_notice`` / 「系统通知」建号。

        参数说明:
            无。
        """
        with patch("im.management.commands.im_setup_system_account.ensure_account",
                   return_value=True) as ensure:
            call_command("im_setup_system_account")
        ensure.assert_called_once_with("system_notice", "系统通知")

    def test_command_raises_when_not_ready(self):
        """建号失败时抛 CommandError,不静默成功。

        参数说明:
            无。
        """
        with patch("im.management.commands.im_setup_system_account.ensure_account",
                   return_value=False):
            with self.assertRaises(CommandError):
                call_command("im_setup_system_account")


class ImSyncNicknamesCommandTests(TestCase):
    """``im_sync_nicknames`` 命令:同步全部非空昵称,并汇总失败数。"""

    def test_syncs_all_nicknamed_profiles(self):
        """昵称非空的资料逐个同步到 IM,入参是 IM 账号与昵称。

        参数说明:
            无。
        """
        user = User.objects.create_user(phone="13800138000")
        Profile.objects.update_or_create(user=user, defaults={"nickname": "小明"})
        with patch("im.management.commands.im_sync_nicknames.set_profile_nick",
                   return_value=True) as sync:
            call_command("im_sync_nicknames")
        sync.assert_any_call(user.im_user_id, "小明")

    def test_skips_users_without_nickname(self):
        """空昵称不参与同步,避免把 IM 昵称刷成空串。

        参数说明:
            无。
        """
        user = User.objects.create_user(phone="13800138001")
        Profile.objects.update_or_create(user=user, defaults={"nickname": ""})
        with patch("im.management.commands.im_sync_nicknames.set_profile_nick",
                   return_value=True) as sync:
            call_command("im_sync_nicknames")
        sync.assert_not_called()

    def test_reports_failure_count(self):
        """失败条数要打进 stdout,运维据此判断是否需要重跑。

        参数说明:
            无。
        """
        user = User.objects.create_user(phone="13800138002")
        Profile.objects.update_or_create(user=user, defaults={"nickname": "小红"})
        out = io.StringIO()
        with patch("im.management.commands.im_sync_nicknames.set_profile_nick",
                   return_value=False):
            call_command("im_sync_nicknames", stdout=out)
        self.assertIn("失败 1", out.getvalue())


class ImSyncPairsCommandTests(TestCase):
    """``im_sync_pairs`` 命令:只回填有效配对,先幂等建号(H4 上线必跑)。"""

    def test_backfills_active_matches(self):
        """有效配对:两侧都 ensure,再写 im_pair。"""
        a = User.objects.create_user(phone="13800138010")
        b = User.objects.create_user(phone="13800138011")
        Match.objects.create(**Match.pair_kwargs(a, b))
        with patch("im.management.commands.im_sync_pairs.ensure_account",
                   return_value=True) as ensure, \
                patch("im.management.commands.im_sync_pairs.pair_add",
                      return_value=True) as pair:
            call_command("im_sync_pairs")
        pair.assert_called_once_with(a.im_user_id, b.im_user_id)
        self.assertEqual(ensure.call_count, 2)

    def test_skips_unmatched(self):
        """已解除的配对不回填。"""
        a = User.objects.create_user(phone="13800138012")
        b = User.objects.create_user(phone="13800138013")
        match = Match.objects.create(**Match.pair_kwargs(a, b))
        Match.objects.filter(pk=match.pk).update(unmatched_at=timezone.now())
        with patch("im.management.commands.im_sync_pairs.pair_add",
                   return_value=True) as pair:
            call_command("im_sync_pairs")
        pair.assert_not_called()


@override_settings(
    IM_SELF_WS_URL="wss://im.example/ws",
    IM_SELF_HTTP_URL="https://im.example/api",
    IM_SELF_SECRET="t" * 32,
    IM_SELF_TOKEN_TTL=86400,
)
class UserSigApiTests(APITestCase):
    """``POST /im/user_sig``:签发内容、重封禁 403、踢旧会话先于签发。"""

    def setUp(self):
        """清缓存并登录一个用户,作为签发凭证用例的公共前置。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``unittest`` 在每条用例前自动调用 ``setUp()``。

        备注信息:
            ``cache.clear()`` 必须清掉 ``im:imported`` 标记,否则第二次跑测试时
            ``ensure_account`` 不会被调用。
        """
        cache.clear()   # 清 im:imported 标记,否则第二次跑测试时 ensure_account 不会被调用
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(phone="13800138000")
        token = RefreshToken.for_user(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_returns_token_for_current_user(self):
        """返回自建凭证:backend=self、带 ws_url、token 里带会话版本。"""
        with patch("im.views.ensure_account", return_value=True) as ensure, \
                patch("im.views.set_session_version", return_value=True) as sync, \
                patch("im.views.kick_user") as kick:
            resp = self.client.post("/api/v1/im/user_sig")
        ensure.assert_called_with(self.user.im_user_id,
                                  getattr(getattr(self.user, "profile", None), "nickname", ""))
        sync.assert_called_once_with(self.user.im_user_id, self.user.session_version,
                                    client_type="app")
        kick.assert_not_called()   # 没有待踢标记时不踢(否则会把本机会话踢掉)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["backend"], "self")
        self.assertEqual(data["im_user_id"], f"u{self.user.id}")
        self.assertEqual(data["ws_url"], "wss://im.example/ws")
        self.assertEqual(data["expire"], 86400)
        self.assertNotIn("user_sig", data, "腾讯分支已删除,不再返回 user_sig")
        self.assertEqual(verify_im_token(data["token"])["sub"], f"u{self.user.id}")

    def test_fails_closed_when_session_sync_fails(self):
        """版本没落库就不签发 token,否则连接会被 imserver 拒绝(H3)。"""
        with patch("im.views.ensure_account", return_value=True), \
                patch("im.views.set_session_version", return_value=False):
            resp = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(resp.status_code, 503)
        self.assertNotIn("token", resp.json())

    def test_pending_kick_runs_before_issuing_sig(self):
        """有待踢标记时先踢旧会话再签发,踢完把标记清掉。

        参数说明:
            无。
        """
        cache.set(kick_pending_key(self.user.id, "app"), 1, 60)
        with patch("im.views.ensure_account", return_value=True), \
                patch("im.views.set_session_version", return_value=True), \
                patch("im.views.kick_user", return_value=True) as kick:
            resp = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(resp.status_code, 200)
        kick.assert_called_once_with(self.user.im_user_id, client_type="app")
        self.assertIsNone(cache.get(kick_pending_key(self.user.id, "app")))

    def test_requires_auth(self):
        """不带 JWT 访问返回 401。

        参数说明:
            无。
        """
        self.client.credentials()
        resp = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(resp.status_code, 401)

    def test_user_sig_throttled(self):
        """IM 凭证按用户限流,超限返回 429(M7)。"""
        from .throttles import UserSigThrottle

        cache.clear()
        with patch("im.views.ensure_account", return_value=True), \
                patch("im.views.set_session_version", return_value=True), \
                patch.object(UserSigThrottle, "rate", "2/hour", create=True):
            self.assertEqual(self.client.post("/api/v1/im/user_sig").status_code, 200)
            self.assertEqual(self.client.post("/api/v1/im/user_sig").status_code, 200)
            self.assertEqual(self.client.post("/api/v1/im/user_sig").status_code, 429)

    def test_heavy_banned_rejected(self):
        """重封禁用户拿不到 IM 凭证,返回 403 且业务码同为 403。

        参数说明:
            无。
        """
        Profile.objects.create(user=self.user, status=ProfileStatus.BANNED_HEAVY)
        resp = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], 403)


class ImTaskTests(TestCase):
    """IM 副作用任务:失败要抛异常(Celery 才会重试),查不到用户则静默跳过。"""

    def setUp(self):
        """清缓存并建一个任务用例共用的账号。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``unittest`` 在每条用例前自动调用 ``setUp()``。

        备注信息:
            ``kick_pending`` 的标记存在缓存里,不清会污染下一个用例。
        """
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(phone="13800138000")

    def test_import_account_task_calls_client(self):
        """建号任务按 id 查库后转调客户端,入参是 IM 账号。

        参数说明:
            无。
        """
        with patch("im.client.import_account", return_value=True) as imp:
            import_account_task.run(self.user.id)
        imp.assert_called_once_with(self.user.im_user_id)

    def test_import_failure_raises_so_celery_retries(self):
        """客户端返回 ``False`` 时转成 RuntimeError,靠异常触发 Celery 重试。

        参数说明:
            无。
        """
        with patch("im.client.import_account", return_value=False):
            with self.assertRaises(RuntimeError):
                import_account_task.run(self.user.id)

    def test_kick_pending_noop_without_flag(self):
        """没有待踢标记时不调用踢人接口。

        参数说明:
            无。
        """
        with patch("im.client.kick_user") as kick:
            kick_pending.run(self.user.id)
        kick.assert_not_called()

    def test_kick_pending_kicks_and_clears_flag(self):
        """按标记踢掉该端会话,成功后删除标记。

        参数说明:
            无。
        """
        cache.set(kick_pending_key(self.user.id, "app"), 1, 60)
        with patch("im.client.kick_user", return_value=True) as kick:
            kick_pending.run(self.user.id)
        kick.assert_called_once_with(self.user.im_user_id, client_type="app")
        self.assertIsNone(cache.get(kick_pending_key(self.user.id, "app")))

    def test_kick_device_kicks_only_given_client(self):
        """登录设备「下线该端」只踢这一端:``client_type`` 必须透传给 IM。"""
        with patch("im.client.kick_user", return_value=True) as kick:
            kick_device.run(self.user.id, "web")
        kick.assert_called_once_with(self.user.im_user_id, client_type="web")

    def test_kick_device_failure_raises_so_celery_retries(self):
        """IM 调用失败要抛异常交给重试,不能静默吞掉(用户会以为已经下线)。"""
        with patch("im.client.kick_user", return_value=False):
            with self.assertRaises(RuntimeError):
                kick_device.run(self.user.id, "app")

    def test_kick_pending_keeps_flag_and_raises_on_failure(self):
        """踢人失败要保留标记并抛异常,重试时还能再踢一次。

        参数说明:
            无。
        """
        cache.set(kick_pending_key(self.user.id, "app"), 1, 60)
        with patch("im.client.kick_user", return_value=False):
            with self.assertRaises(RuntimeError):
                kick_pending.run(self.user.id, "app")
        self.assertIsNotNone(cache.get(kick_pending_key(self.user.id, "app")))


class ImSideEffectTaskTests(TestCase):
    """第 2 期:配对灰条 / 封禁通知 / 黑名单 / 资料同步的任务体。"""

    def setUp(self):
        """建两个账号,其中 ``b`` 带昵称「小红」。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``unittest`` 在每条用例前自动调用 ``setUp()``。

        备注信息:
            资料同步相关用例依赖 ``b`` 的昵称与已过审照片。
        """
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.b, nickname="小红")

    def test_send_match_notice_task(self):
        """配对通知任务把两侧账号转成 IM 账号后交给客户端。

        参数说明:
            无。
        """
        with patch("im.client.send_match_notice", return_value=True) as send:
            send_match_notice_task.run(self.a.id, self.b.id)
        send.assert_called_once_with(self.a.im_user_id, self.b.im_user_id)

    def test_blacklist_add_and_remove(self):
        """拉黑与取消拉黑各自转调对应的客户端函数。

        参数说明:
            无。
        """
        with patch("im.client.black_list_add", return_value=True) as add:
            blacklist_add.run(self.a.id, self.b.id)
        add.assert_called_once_with(self.a.im_user_id, self.b.im_user_id)
        with patch("im.client.black_list_delete", return_value=True) as delete:
            blacklist_remove.run(self.a.id, self.b.id)
        delete.assert_called_once_with(self.a.im_user_id, self.b.im_user_id)

    def test_unmatch_blacklist_blocks_both_directions(self):
        """解除配对时双向拉黑,两侧各写一条且都成功。

        参数说明:
            无。
        """
        calls = []
        with patch("im.client.black_list_add",
                   side_effect=lambda *args: calls.append(args) or True):
            unmatch_blacklist.run(self.a.id, self.b.id)
        self.assertEqual(calls, [
            (self.a.im_user_id, self.b.im_user_id),
            (self.b.im_user_id, self.a.im_user_id),
        ])

    def test_unmatch_blacklist_failure_raises_so_celery_retries(self):
        """拉黑失败抛异常交给 Celery 重试。

        参数说明:
            无。
        """
        with patch("im.client.black_list_add", return_value=False):
            with self.assertRaises(RuntimeError):
                unmatch_blacklist.run(self.a.id, self.b.id)

    def test_unmatch_blacklist_missing_user_is_noop(self):
        """对端账号不存在时静默跳过,不调用拉黑。

        参数说明:
            无。
        """
        with patch("im.client.black_list_add") as add:
            unmatch_blacklist.run(self.a.id, 999999)
        add.assert_not_called()

    def test_ban_notice_light_only_sends(self):
        """轻封只发通知,不断开连接。

        参数说明:
            无。
        """
        with patch("im.client.send_ban_notice", return_value=True) as send, \
                patch("im.client.kick_user") as kick:
            ban_notice.run(self.b.id, "light", "骚扰他人")
        send.assert_called_once_with(self.b.im_user_id, "light", "骚扰他人")
        kick.assert_not_called()

    def test_ban_notice_heavy_sends_then_kicks(self):
        """重封先发通知再踢全部端,顺序不能反。

        参数说明:
            无。
        """
        calls = []
        with patch("im.client.send_ban_notice",
                   side_effect=lambda *a: calls.append("send") or True), \
                patch("im.client.kick_user",
                      side_effect=lambda *a, **k: calls.append("kick") or True):
            ban_notice.run(self.b.id, "heavy", "严重违规")
        self.assertEqual(calls, ["send", "kick"])   # 顺序不能反:先说明原因再断线

    def test_ban_notice_failure_raises_so_celery_retries(self):
        """通知发送失败抛异常交给 Celery 重试。

        参数说明:
            无。
        """
        with patch("im.client.send_ban_notice", return_value=False):
            with self.assertRaises(RuntimeError):
                ban_notice.run(self.b.id, "light", "骚扰他人")

    def test_ban_lifted_task(self):
        """解封任务以 IM 账号为唯一入参发解封通知。

        参数说明:
            无。
        """
        with patch("im.client.send_ban_lifted", return_value=True) as send:
            ban_lifted.run(self.b.id)
        send.assert_called_once_with(self.b.im_user_id)

    def test_sync_profile_nick(self):
        """``kind="nick"`` 只同步昵称,取库里的当前值。

        参数说明:
            无。
        """
        with patch("im.client.set_profile_nick", return_value=True) as sync:
            sync_profile.run(self.b.id, "nick")
        sync.assert_called_once_with(self.b.im_user_id, "小红")

    @override_settings(MEDIA_BASE_URL="http://cdn.test")
    def test_sync_profile_avatar_uses_absolute_url(self):
        """``kind="avatar"`` 把已过审照片拼成绝对地址再同步。

        参数说明:
            无。
        """
        Photo.objects.create(user=self.b, file="photos/a.png", status=PhotoStatus.APPROVED)
        with patch("im.client.set_profile_avatar", return_value=True) as sync:
            sync_profile.run(self.b.id, "avatar")
        sync.assert_called_once_with(self.b.im_user_id, "http://cdn.test/media/photos/a.png")

    def test_sync_profile_avatar_without_approved_photo_is_noop(self):
        """没有已过审照片时不同步头像。

        参数说明:
            无。
        """
        with patch("im.client.set_profile_avatar") as sync:
            sync_profile.run(self.b.id, "avatar")
        sync.assert_not_called()

    def test_report_handled_task(self):
        """举报处理完成通知发给被举报人。

        参数说明:
            无。
        """
        with patch("im.client.send_report_handled", return_value=True) as send:
            report_handled_task.run(self.a.id)
        send.assert_called_once_with(self.a.im_user_id)

    def test_report_handled_failure_raises_so_celery_retries(self):
        """通知失败抛异常交给 Celery 重试。

        参数说明:
            无。
        """
        with patch("im.client.send_report_handled", return_value=False):
            with self.assertRaises(RuntimeError):
                report_handled_task.run(self.a.id)

    def test_report_handled_missing_user_is_noop(self):
        """用户已不存在时静默返回,不抛异常也不发送。

        参数说明:
            无。
        """
        report_handled_task.run(999999)   # 不抛异常、不调用

    def test_missing_user_is_noop(self):
        """任一账号查不到都不抛异常(查不到就跳过)。

        参数说明:
            无。
        """
        send_match_notice_task.run(self.a.id, 999999)   # 不抛异常
        sync_profile.run(999999, "nick")


class ImDeleteAccountTaskTests(TestCase):
    """注销删号:先踢后删;踢失败不阻塞删号;删号失败抛异常让 Celery 重试。

    回归重点:任务**不查库** —— 调用时用户行已经删掉了,参数是 im_user_id。
    """

    def test_kicks_then_deletes(self):
        """先踢在线会话再删号,两条调用顺序不能反。

        参数说明:
            无。
        """
        calls = []
        with patch("im.client.kick_user",
                   side_effect=lambda *a: calls.append("kick") or True), \
                patch("im.client.delete_account",
                      side_effect=lambda *a: calls.append("delete") or True):
            delete_account_task.run("u9")
        self.assertEqual(calls, ["kick", "delete"])   # 顺序不能反:先断在线会话再删号

    def test_kick_failure_does_not_block_delete(self):
        """踢人失败不阻塞删号,删号仍被调用且不抛异常。

        参数说明:
            无。
        """
        with patch("im.client.kick_user", return_value=False), \
                patch("im.client.delete_account", return_value=True) as delete:
            delete_account_task.run("u9")   # 不抛异常
        delete.assert_called_once_with("u9")

    def test_delete_failure_raises_so_celery_retries(self):
        """删号失败抛异常让 Celery 重试。

        参数说明:
            无。
        """
        with patch("im.client.kick_user", return_value=True), \
                patch("im.client.delete_account", return_value=False):
            with self.assertRaises(RuntimeError):
                delete_account_task.run("u9")

    def test_does_not_touch_database(self):
        """任务不查库:用户行已删,只按 ``im_user_id`` 直接转调客户端。

        参数说明:
            无。
        """
        with patch("im.client.kick_user", return_value=True), \
                patch("im.client.delete_account", return_value=True), \
                patch("im.tasks._user") as user_lookup:
            delete_account_task.run("u9")
        user_lookup.assert_not_called()


class ImTokenTests(SimpleTestCase):
    """自建 IM token 的签发与校验。"""

    @override_settings(IM_SELF_SECRET="t" * 32)
    def test_mint_and_verify(self):
        """签发后可验签,claims 带 ``uid``/``sub``/``sv``,端类型缺省为 ``app``。

        参数说明:
            无。
        """
        token = mint_im_token(9, 3600, session_version=7)
        claims = verify_im_token(token)
        self.assertIsNotNone(claims)
        self.assertEqual(claims["uid"], 9)
        self.assertEqual(claims["sub"], "u9")
        self.assertEqual(claims["sv"], 7)
        self.assertEqual(claims["ct"], "app")   # 缺省端类型;多端在线按 (uid, ct) 查会话

    @override_settings(IM_SELF_SECRET="t" * 32)
    def test_mint_carries_client_type(self):
        """指定端类型签发时 ``ct`` 与会话版本原样写入 claims。

        参数说明:
            无。
        """
        claims = verify_im_token(mint_im_token(9, 3600, 4, "web"))
        self.assertEqual(claims["ct"], "web")
        self.assertEqual(claims["sv"], 4)

    @override_settings(IM_SELF_SECRET="t" * 32)
    def test_reject_tampered(self):
        """改动 payload 段后验签失败,返回 ``None``。

        参数说明:
            无。
        """
        token = mint_im_token(9, 3600)
        # 改 payload 段,而不是签名段的最后一个字符:32 字节签名 base64url 后是 43 字符,
        # 末字符只有 2 位有效 + 4 位填充,改它的低位可能解出完全相同的字节,
        # 验签会「通过」——这是本用例此前偶发变红的原因。
        header, payload, signature = token.split(".")
        tampered = ".".join([header, payload[:-1] + ("A" if payload[-1] != "A" else "B"),
                             signature])
        self.assertIsNone(verify_im_token(tampered))


class SelfNoticeTests(SimpleTestCase):
    """自建后端下的封禁/解封通知。"""

    @patch("im.client.self_client.send_custom_elem", return_value=True)
    @patch("im.client.self_client.kick_user", return_value=True)
    def test_heavy_ban_blocks_and_notifies(self, kick, send):
        """重封先发通知再踢全部端(``kick_user`` 第三参为 ``None`` 即踢全部)。

        参数说明:
            无。
        """
        with patch("im.tasks._user") as user:
            user.return_value.im_user_id = "u9"
            ban_notice.run(9, "heavy", "违规")
        send.assert_called_once()
        kick.assert_called_once_with("u9", True, None)   # None = 踢全部端(封禁语义)

    @patch("im.client.self_client.send_ban_lifted", return_value=True)
    def test_ban_lifted_unblocks(self, lifted):
        """解封只发解封通知,不踢人。

        参数说明:
            无。
        """
        with patch("im.tasks._user") as user:
            user.return_value.im_user_id = "u9"
            ban_lifted.run(9)
        lifted.assert_called_once_with("u9")

class ChatImageModelTests(TestCase):
    """聊天图片元数据:默认状态、可读表示、随用户级联删除。"""

    def setUp(self):
        """把 ``MEDIA_ROOT`` 指向临时目录,并建一个上传者账号。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``unittest`` 在每条用例前自动调用 ``setUp()``。

        备注信息:
            临时目录随用例结束删除,不污染仓库内的 media/。
        """
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(phone="13900139001")

    def test_defaults_to_visible_and_str_is_readable(self):
        """新建记录默认可见,``str()`` 里带 ``chat_image#`` 前缀。

        参数说明:
            无。
        """
        image = ChatImage.objects.create(
            owner=self.user,
            file=SimpleUploadedFile("a.jpg", PNG_1PX, content_type="image/jpeg"),
            thumb=SimpleUploadedFile("a_thumb.jpg", PNG_1PX, content_type="image/jpeg"),
            width=10, height=20, bytes=len(PNG_1PX))
        self.assertEqual(image.status, ChatImageStatus.VISIBLE)
        self.assertIn("chat_image#", str(image))

    def test_cascade_deletes_rows_with_user(self):
        """账号被删时图片记录随外键级联删除。

        参数说明:
            无。
        """
        ChatImage.objects.create(
            owner=self.user,
            file=SimpleUploadedFile("a.jpg", PNG_1PX, content_type="image/jpeg"),
            thumb=SimpleUploadedFile("a_thumb.jpg", PNG_1PX, content_type="image/jpeg"),
            width=10, height=20, bytes=len(PNG_1PX))
        self.user.delete()
        self.assertEqual(ChatImage.objects.count(), 0)

    def test_signed_urls_are_absolute_and_signed(self):
        """``signed_file_url`` 是绝对地址,且带 ``e=`` 与 ``s=`` 签名参数。

        参数说明:
            无。
        """
        with override_settings(IM_MEDIA_SIGN_SECRET="s", MEDIA_BASE_URL="http://cdn.test"):
            image = ChatImage.objects.create(
                owner=self.user,
                file=SimpleUploadedFile("a.jpg", PNG_1PX, content_type="image/jpeg"),
                thumb=SimpleUploadedFile("a_thumb.jpg", PNG_1PX, content_type="image/jpeg"),
                width=10, height=20, bytes=len(PNG_1PX))
            self.assertTrue(image.signed_file_url.startswith("http://cdn.test/media/chat/"))
            self.assertIn("?e=", image.signed_file_url)
            self.assertIn("&s=", image.signed_thumb_url)

    def test_expired_status_and_timestamp_exist(self):
        """状态可直接落 EXPIRED,此时 ``expired_at`` 允许为空。

        参数说明:
            无。
        """
        image = ChatImage.objects.create(
            owner=self.user,
            file=SimpleUploadedFile("b.jpg", PNG_1PX, content_type="image/jpeg"),
            thumb=SimpleUploadedFile("b_thumb.jpg", PNG_1PX, content_type="image/jpeg"),
            width=1, height=1, bytes=len(PNG_1PX),
            status=ChatImageStatus.EXPIRED)
        self.assertIsNone(image.expired_at)

def _jpeg_with_orientation(size=(40, 20), orientation=6):
    """生成一张带 EXIF 方向标签的 JPEG(6 = 顺时针 90°,显示时宽高互换)。

    参数说明:
        size: 原始像素尺寸(宽, 高),默认 ``(40, 20)``。
        orientation: EXIF Orientation 值,默认 6。

    返回参数:
        JPEG 字节内容。

    使用示例:
        ``content = _jpeg_with_orientation((40, 20), 6)``

    备注信息:
        纯内存生成,不落盘;用于断言上传后按显示方向纠正宽高并重编码。
    """
    buffer = io.BytesIO()
    image = Image.new("RGB", size, (200, 30, 30))
    exif = image.getexif()
    exif[0x0112] = orientation
    image.save(buffer, "JPEG", exif=exif)
    return buffer.getvalue()


class ChatImageUploadTests(APITestCase):
    """聊天图片上传:成功返回四元组、大小/格式/尺寸校验、限流、重封禁拦截。"""

    def setUp(self):
        """把 ``MEDIA_ROOT`` 指向临时目录、清限流计数并登录一个上传者。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``unittest`` 在每条用例前自动调用 ``setUp()``。

        备注信息:
            cache 必须清:限流计数按用户缓存在 Redis,不清会跨用例累加。
        """
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir, MEDIA_BASE_URL="http://cdn.test",
                                 IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=86400)
        override.enable()
        self.addCleanup(override.disable)
        cache.clear()   # 限流计数按用户缓存在 Redis,用例间必须清
        self.user = User.objects.create_user(phone="13900139002")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")
        self.url = "/api/v1/im/images"

    def upload(self, name="a.png", content=PNG_1PX, content_type="image/png"):
        """上传一张图片。

        参数说明:
            name: 文件名,默认 ``a.png``。
            content: 文件字节内容,默认 1×1 透明 PNG。
            content_type: MIME 类型,默认 ``image/png``。

        返回参数:
            DRF 测试客户端的响应对象。

        使用示例:
            ``response = self.upload(name="a.gif", content_type="image/gif")``

        备注信息:
            走 ``multipart`` 表单提交,字段名固定为 ``file``。
        """
        return self.client.post(
            self.url, {"file": SimpleUploadedFile(name, content, content_type=content_type)},
            format="multipart")

    def test_upload_returns_urls_and_dimensions(self):
        """上传成功返回 201,给出原图/缩略图签名 URL 与真实宽高。

        参数说明:
            无。
        """
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.data)
        data = response.data
        self.assertTrue(data["url"].startswith("http://cdn.test/media/chat/"))
        self.assertIn("?e=", data["url"])
        self.assertIn("&s=", data["url"])
        self.assertTrue(urlsplit(data["thumb_url"]).path.endswith("_thumb.jpg"))
        self.assertIn("&s=", data["thumb_url"])
        self.assertEqual((data["width"], data["height"]), (1, 1))
        self.assertGreater(data["size"], 0)   # 重编码后的字节数,不再等于原始 PNG
        image = ChatImage.objects.get()
        self.assertEqual(image.owner_id, self.user.id)
        self.assertRegex(image.file.name, r"^chat/\d{4}/\d{2}/\d+-[0-9a-f]{32}\.png$")
        self.assertTrue(image.file.storage.exists(image.file.name))
        self.assertTrue(image.thumb.storage.exists(image.thumb.name))

    def test_uploaded_url_verifies_with_auth_helper(self):
        """返回的 URL 能被 ``media_sign.verify`` 验过(与 nginx 子请求同一套算法)。

        参数说明:
            无。
        """
        data = self.upload().data
        parts = urlsplit(data["url"])
        query = parse_qs(parts.query)
        self.assertTrue(media_sign.verify(parts.path, query["e"][0], query["s"][0]))

    def test_rejects_non_image(self):
        """非图片内容返回 400。

        参数说明:
            无。
        """
        response = self.upload(name="a.txt", content=b"not an image", content_type="text/plain")
        self.assertEqual(response.status_code, 400)

    def test_rejects_oversized_file(self):
        """超过 ``CHAT_IMAGE_MAX_BYTES`` 返回 400,文案里带 5MB 上限。

        参数说明:
            无。
        """
        with override_settings(CHAT_IMAGE_MAX_BYTES=10):
            response = self.upload()
        self.assertEqual(response.status_code, 400)
        self.assertIn("5MB", str(response.data))

    def test_rejects_too_large_side(self):
        """长边超过 ``CHAT_IMAGE_MAX_SIDE`` 返回 400。

        参数说明:
            无。
        """
        with override_settings(CHAT_IMAGE_MAX_SIDE=0):
            response = self.upload()
        self.assertEqual(response.status_code, 400)

    def test_rejects_format_outside_whitelist(self):
        """GIF 不在 jpg/png/webp 白名单内(L5)。"""
        buffer = io.BytesIO()
        Image.new("RGB", (1, 1), "red").save(buffer, "GIF")
        response = self.upload(name="a.gif", content=buffer.getvalue(),
                               content_type="image/gif")
        self.assertEqual(response.status_code, 400)

    def test_rejects_decompression_bomb(self):
        """像素总数超限时在解码前拒绝(M3)。"""
        buffer = io.BytesIO()
        Image.new("RGB", (20, 20), "red").save(buffer, "PNG")
        with patch("config.images.MAX_IMAGE_PIXELS", 100):
            response = self.upload(content=buffer.getvalue())
        self.assertEqual(response.status_code, 400)

    def test_upload_strips_exif(self):
        """落盘的是重编码图,原始 EXIF 不再存在(M4)。"""
        exif = Image.Exif()
        exif[0x010F] = "TestCamera"
        buffer = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(buffer, "JPEG", exif=exif)
        response = self.upload(name="a.jpg", content=buffer.getvalue(),
                               content_type="image/jpeg")
        self.assertEqual(response.status_code, 201, response.data)
        image = ChatImage.objects.get()
        with Image.open(image.file.path) as stored:
            self.assertNotIn(0x010F, stored.getexif())

    def test_throttled_after_rate(self):
        """超过 ``chat_image`` 频率后返回 429。

        参数说明:
            无。
        """
        # DRF 的 THROTTLE_RATES 是类属性,在 import 时就绑定了;测试只能替换这个属性
        with patch.object(ChatImageThrottle, "THROTTLE_RATES", {"chat_image": "2/hour"}):
            self.assertEqual(self.upload().status_code, 201)
            self.assertEqual(self.upload().status_code, 201)
            self.assertEqual(self.upload().status_code, 429)

    def test_heavy_banned_user_is_forbidden(self):
        """重封禁用户上传返回 403。

        参数说明:
            无。
        """
        profile = get_profile(self.user)          # 资料行是懒创建的,不能直接 user.profile
        profile.status = ProfileStatus.BANNED_HEAVY
        profile.save(update_fields=["status"])
        self.assertEqual(self.upload().status_code, 403)

    def test_exif_orientation_swaps_dimensions_and_reencodes(self):
        """带 EXIF 方向 6 的图按显示方向纠正,宽高互换。

        参数说明:
            无。
        """
        content = _jpeg_with_orientation()
        response = self.upload(name="rotated.jpg", content=content, content_type="image/jpeg")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data["width"], response.data["height"]), (20, 40))
        self.assertTrue(urlsplit(response.data["url"]).path.endswith(".jpg"))

    def test_quota_exceeded_rejects_upload(self):
        """配额不足时 413/41301,不建行,且**磁盘上不留任何文件**(M-1)。"""
        with self.settings(USER_STORAGE_QUOTA_BYTES=1):
            response = self.upload()
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.data["code"], 41301)
        self.assertEqual(ChatImage.objects.count(), 0)
        # 配额校验必须先于落盘:超限后 media/chat 下不能出现孤儿原图/缩略图
        self.assertEqual([p for p in Path(self.media_dir).rglob("*") if p.is_file()], [])


class MediaSignTests(SimpleTestCase):
    """聊天图片签名:共享向量、过期、篡改、路径白名单、未配置密钥时的放行。"""

    def test_shared_vector_matches_imserver(self):
        """与 imserver 共用的签名向量逐字节一致,算法改动会两侧同时变红。

        参数说明:
            无。
        """
        self.assertEqual(
            media_sign.signature("/media/chat/2026/10/12-abc.jpg", 1761782400,
                                 secret="test-media-secret"),
            "2b46b854b31a88877e318e3d12cb743fe76fccb2977e2d7ced879d7b3547d419")

    def test_expiry_is_bucket_aligned(self):
        """过期时刻对齐到整点桶再加 TTL,同一小时内的 URL 过期时间相同。

        参数说明:
            无。
        """
        # 1761779999 落在 1761778800 这个整点桶里,加 24h
        with override_settings(IM_MEDIA_SIGN_TTL=86400):
            self.assertEqual(media_sign.expires_at(1761779999), 1761865200)

    def test_sign_url_replaces_existing_query(self):
        """``sign_url`` 覆盖已有的 ``e``/``s``,不把旧签名叠在后面。

        参数说明:
            无。
        """
        with override_settings(IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=86400):
            signed = media_sign.sign_url("http://cdn.test/media/chat/a.jpg?e=1&s=old",
                                         now=1761782400)
        self.assertTrue(signed.startswith("http://cdn.test/media/chat/a.jpg?e="))
        self.assertNotIn("s=old", signed)

    def test_verify_accepts_valid_and_rejects_tampered(self):
        """同路径同签名放行,换路径或换签名都拒绝。

        参数说明:
            无。
        """
        with override_settings(IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=86400):
            signed = media_sign.sign_url("/media/chat/a.jpg", now=1761782400)
            query = parse_qs(urlsplit(signed).query)
            self.assertTrue(media_sign.verify("/media/chat/a.jpg", query["e"][0],
                                              query["s"][0], now=1761782400))
            self.assertFalse(media_sign.verify("/media/chat/b.jpg", query["e"][0],
                                               query["s"][0], now=1761782400))
            self.assertFalse(media_sign.verify("/media/chat/a.jpg", query["e"][0],
                                               "0" * 64, now=1761782400))

    def test_verify_rejects_expired_and_foreign_path(self):
        """过期签名与 ``/media/photos/`` 等非聊天路径都拒绝。

        参数说明:
            无。
        """
        with override_settings(IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=60):
            signed = media_sign.sign_url("/media/chat/a.jpg", now=1761782400)
            query = parse_qs(urlsplit(signed).query)
            self.assertFalse(media_sign.verify("/media/chat/a.jpg", query["e"][0],
                                               query["s"][0], now=1761868800))
            self.assertFalse(media_sign.verify("/media/photos/a.jpg", query["e"][0],
                                               query["s"][0], now=1761782400))

    @override_settings(DEBUG=True)
    def test_disabled_secret_passes_everything(self):
        """仅开发模式(DEBUG=1)允许空密钥放行。"""
        with override_settings(IM_MEDIA_SIGN_SECRET=""):
            self.assertEqual(media_sign.sign_url("/media/chat/a.jpg"), "/media/chat/a.jpg")
            self.assertTrue(media_sign.verify("/media/chat/a.jpg", "0", "bad"))

    @override_settings(DEBUG=False)
    def test_missing_secret_fails_closed_in_production(self):
        """生产漏配密钥时必须拒绝,而不是放行(M6)。"""
        with override_settings(IM_MEDIA_SIGN_SECRET=""):
            self.assertFalse(media_sign.verify("/media/chat/a.jpg", "0", "bad"))


@override_settings(IM_MEDIA_SIGN_SECRET="s")
class ChatImageAuthTests(APITestCase):
    """nginx 子请求验签:有效 204、缺头/过期/篡改 403、无需 JWT。"""

    def setUp(self):
        """固定验签接口地址与被签名的媒体路径。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``unittest`` 在每条用例前自动调用 ``setUp()``。

        备注信息:
            用例直接用 ``self.client``,不需要登录态。
        """
        self.url = "/api/v1/im/images/auth"
        self.media = "/media/chat/2026/10/12-abc.jpg"

    def auth(self, original):
        """带 ``X-Original-URI`` 调验签接口。

        参数说明:
            original: nginx 传入的原始 URI,含 ``?e=&s=`` 查询串。

        返回参数:
            DRF 响应对象。

        使用示例:
            ``self.auth("/media/chat/a.jpg?e=1&s=x")``

        备注信息:
            不带 JWT:验签接口只认签名,登录态由 ``is_authenticated=False`` 兜住。
        """
        return self.client.get(self.url, HTTP_X_ORIGINAL_URI=original)

    def signed(self):
        """生成一个当前有效的签名 URL。

        参数说明:
            无。

        返回参数:
            带 ``?e=&s=`` 的路径。

        使用示例:
            ``url = self.signed()``

        备注信息:
            用当前时间做签名,过期类用例要自己另造旧签名,不能用本方法。
        """
        with override_settings(IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=86400):
            return media_sign.sign_url(self.media, now=int(time.time()))

    def test_valid_signature_passes_without_jwt(self):
        """凭有效签名直接返回 204,不需要 JWT。

        参数说明:
            无。
        """
        self.assertEqual(self.auth(self.signed()).status_code, 204)

    def test_missing_header_is_forbidden(self):
        """缺 ``X-Original-URI`` 头返回 403,业务码同为 403。

        参数说明:
            无。
        """
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], 403)

    def test_expired_signature_is_forbidden(self):
        """过期签名返回 403。

        参数说明:
            无。
        """
        with override_settings(IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=60):
            stale = media_sign.sign_url(self.media, now=1)
            self.assertEqual(self.auth(stale).status_code, 403)

    def test_non_chat_path_is_forbidden(self):
        """非 ``/media/chat/`` 路径即使签名有效也返回 403。

        参数说明:
            无。
        """
        with override_settings(IM_MEDIA_SIGN_SECRET="s"):
            signed = media_sign.sign_url("/media/photos/a.jpg", now=int(time.time()))
        self.assertEqual(self.auth(signed).status_code, 403)

    def test_non_chat_path_rejected_even_if_verify_passes(self):
        """L-6:路径前缀由视图显式校验,不再依赖 ``media_sign.verify`` 内部兜底。"""
        with patch("im.views.media_sign.verify", return_value=True):
            response = self.auth("/media/photos/a.jpg?e=9999999999&s=x")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], 403)

    def test_heavy_banned_user_can_still_view(self):
        """重封禁用户仍可查看已签名聊天图,不能因封禁挡住历史消息。

        参数说明:
            无。
        """
        user = User.objects.create_user(phone="13900139009")
        profile = get_profile(user)
        profile.status = ProfileStatus.BANNED_HEAVY
        profile.save(update_fields=["status"])
        self.assertEqual(self.auth(self.signed()).status_code, 204)


class ChatImageCleanupTests(TestCase):
    """清理命令:保留期删文件并改状态、默认 dry-run、孤儿文件按 mtime、删除残留补删。"""

    def setUp(self):
        """把 ``MEDIA_ROOT`` 指向临时目录、固定 30 天保留期并建一个所有者账号。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``unittest`` 在每条用例前自动调用 ``setUp()``。

        备注信息:
            保留期读 ``CHAT_IMAGE_RETENTION_DAYS``,单个用例可再覆盖。
        """
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir, CHAT_IMAGE_RETENTION_DAYS=30)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(phone="13900139003")

    def make_image(self, name="a.jpg", days_old=0, status=ChatImageStatus.VISIBLE):
        """造一张聊天图片并把 ``created_at`` 往前挪。

        参数说明:
            name: 原图文件名,默认 ``a.jpg``;缩略图名自动派生。
            days_old: 创建时间往前挪几天,默认 0。
            status: 初始状态,默认 ``VISIBLE``。

        返回参数:
            刷新后的 ``ChatImage`` 实例。

        使用示例:
            ``image = self.make_image(days_old=31)``

        备注信息:
            ``created_at`` 是 auto_now_add,只能建完再用 ``UPDATE`` 改,所以末尾要回读。
        """
        image = ChatImage.objects.create(
            owner=self.user,
            file=SimpleUploadedFile(name, PNG_1PX, content_type="image/jpeg"),
            thumb=SimpleUploadedFile(name.replace(".jpg", "_thumb.jpg"), PNG_1PX,
                                     content_type="image/jpeg"),
            width=1, height=1, bytes=len(PNG_1PX), status=status)
        ChatImage.objects.filter(pk=image.pk).update(
            created_at=timezone.now() - timedelta(days=days_old))
        image.refresh_from_db()
        return image

    def run_cleanup(self, *args):
        """跑一次清理命令并返回标准输出。

        参数说明:
            *args: 透传给 ``im_media_cleanup`` 的参数,如 ``"--apply"``。

        返回参数:
            命令的标准输出文本。

        使用示例:
            ``out = self.run_cleanup("--apply", "--retention-days", "0")``

        备注信息:
            不带 ``--apply`` 就是 dry-run;stdout 被截到内存,便于断言提示文案。
        """
        out = StringIO()
        call_command("im_media_cleanup", *args, stdout=out)
        return out.getvalue()

    def test_retention_removes_files_and_marks_expired(self):
        """超保留期的图删磁盘文件,状态改 EXPIRED 并写 ``expired_at``。

        参数说明:
            无。
        """
        image = self.make_image(days_old=31)
        names = (image.file.name, image.thumb.name)
        self.run_cleanup("--apply")
        image.refresh_from_db()
        self.assertEqual(image.status, ChatImageStatus.EXPIRED)
        self.assertIsNotNone(image.expired_at)
        for name in names:
            self.assertFalse(default_storage.exists(name))

    def test_dry_run_keeps_files(self):
        """不带 ``--apply`` 是 dry-run:文件与状态都不动,输出里标明 dry-run。

        参数说明:
            无。
        """
        image = self.make_image(days_old=31)
        output = self.run_cleanup()
        image.refresh_from_db()
        self.assertEqual(image.status, ChatImageStatus.VISIBLE)
        self.assertTrue(default_storage.exists(image.file.name))
        self.assertIn("dry-run", output)

    def test_fresh_image_is_kept(self):
        """未到保留期的图保持 VISIBLE,文件不动。

        参数说明:
            无。
        """
        image = self.make_image(days_old=1)
        self.run_cleanup("--apply")
        image.refresh_from_db()
        self.assertEqual(image.status, ChatImageStatus.VISIBLE)

    def test_orphan_file_is_deleted_after_grace(self):
        """库里无记录、mtime 超宽限期的孤儿文件被删除。

        参数说明:
            无。
        """
        orphan_dir = Path(self.media_dir) / "chat" / "2026" / "10"
        orphan_dir.mkdir(parents=True)
        orphan = orphan_dir / "999-dead.jpg"
        orphan.write_bytes(PNG_1PX)
        old = time.time() - 48 * 3600
        os.utime(orphan, (old, old))
        self.run_cleanup("--apply")
        self.assertFalse(orphan.exists())

    def test_recent_orphan_is_kept(self):
        """刚写入的孤儿文件在宽限期内保留,避免误删正在上传的文件。

        参数说明:
            无。
        """
        orphan_dir = Path(self.media_dir) / "chat" / "2026" / "10"
        orphan_dir.mkdir(parents=True)
        orphan = orphan_dir / "999-live.jpg"
        orphan.write_bytes(PNG_1PX)
        self.run_cleanup("--apply")
        self.assertTrue(orphan.exists())

    def test_deleted_row_leftover_file_is_removed(self):
        """状态为 DELETED 但文件残留的记录,文件被补删。

        参数说明:
            无。
        """
        image = self.make_image(status=ChatImageStatus.DELETED)
        self.run_cleanup("--apply")
        self.assertFalse(default_storage.exists(image.file.name))

    def test_zero_retention_skips_retention_pass(self):
        """``--retention-days 0`` 跳过保留期清理,老图不动。

        参数说明:
            无。
        """
        image = self.make_image(days_old=365)
        self.run_cleanup("--apply", "--retention-days", "0")
        image.refresh_from_db()
        self.assertEqual(image.status, ChatImageStatus.VISIBLE)


class ChatImageStatsTests(TestCase):
    """用量报表:打印各状态条数、字节数与磁盘文件数。"""

    def test_reports_status_counts_and_disk(self):
        """报表输出各状态条数与磁盘文件数(一张图 = 原图 + 缩略图 = 2 个文件)。

        参数说明:
            无。
        """
        media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_dir, ignore_errors=True)
        with self.settings(MEDIA_ROOT=media_dir):
            user = User.objects.create_user(phone="13900139004")
            ChatImage.objects.create(
                owner=user,
                file=SimpleUploadedFile("s.jpg", PNG_1PX, content_type="image/jpeg"),
                thumb=SimpleUploadedFile("s_thumb.jpg", PNG_1PX, content_type="image/jpeg"),
                width=1, height=1, bytes=len(PNG_1PX))
            out = StringIO()
            call_command("im_media_stats", stdout=out)
        text = out.getvalue()
        self.assertIn("visible=1", text)
        self.assertIn("磁盘文件=2", text)


class ChatVoiceUploadTests(APITestCase):
    """语音上传:成功返回四元组、时长/大小/格式校验、ffmpeg 缺失 503、限流。"""

    def setUp(self):
        """把 ``MEDIA_ROOT`` 指向临时目录、清限流计数并登录一个上传者。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``unittest`` 在每条用例前自动调用 ``setUp()``。

        备注信息:
            cache 必须清:语音限流计数按用户存在 Redis 里,不清会跨用例累加。
        """
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir, MEDIA_BASE_URL="http://cdn.test",
                                 IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=86400)
        override.enable()
        self.addCleanup(override.disable)
        cache.clear()
        self.user = User.objects.create_user(phone="13900139009")
        self.client.credentials(
            HTTP_AUTHORIZATION=f"Bearer {RefreshToken.for_user(self.user).access_token}")
        self.url = "/api/v1/im/voices"

    def upload(self, content=b"fake-m4a", content_type="audio/mp4", duration_ms=12500):
        """上传一段语音。

        参数说明:
            content: 文件字节,默认伪造的 m4a 内容。
            content_type: MIME 类型,默认 ``audio/mp4``。
            duration_ms: 客户端声明的时长,默认 12500 毫秒。

        返回参数:
            DRF 测试客户端响应。

        使用示例:
            ``response = self.upload(duration_ms=61000)``

        备注信息:
            文件名固定 ``a.m4a``;探测与转码由各用例用 ``patch`` 顶掉,不真跑 ffmpeg。
        """
        return self.client.post(
            self.url,
            {"file": SimpleUploadedFile("a.m4a", content, content_type=content_type),
             "duration_ms": duration_ms},
            format="multipart")

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"transcoded"))
    @patch("im.voice._probe_ms", return_value=12500)
    def test_upload_returns_signed_url(self, _probe, _transcode, _ffmpeg):
        """上传成功返回 201,给出签名播放 URL、时长与转码后字节数。

        参数说明:
            无。
        """
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.data)
        data = response.data
        self.assertTrue(data["url"].startswith("http://cdn.test/media/chat/voices/"))
        self.assertIn("?e=", data["url"])
        self.assertEqual(data["duration_ms"], 12500)
        self.assertEqual(data["size"], len(b"transcoded"))
        voice = ChatVoice.objects.get()
        self.assertEqual(voice.owner_id, self.user.id)
        self.assertRegex(voice.file.name, r"^chat/voices/\d{4}/\d{2}/\d+-[0-9a-f]{32}\.m4a$")
        self.assertTrue(voice.file.storage.exists(voice.file.name))

    @patch("im.voice.ffmpeg_available", return_value=False)
    def test_returns_503_without_ffmpeg(self, _ffmpeg):
        """服务器没装 ffmpeg 时返回 503 + 业务码 50302。

        参数说明:
            无。
        """
        response = self.upload()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.data["code"], 50302)

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"transcoded"))
    @patch("im.voice._probe_ms", return_value=12500)
    def test_quota_exceeded_rejects_upload(self, _probe, _transcode, _ffmpeg):
        """配额不足时 413/41301,且不建行(M7)。"""
        with self.settings(USER_STORAGE_QUOTA_BYTES=1):
            response = self.upload()
        self.assertEqual(response.status_code, 413)
        self.assertEqual(response.data["code"], 41301)
        self.assertEqual(ChatVoice.objects.count(), 0)

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._probe_ms", return_value=61000)
    def test_rejects_too_long(self, _probe, _ffmpeg):
        """超过语音时长上限返回 400。

        参数说明:
            无。
        """
        response = self.upload(duration_ms=61000)
        self.assertEqual(response.status_code, 400)

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._probe_ms", return_value=5000)
    def test_rejects_declared_duration_mismatch(self, _probe, _ffmpeg):
        """客户端声明时长与探测结果相差过大时返回 400。

        参数说明:
            无。
        """
        response = self.upload(duration_ms=20000)
        self.assertEqual(response.status_code, 400)

    def test_rejects_non_audio_content_type(self):
        """非音频 MIME 返回 400。

        参数说明:
            无。
        """
        response = self.upload(content_type="image/png")
        self.assertEqual(response.status_code, 400)

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"x"))
    @patch("im.voice._probe_ms", return_value=5000)
    def test_accepts_codecs_parameter(self, _probe, _transcode, _ffmpeg):
        """``audio/webm;codecs=opus`` 带参数也要收,不能按整串比对白名单。

        参数说明:
            无。
        """
        # 浏览器 Blob.type 会带 ;codecs=opus,不能因此拒收
        response = self.upload(content_type="audio/webm;codecs=opus", duration_ms=5000)
        self.assertEqual(response.status_code, 201, response.data)

    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"x"))
    @patch("im.voice._probe_ms", return_value=5000)
    def test_signed_url_passes_auth_helper(self, _probe, _transcode, _ffmpeg):
        """返回的播放 URL 能被 ``media_sign.verify`` 验过,nginx 可直接放行。

        参数说明:
            无。
        """
        data = self.upload(duration_ms=5000).data
        parts = urlsplit(data["url"])
        query = parse_qs(parts.query)
        self.assertTrue(media_sign.verify(parts.path, query["e"][0], query["s"][0]))

    @patch("im.throttles.ChatVoiceThrottle.get_rate", return_value="1/hour")
    @patch("im.voice.ffmpeg_available", return_value=True)
    @patch("im.voice._transcode", side_effect=lambda src, dst: dst.write_bytes(b"x"))
    @patch("im.voice._probe_ms", return_value=5000)
    def test_second_upload_is_throttled(self, _rate, _probe, _transcode, _ffmpeg):
        """频率压到 1/hour 后第二次上传返回 429。

        参数说明:
            无。
        """
        cache.clear()
        self.assertEqual(self.upload(duration_ms=5000).status_code, 201)
        self.assertEqual(self.upload(duration_ms=5000).status_code, 429)


class VoiceCommandHardeningTests(SimpleTestCase):
    """M5:ffmpeg/ffprobe 以最小权限运行(协议白名单、无交互、资源上限、最小环境)。"""

    def test_probe_uses_protocol_whitelist(self):
        """ffprobe 只允许 file/pipe 协议,无交互、带超时,posix 下再加资源限制。

        参数说明:
            无。
        """
        with patch("im.voice.subprocess.run") as run:
            run.return_value = SimpleNamespace(stdout="5.0\n", returncode=0)
            duration = voice._probe_ms(Path("a.m4a"))
        self.assertEqual(duration, 5000)
        args = run.call_args.args[0]
        self.assertEqual(args[0], "ffprobe")
        self.assertEqual(args[args.index("-protocol_whitelist") + 1], "file,pipe")
        kwargs = run.call_args.kwargs
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        self.assertFalse(kwargs.get("shell", False))
        self.assertEqual(kwargs["timeout"], voice.PROCESS_TIMEOUT_SECONDS)
        self.assertEqual(kwargs["env"]["LC_ALL"], "C")
        if os.name == "posix":
            self.assertIs(kwargs["preexec_fn"], voice._apply_limits)
        else:
            self.assertIsNone(kwargs["preexec_fn"])

    def test_transcode_args_are_hardened(self):
        """ffmpeg 参数硬化:``-nostdin``、丢元数据与字幕/数据流、单线程。

        参数说明:
            无。
        """
        with tempfile.TemporaryDirectory() as workdir:
            src = Path(workdir) / "in.webm"
            src.write_bytes(b"x")
            with patch("im.voice.subprocess.run") as run:
                run.return_value = SimpleNamespace(stdout="", returncode=0)
                voice._transcode(src, Path(workdir) / "out.m4a")
        args = run.call_args.args[0]
        self.assertEqual(args[0], "ffmpeg")
        self.assertIn("-nostdin", args)
        self.assertEqual(args[args.index("-protocol_whitelist") + 1], "file,pipe")
        self.assertEqual(args[args.index("-map_metadata") + 1], "-1")
        self.assertIn("-sn", args)
        self.assertIn("-dn", args)
        self.assertEqual(args[args.index("-threads") + 1], "1")
        self.assertFalse(run.call_args.kwargs.get("shell", False))

    def test_transcode_nonzero_exit_raises_voice_error(self):
        """ffmpeg 非零退出抛 VoiceError,不把裸异常漏给调用方。

        参数说明:
            无。
        """
        with tempfile.TemporaryDirectory() as workdir:
            with patch("im.voice.subprocess.run") as run:
                run.return_value = SimpleNamespace(stdout="", returncode=1)
                with self.assertRaises(voice.VoiceError):
                    voice._transcode(Path(workdir) / "in.m4a", Path(workdir) / "out.m4a")

    def test_transcode_timeout_raises_voice_error(self):
        """转码超时统一收敛成 VoiceError。

        参数说明:
            无。
        """
        with tempfile.TemporaryDirectory() as workdir:
            with patch("im.voice.subprocess.run",
                       side_effect=subprocess.TimeoutExpired("ffmpeg", 15)):
                with self.assertRaises(voice.VoiceError):
                    voice._transcode(Path(workdir) / "in.m4a", Path(workdir) / "out.m4a")

    def test_probe_timeout_raises_voice_error(self):
        """探测超时同样收敛成 VoiceError。

        参数说明:
            无。
        """
        with patch("im.voice.subprocess.run",
                   side_effect=subprocess.TimeoutExpired("ffprobe", 15)):
            with self.assertRaises(voice.VoiceError):
                voice._probe_ms(Path("a.m4a"))


class ChatVoiceCleanupTests(TestCase):
    """语音清理:30 天过期删文件,孤儿扫描不误删正常语音。"""

    def setUp(self):
        """把 ``MEDIA_ROOT`` 指向临时目录,并建一个语音所有者账号。

        参数说明:
            无。

        返回参数:
            无返回值。

        使用示例:
            ``unittest`` 在每条用例前自动调用 ``setUp()``。

        备注信息:
            临时目录随用例结束删除,不污染仓库内的 media/。
        """
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(phone="13900139010")

    def make_voice(self, name="v.m4a", created_days_ago=0):
        """造一条语音行(带真实文件)。

        参数说明:
            name: 文件名,默认 ``v.m4a``。
            created_days_ago: 创建时间距今的天数,0 表示就是现在。

        返回参数:
            保存后的 ``ChatVoice`` 实例。

        使用示例:
            ``voice = self.make_voice("old.m4a", created_days_ago=31)``

        备注信息:
            ``created_days_ago`` 走 ``UPDATE`` 回写,返回对象里的 ``created_at``
            仍是旧值,用例要校验时间需先 ``refresh_from_db()``。
        """
        voice = ChatVoice(owner=self.user, duration_ms=5000, bytes=3)
        voice.file.save(name, ContentFile(b"abc"), save=False)
        voice.save()
        if created_days_ago:
            ChatVoice.objects.filter(pk=voice.pk).update(
                created_at=timezone.now() - timedelta(days=created_days_ago))
        return voice

    def test_expires_old_voice_and_keeps_fresh(self):
        """超 30 天的语音置 EXPIRED 并删文件,新语音原样保留。

        参数说明:
            无。
        """
        old = self.make_voice("old.m4a", created_days_ago=31)
        fresh = self.make_voice("fresh.m4a")
        call_command("im_media_cleanup", "--apply")
        old.refresh_from_db()
        fresh.refresh_from_db()
        self.assertEqual(old.status, ChatVoiceStatus.EXPIRED)
        self.assertFalse(old.file.storage.exists(old.file.name))
        self.assertEqual(fresh.status, ChatVoiceStatus.VISIBLE)
        self.assertTrue(fresh.file.storage.exists(fresh.file.name))

    def test_orphan_scan_keeps_known_voice(self):
        """孤儿扫描按库内记录判断,文件被改旧也不会误删正常语音。

        参数说明:
            无。
        """
        voice = self.make_voice()
        path = Path(settings.MEDIA_ROOT) / voice.file.name
        os.utime(path, (time.time() - 48 * 3600, time.time() - 48 * 3600))
        call_command("im_media_cleanup", "--apply", "--orphan-hours", "24")
        self.assertTrue(voice.file.storage.exists(voice.file.name))




