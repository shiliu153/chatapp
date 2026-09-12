import io
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase, override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import Photo, PhotoStatus, Profile, ProfileStatus

from feed.models import Post, PostComment

from .client import (_request, black_list_add, black_list_delete, ensure_account,
                     import_account, kick_user, send_ban_lifted, send_ban_notice,
                     send_custom_elem, send_match_notice, send_post_commented,
                     send_report_handled, send_text,
                     set_profile_avatar, set_profile_nick)
from .signature import _hmac_sha256, decode_user_sig, gen_user_sig
from .tasks import (ban_lifted, ban_notice, blacklist_add, blacklist_remove,
                    import_account as import_account_task, kick_pending,
                    kick_pending_key, post_commented as post_commented_task,
                    report_handled as report_handled_task, sync_profile)
from .tasks import send_match_notice as send_match_notice_task

User = get_user_model()

IM_TEST_SETTINGS = dict(
    IM_SDKAPPID="1400000000",
    IM_SECRETKEY="k" * 32,
    IM_ADMIN_IDENTIFIER="administrator",
    IM_SIG_EXPIRE=604800,
    IM_REST_BASE="https://console.tim.qq.com/v4",
    IM_TIMEOUT=5,
)


@override_settings(**IM_TEST_SETTINGS)
class UserSigTests(SimpleTestCase):
    def test_encode_then_decode_keeps_fields(self):
        sig = gen_user_sig("u1", now=1700000000)
        doc = decode_user_sig(sig)
        self.assertEqual(doc["TLS.ver"], "2.0")
        self.assertEqual(doc["TLS.identifier"], "u1")
        self.assertEqual(doc["TLS.sdkappid"], 1400000000)
        self.assertEqual(doc["TLS.time"], 1700000000)
        self.assertEqual(doc["TLS.expire"], 604800)

    def test_sig_field_matches_official_hmac_formula(self):
        sig = gen_user_sig("u1", now=1700000000)
        doc = decode_user_sig(sig)
        expected = _hmac_sha256("u1", 1400000000, 1700000000, 604800, "k" * 32)
        self.assertEqual(doc["TLS.sig"], expected)

    def test_uses_tencent_base64_variant(self):
        sig = gen_user_sig("u1")
        for ch in "+/=":
            self.assertNotIn(ch, sig)


@override_settings(**IM_TEST_SETTINGS)
class ImClientTests(SimpleTestCase):
    def test_request_builds_tencent_params(self):
        with patch("im.client.requests.post") as post:
            post.return_value.json.return_value = {"ErrorCode": 0}
            _request("openim", "sendmsg", {"a": 1})
        args, kwargs = post.call_args
        self.assertTrue(args[0].endswith("/openim/sendmsg"))
        self.assertEqual(kwargs["params"]["sdkappid"], "1400000000")
        self.assertEqual(kwargs["params"]["identifier"], "administrator")
        self.assertEqual(kwargs["params"]["contenttype"], "json")
        self.assertIn("usersig", kwargs["params"])
        self.assertIn("random", kwargs["params"])
        self.assertEqual(kwargs["json"], {"a": 1})

    def test_import_account_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(import_account("u1", "小明"))
        args, _ = req.call_args
        self.assertEqual(args[0], "im_open_login_svc")
        self.assertEqual(args[1], "account_import")
        self.assertEqual(args[2]["Identifier"], "u1")
        self.assertEqual(args[2]["Nick"], "小明")

    def test_import_account_error_code_returns_false(self):
        with patch("im.client._request", return_value={"ErrorCode": 7015, "ErrorInfo": "exist"}):
            self.assertFalse(import_account("u1"))

    def test_import_account_network_error_returns_false(self):
        with patch("im.client._request", side_effect=Exception("boom")):
            self.assertFalse(import_account("u1"))

    def test_send_custom_elem_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(send_custom_elem("u1", "u2", {"type": "match_notice"}, "灰条"))
        args, kwargs = req.call_args
        self.assertEqual(args[0], "openim")
        self.assertEqual(args[1], "sendmsg")
        self.assertIsNone(kwargs.get("identifier"))   # 必须以管理员身份调(错误码 60010),发送方看 From_Account
        payload = args[2]
        self.assertEqual(payload["From_Account"], "u1")
        self.assertEqual(payload["To_Account"], "u2")
        body = payload["MsgBody"][0]
        self.assertEqual(body["MsgType"], "TIMCustomElem")
        self.assertEqual(json.loads(body["MsgContent"]["Data"]), {"type": "match_notice"})
        self.assertEqual(body["MsgContent"]["Desc"], "灰条")

    def test_send_match_notice_sends_both_directions(self):
        with patch("im.client.send_custom_elem", return_value=True) as send:
            self.assertTrue(send_match_notice("u1", "u2"))
        self.assertEqual(send.call_count, 2)
        self.assertEqual(send.call_args_list[0][0][:2], ("u1", "u2"))
        self.assertEqual(send.call_args_list[1][0][:2], ("u2", "u1"))

    def test_send_text_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(send_text("u1", "u2", "你好"))
        args, _ = req.call_args
        self.assertEqual(args[0], "openim")
        self.assertEqual(args[1], "sendmsg")
        payload = args[2]
        self.assertEqual(payload["From_Account"], "u1")
        self.assertEqual(payload["To_Account"], "u2")
        body = payload["MsgBody"][0]
        self.assertEqual(body["MsgType"], "TIMTextElem")
        self.assertEqual(body["MsgContent"]["Text"], "你好")

    def test_kick_user_payload(self):
        with patch("im.client._request", return_value={"ActionStatus": "OK", "ErrorCode": 0}) as req:
            self.assertTrue(kick_user("u5"))
        args, _ = req.call_args
        self.assertEqual(args[0], "im_open_login_svc")
        self.assertEqual(args[1], "kick")
        self.assertEqual(args[2], {"UserID": "u5"})

    def test_kick_user_network_error_returns_false(self):
        with patch("im.client._request", side_effect=Exception("boom")):
            self.assertFalse(kick_user("u5"))

    def test_set_profile_nick_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(set_profile_nick("u1", "小明"))
        args, _ = req.call_args
        self.assertEqual(args[0], "profile")
        self.assertEqual(args[1], "portrait_set")
        self.assertEqual(args[2]["From_Account"], "u1")
        self.assertEqual(args[2]["ProfileItem"],
                         [{"Tag": "Tag_Profile_IM_Nick", "Value": "小明"}])

    def test_set_profile_nick_error_returns_false(self):
        with patch("im.client._request", return_value={"ErrorCode": 9999}):
            self.assertFalse(set_profile_nick("u1", "小明"))

    def test_set_profile_nick_network_error_returns_false(self):
        with patch("im.client._request", side_effect=Exception("boom")):
            self.assertFalse(set_profile_nick("u1", "小明"))

    def test_set_profile_avatar_payload(self):
        # 实测字段名必须是 Tag_Profile_IM_Image,写成 Url 腾讯回 40009
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(set_profile_avatar("u1", "http://x/a.jpg"))
        args, _ = req.call_args
        self.assertEqual(args[2]["ProfileItem"],
                         [{"Tag": "Tag_Profile_IM_Image", "Value": "http://x/a.jpg"}])

    def test_black_list_add_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(black_list_add("u1", "u2"))
        args, _ = req.call_args
        self.assertEqual(args[0], "sns")
        self.assertEqual(args[1], "black_list_add")
        self.assertEqual(args[2], {"From_Account": "u1", "To_Account": ["u2"]})

    def test_black_list_delete_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(black_list_delete("u1", "u2"))
        args, _ = req.call_args
        self.assertEqual(args[1], "black_list_delete")

    def test_black_list_error_returns_false(self):
        with patch("im.client._request", side_effect=Exception("boom")):
            self.assertFalse(black_list_add("u1", "u2"))

    def test_ensure_account_existing_is_success(self):
        with patch("im.client._request", return_value={"ErrorCode": 7015, "ErrorInfo": "exist"}):
            self.assertTrue(ensure_account("system_notice", "系统通知"))

    def test_ensure_account_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(ensure_account("system_notice", "系统通知"))
        args = req.call_args[0]
        self.assertEqual(args[0], "im_open_login_svc")
        self.assertEqual(args[1], "account_import")
        self.assertEqual(args[2]["Identifier"], "system_notice")
        self.assertEqual(args[2]["Nick"], "系统通知")

    def test_ensure_account_other_error_returns_false(self):
        with patch("im.client._request", return_value={"ErrorCode": 9999}):
            self.assertFalse(ensure_account("system_notice"))

    def test_send_ban_notice_light_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(send_ban_notice("u9", "light", "骚扰他人"))
        args = req.call_args[0]
        self.assertEqual(args[:2], ("openim", "sendmsg"))
        payload = args[2]
        self.assertEqual(payload["From_Account"], "system_notice")
        self.assertEqual(payload["To_Account"], "u9")
        content = payload["MsgBody"][0]["MsgContent"]
        self.assertEqual(json.loads(content["Data"]), {"type": "ban_notice", "level": "light"})
        self.assertIn("骚扰他人", content["Desc"])
        self.assertIn("无法使用滑卡功能", content["Desc"])

    def test_send_ban_notice_heavy_reason_fallback(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            send_ban_notice("u9", "heavy", "")
        content = req.call_args[0][2]["MsgBody"][0]["MsgContent"]
        self.assertEqual(json.loads(content["Data"]), {"type": "ban_notice", "level": "heavy"})
        self.assertIn("违反社区规范", content["Desc"])
        self.assertIn("封禁期间所有功能暂停使用", content["Desc"])

    def test_send_ban_lifted_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(send_ban_lifted("u9"))
        content = req.call_args[0][2]["MsgBody"][0]["MsgContent"]
        self.assertEqual(json.loads(content["Data"]), {"type": "ban_lifted"})
        self.assertIn("已解除", content["Desc"])

    def test_send_ban_notice_network_error_returns_false(self):
        with patch("im.client._request", side_effect=RuntimeError("boom")):
            self.assertFalse(send_ban_notice("u9", "light", "x"))

    def test_send_report_handled_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(send_report_handled("u9"))
        args = req.call_args[0]
        self.assertEqual(args[:2], ("openim", "sendmsg"))
        payload = args[2]
        self.assertEqual(payload["From_Account"], "system_notice")
        self.assertEqual(payload["To_Account"], "u9")
        content = payload["MsgBody"][0]["MsgContent"]
        self.assertEqual(json.loads(content["Data"]), {"type": "report_handled"})
        self.assertEqual(content["Desc"], "您提交的举报已处理,感谢您对社区安全的支持。")

    def test_send_report_handled_network_error_returns_false(self):
        with patch("im.client._request", side_effect=RuntimeError("boom")):
            self.assertFalse(send_report_handled("u9"))


class PostCommentedClientTests(TestCase):
    def test_send_post_commented_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(send_post_commented("u9", "小红", "好漂亮"))
        args = req.call_args[0]
        self.assertEqual(args[:2], ("openim", "sendmsg"))
        payload = args[2]
        self.assertEqual(payload["From_Account"], "system_notice")
        self.assertEqual(payload["To_Account"], "u9")
        content = payload["MsgBody"][0]["MsgContent"]
        self.assertEqual(json.loads(content["Data"]), {"type": "post_commented"})
        self.assertEqual(content["Desc"], "小红 评论了你的动态:好漂亮")

    def test_send_post_commented_network_error_returns_false(self):
        with patch("im.client._request", side_effect=RuntimeError("boom")):
            self.assertFalse(send_post_commented("u9", "小红", "好漂亮"))


class PostCommentedTaskTests(TestCase):
    def setUp(self):
        self.author = User.objects.create_user(phone="13800138000")
        self.commenter = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.commenter, nickname="小红")
        self.post = Post.objects.create(author=self.author, text="动态")

    def test_task_sends_notice_to_author(self):
        comment = PostComment.objects.create(post=self.post, author=self.commenter,
                                             text="好漂亮")
        with patch("im.client.send_post_commented", return_value=True) as send:
            post_commented_task.run(comment.id)
        send.assert_called_once_with(self.author.im_user_id, "小红", "好漂亮")

    def test_self_comment_not_sent(self):
        comment = PostComment.objects.create(post=self.post, author=self.author, text="自评")
        with patch("im.client.send_post_commented") as send:
            post_commented_task.run(comment.id)
        send.assert_not_called()

    def test_missing_comment_is_silent(self):
        post_commented_task.run(999999)   # 不抛异常


class ImSendCommandTests(SimpleTestCase):
    def test_text_and_notice_are_mutually_exclusive(self):
        with self.assertRaises(CommandError):
            call_command("im_send", sender="u1", receiver="u2", text="hi", notice=True)
        with self.assertRaises(CommandError):
            call_command("im_send", sender="u1", receiver="u2")

    def test_sends_text(self):
        with patch("im.management.commands.im_send.send_text", return_value=True) as send:
            call_command("im_send", sender="u1", receiver="u2", text="hi")
        send.assert_called_once_with("u1", "u2", "hi")

    def test_sends_match_notice(self):
        with patch("im.management.commands.im_send.send_custom_elem", return_value=True) as send:
            call_command("im_send", sender="u1", receiver="u2", notice=True)
        args = send.call_args[0]
        self.assertEqual(args[:2], ("u1", "u2"))
        self.assertEqual(args[2], {"type": "match_notice"})

    def test_send_failure_raises(self):
        with patch("im.management.commands.im_send.send_text", return_value=False):
            with self.assertRaises(CommandError):
                call_command("im_send", sender="u1", receiver="u2", text="hi")


class ImSetupSystemAccountCommandTests(SimpleTestCase):
    def test_command_creates_system_account(self):
        with patch("im.management.commands.im_setup_system_account.ensure_account",
                   return_value=True) as ensure:
            call_command("im_setup_system_account")
        ensure.assert_called_once_with("system_notice", "系统通知")

    def test_command_raises_when_not_ready(self):
        with patch("im.management.commands.im_setup_system_account.ensure_account",
                   return_value=False):
            with self.assertRaises(CommandError):
                call_command("im_setup_system_account")


class ImSyncNicknamesCommandTests(TestCase):
    def test_syncs_all_nicknamed_profiles(self):
        user = User.objects.create_user(phone="13800138000")
        Profile.objects.update_or_create(user=user, defaults={"nickname": "小明"})
        with patch("im.management.commands.im_sync_nicknames.set_profile_nick",
                   return_value=True) as sync:
            call_command("im_sync_nicknames")
        sync.assert_any_call(user.im_user_id, "小明")

    def test_skips_users_without_nickname(self):
        user = User.objects.create_user(phone="13800138001")
        Profile.objects.update_or_create(user=user, defaults={"nickname": ""})
        with patch("im.management.commands.im_sync_nicknames.set_profile_nick",
                   return_value=True) as sync:
            call_command("im_sync_nicknames")
        sync.assert_not_called()

    def test_reports_failure_count(self):
        user = User.objects.create_user(phone="13800138002")
        Profile.objects.update_or_create(user=user, defaults={"nickname": "小红"})
        out = io.StringIO()
        with patch("im.management.commands.im_sync_nicknames.set_profile_nick",
                   return_value=False):
            call_command("im_sync_nicknames", stdout=out)
        self.assertIn("失败 1", out.getvalue())


@override_settings(**IM_TEST_SETTINGS)
class UserSigApiTests(APITestCase):
    def setUp(self):
        cache.clear()   # 清 im:imported 标记,否则第二次跑测试时 ensure_account 不会被调用
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(phone="13800138000")
        token = RefreshToken.for_user(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_returns_sig_for_current_user(self):
        with patch("im.views.ensure_account", return_value=True) as ensure, \
                patch("im.views.kick_user") as kick:
            resp = self.client.post("/api/v1/im/user_sig")
        ensure.assert_called_once_with(self.user.im_user_id)
        kick.assert_not_called()   # 没有待踢标记时不踢(否则会把本机会话踢掉)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["im_user_id"], f"u{self.user.id}")
        self.assertEqual(data["sdkappid"], "1400000000")
        self.assertEqual(data["expire"], 604800)
        self.assertEqual(decode_user_sig(data["user_sig"])["TLS.identifier"], f"u{self.user.id}")

    def test_pending_kick_runs_before_issuing_sig(self):
        cache.set(kick_pending_key(self.user.id), 1, 60)
        with patch("im.views.ensure_account", return_value=True), \
                patch("im.views.kick_user", return_value=True) as kick:
            resp = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(resp.status_code, 200)
        kick.assert_called_once_with(self.user.im_user_id)
        self.assertIsNone(cache.get(kick_pending_key(self.user.id)))

    def test_requires_auth(self):
        self.client.credentials()
        resp = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(resp.status_code, 401)

    def test_heavy_banned_rejected(self):
        Profile.objects.create(user=self.user, status=ProfileStatus.BANNED_HEAVY)
        resp = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], 403)


class ImTaskTests(TestCase):
    """IM 副作用任务:失败要抛异常(Celery 才会重试),查不到用户则静默跳过。"""

    def setUp(self):
        cache.clear()
        self.addCleanup(cache.clear)
        self.user = User.objects.create_user(phone="13800138000")

    def test_import_account_task_calls_client(self):
        with patch("im.client.import_account", return_value=True) as imp:
            import_account_task.run(self.user.id)
        imp.assert_called_once_with(self.user.im_user_id)

    def test_import_failure_raises_so_celery_retries(self):
        with patch("im.client.import_account", return_value=False):
            with self.assertRaises(RuntimeError):
                import_account_task.run(self.user.id)

    def test_kick_pending_noop_without_flag(self):
        with patch("im.client.kick_user") as kick:
            kick_pending.run(self.user.id)
        kick.assert_not_called()

    def test_kick_pending_kicks_and_clears_flag(self):
        cache.set(kick_pending_key(self.user.id), 1, 60)
        with patch("im.client.kick_user", return_value=True) as kick:
            kick_pending.run(self.user.id)
        kick.assert_called_once_with(self.user.im_user_id)
        self.assertIsNone(cache.get(kick_pending_key(self.user.id)))

    def test_kick_pending_keeps_flag_and_raises_on_failure(self):
        cache.set(kick_pending_key(self.user.id), 1, 60)
        with patch("im.client.kick_user", return_value=False):
            with self.assertRaises(RuntimeError):
                kick_pending.run(self.user.id)
        self.assertIsNotNone(cache.get(kick_pending_key(self.user.id)))


class ImSideEffectTaskTests(TestCase):
    """第 2 期:配对灰条 / 封禁通知 / 黑名单 / 资料同步的任务体。"""

    def setUp(self):
        self.a = User.objects.create_user(phone="13800138000")
        self.b = User.objects.create_user(phone="13900139000")
        Profile.objects.create(user=self.b, nickname="小红")

    def test_send_match_notice_task(self):
        with patch("im.client.send_match_notice", return_value=True) as send:
            send_match_notice_task.run(self.a.id, self.b.id)
        send.assert_called_once_with(self.a.im_user_id, self.b.im_user_id)

    def test_blacklist_add_and_remove(self):
        with patch("im.client.black_list_add", return_value=True) as add:
            blacklist_add.run(self.a.id, self.b.id)
        add.assert_called_once_with(self.a.im_user_id, self.b.im_user_id)
        with patch("im.client.black_list_delete", return_value=True) as delete:
            blacklist_remove.run(self.a.id, self.b.id)
        delete.assert_called_once_with(self.a.im_user_id, self.b.im_user_id)

    def test_ban_notice_light_only_sends(self):
        with patch("im.client.send_ban_notice", return_value=True) as send, \
                patch("im.client.kick_user") as kick:
            ban_notice.run(self.b.id, "light", "骚扰他人")
        send.assert_called_once_with(self.b.im_user_id, "light", "骚扰他人")
        kick.assert_not_called()

    def test_ban_notice_heavy_sends_then_kicks(self):
        calls = []
        with patch("im.client.send_ban_notice",
                   side_effect=lambda *a: calls.append("send") or True), \
                patch("im.client.kick_user",
                      side_effect=lambda *a: calls.append("kick") or True):
            ban_notice.run(self.b.id, "heavy", "严重违规")
        self.assertEqual(calls, ["send", "kick"])   # 顺序不能反:先说明原因再断线

    def test_ban_notice_failure_raises_so_celery_retries(self):
        with patch("im.client.send_ban_notice", return_value=False):
            with self.assertRaises(RuntimeError):
                ban_notice.run(self.b.id, "light", "骚扰他人")

    def test_ban_lifted_task(self):
        with patch("im.client.send_ban_lifted", return_value=True) as send:
            ban_lifted.run(self.b.id)
        send.assert_called_once_with(self.b.im_user_id)

    def test_sync_profile_nick(self):
        with patch("im.client.set_profile_nick", return_value=True) as sync:
            sync_profile.run(self.b.id, "nick")
        sync.assert_called_once_with(self.b.im_user_id, "小红")

    @override_settings(MEDIA_BASE_URL="http://cdn.test")
    def test_sync_profile_avatar_uses_absolute_url(self):
        Photo.objects.create(user=self.b, file="photos/a.png", status=PhotoStatus.APPROVED)
        with patch("im.client.set_profile_avatar", return_value=True) as sync:
            sync_profile.run(self.b.id, "avatar")
        sync.assert_called_once_with(self.b.im_user_id, "http://cdn.test/media/photos/a.png")

    def test_sync_profile_avatar_without_approved_photo_is_noop(self):
        with patch("im.client.set_profile_avatar") as sync:
            sync_profile.run(self.b.id, "avatar")
        sync.assert_not_called()

    def test_report_handled_task(self):
        with patch("im.client.send_report_handled", return_value=True) as send:
            report_handled_task.run(self.a.id)
        send.assert_called_once_with(self.a.im_user_id)

    def test_report_handled_failure_raises_so_celery_retries(self):
        with patch("im.client.send_report_handled", return_value=False):
            with self.assertRaises(RuntimeError):
                report_handled_task.run(self.a.id)

    def test_report_handled_missing_user_is_noop(self):
        report_handled_task.run(999999)   # 不抛异常、不调用

    def test_missing_user_is_noop(self):
        send_match_notice_task.run(self.a.id, 999999)   # 不抛异常
        sync_profile.run(999999, "nick")
