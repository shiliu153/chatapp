"""IM 应用的测试:userSig 算法、REST 客户端、Celery 副作用任务、命令与接口。

覆盖场景:
    - userSig:编码后能还原、sig 字段符合官方 HMAC 公式、外层用腾讯 base64 变体;
    - REST 客户端:请求参数拼装、各接口的 payload 形状、错误码与网络异常一律返回 False,
      ``ensure_account`` 对已存在账号不重复导入(覆盖会清空昵称/头像的回归点);
    - 动态评论通知:客户端 payload 与任务侧收件人、自己评自己不发送、评论已删则静默;
    - 管理命令:``im_send``(文本与灰条互斥)、``im_setup_system_account``、
      ``im_sync_nicknames``(含失败计数);
    - userSig 接口:签发、重封禁 403、踢旧会话必须先于签发;
    - 副作用任务:``False`` 转异常以触发重试、缺用户时静默、注销删号不查库、
      解除配对时双向拉黑。
"""

import io
import json
import os
import shutil
import tempfile
import time
from datetime import timedelta
from io import StringIO
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth import get_user_model
from django.core.cache import cache
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

from feed.models import Post, PostComment

from . import media_sign
from .client import (_request, black_list_add, black_list_delete, delete_account,
                     ensure_account, import_account, kick_user, send_ban_lifted,
                     send_ban_notice, send_custom_elem, send_match_notice,
                     send_post_commented, send_report_handled, send_text,
                     set_profile_avatar, set_profile_nick)
from .models import ChatImage, ChatImageStatus
from .signature import _hmac_sha256, decode_user_sig, gen_user_sig
from .throttles import ChatImageThrottle
from .token import mint_im_token, verify_im_token
from .tasks import (ban_lifted, ban_notice, blacklist_add, blacklist_remove,
                    delete_account as delete_account_task,
                    import_account as import_account_task, kick_pending,
                    kick_pending_key, post_commented as post_commented_task,
                    report_handled as report_handled_task, sync_profile,
                    unmatch_blacklist)
from .tasks import send_match_notice as send_match_notice_task

User = get_user_model()

# 1×1 透明 PNG:最小合法图片,用于上传类用例
PNG_1PX = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
           b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
           b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82")

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
    """userSig 算法:可还原、sig 字段公式正确、外层编码是腾讯变体。"""

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
    """REST 客户端:参数拼装、各接口 payload、错误与异常都返回 False。"""

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

    def test_delete_account_payload(self):
        with patch("im.client._request", return_value={"ErrorCode": 0}) as req:
            self.assertTrue(delete_account("u9"))
        args, _ = req.call_args
        self.assertEqual(args[0], "im_open_login_svc")
        self.assertEqual(args[1], "account_delete")
        self.assertEqual(args[2], {"DeleteItem": [{"UserID": "u9"}]})

    def test_delete_account_error_code_returns_false(self):
        with patch("im.client._request",
                   return_value={"ErrorCode": 7011, "ErrorInfo": "account not exist"}):
            self.assertFalse(delete_account("u9"))

    def test_delete_account_network_error_returns_false(self):
        with patch("im.client._request", side_effect=Exception("boom")):
            self.assertFalse(delete_account("u9"))

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

    def test_ensure_account_existing_account_is_not_reimported(self):
        """⚠️ 回归:对已存在的账号再调 account_import 会把昵称/头像**清空**。

        实测(2026-10-12):account_import 对已存在账号返回 `ErrorCode: 0`(不是文档说的 7015),
        并且把 Nick/FaceUrl 覆盖成传入值 —— 于是 `POST /im/user_sig` 的首次 ensure_account
        会把刚同步好的昵称和头像抹掉,会话列表只剩 `u43`。
        所以已存在时必须**跳过**导入。
        """
        def fake_request(service, command, payload=None, identifier=None):
            if command == "account_check":
                return {"ErrorCode": 0, "ResultItem": [
                    {"UserID": "u9", "ResultCode": 0, "AccountStatus": "Imported"}]}
            raise AssertionError(f"不该调用 {command}(会把昵称/头像清空)")

        with patch("im.client._request", side_effect=fake_request):
            self.assertTrue(ensure_account("u9", "小雨"))

    def test_ensure_account_missing_account_imports(self):
        calls = []

        def fake_request(service, command, payload=None, identifier=None):
            calls.append(command)
            if command == "account_check":
                return {"ErrorCode": 0, "ResultItem": [
                    {"UserID": "u9", "ResultCode": 0, "AccountStatus": "NotImported"}]}
            return {"ErrorCode": 0}

        with patch("im.client._request", side_effect=fake_request):
            self.assertTrue(ensure_account("u9", "小雨"))

        self.assertEqual(calls, ["account_check", "account_import"])

    def test_ensure_account_check_failure_returns_false(self):
        """查不到状态时不敢盲目导入(导入是破坏性的),交给上层重试。"""
        with patch("im.client._request", side_effect=Exception("boom")):
            self.assertFalse(ensure_account("u9", "小雨"))

    def test_ensure_account_payload(self):
        def fake_request(service, command, payload=None, identifier=None):
            if command == "account_check":
                return {"ErrorCode": 0, "ResultItem": [
                    {"UserID": "system_notice", "AccountStatus": "NotImported"}]}
            self.assertEqual(command, "account_import")
            self.assertEqual(payload["Identifier"], "system_notice")
            self.assertEqual(payload["Nick"], "系统通知")
            return {"ErrorCode": 0}

        with patch("im.client._request", side_effect=fake_request):
            self.assertTrue(ensure_account("system_notice", "系统通知"))

    def test_ensure_account_other_error_returns_false(self):
        def fake_request(service, command, payload=None, identifier=None):
            if command == "account_check":
                return {"ErrorCode": 0, "ResultItem": [
                    {"UserID": "u9", "AccountStatus": "NotImported"}]}
            return {"ErrorCode": 9999}

        with patch("im.client._request", side_effect=fake_request):
            self.assertFalse(ensure_account("u9"))

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
    """动态评论通知的客户端层:以系统通知身份发出,文案带评论者昵称与摘要。"""

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
    """动态评论通知的任务层:收件人是作者,自己评自己不打扰,评论已删则静默。"""

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
    """``im_send`` 命令:文本与灰条互斥,发送失败要抛 CommandError。"""

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
    """``im_setup_system_account`` 命令:建「系统通知」账号,失败要抛 CommandError。"""

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
    """``im_sync_nicknames`` 命令:同步全部非空昵称,并汇总失败数。"""

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
    """``POST /im/user_sig``:签发内容、重封禁 403、踢旧会话先于签发。"""

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

    def test_unmatch_blacklist_blocks_both_directions(self):
        calls = []
        with patch("im.client.black_list_add",
                   side_effect=lambda *args: calls.append(args) or True):
            unmatch_blacklist.run(self.a.id, self.b.id)
        self.assertEqual(calls, [
            (self.a.im_user_id, self.b.im_user_id),
            (self.b.im_user_id, self.a.im_user_id),
        ])

    def test_unmatch_blacklist_failure_raises_so_celery_retries(self):
        with patch("im.client.black_list_add", return_value=False):
            with self.assertRaises(RuntimeError):
                unmatch_blacklist.run(self.a.id, self.b.id)

    def test_unmatch_blacklist_missing_user_is_noop(self):
        with patch("im.client.black_list_add") as add:
            unmatch_blacklist.run(self.a.id, 999999)
        add.assert_not_called()

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
                      side_effect=lambda *a, **k: calls.append("kick") or True):
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


class ImDeleteAccountTaskTests(TestCase):
    """注销删号:先踢后删;踢失败不阻塞删号;删号失败抛异常让 Celery 重试。

    回归重点:任务**不查库** —— 调用时用户行已经删掉了,参数是 im_user_id。
    """

    def test_kicks_then_deletes(self):
        calls = []
        with patch("im.client.kick_user",
                   side_effect=lambda *a: calls.append("kick") or True), \
                patch("im.client.delete_account",
                      side_effect=lambda *a: calls.append("delete") or True):
            delete_account_task.run("u9")
        self.assertEqual(calls, ["kick", "delete"])   # 顺序不能反:先断在线会话再删号

    def test_kick_failure_does_not_block_delete(self):
        with patch("im.client.kick_user", return_value=False), \
                patch("im.client.delete_account", return_value=True) as delete:
            delete_account_task.run("u9")   # 不抛异常
        delete.assert_called_once_with("u9")

    def test_delete_failure_raises_so_celery_retries(self):
        with patch("im.client.kick_user", return_value=True), \
                patch("im.client.delete_account", return_value=False):
            with self.assertRaises(RuntimeError):
                delete_account_task.run("u9")

    def test_does_not_touch_database(self):
        with patch("im.client.kick_user", return_value=True), \
                patch("im.client.delete_account", return_value=True), \
                patch("im.tasks._user") as user_lookup:
            delete_account_task.run("u9")
        user_lookup.assert_not_called()


class ImTokenTests(SimpleTestCase):
    """自建 IM token 的签发与校验。"""

    @override_settings(IM_SELF_SECRET="t" * 32)
    def test_mint_and_verify(self):
        token = mint_im_token(9, 3600)
        claims = verify_im_token(token)
        self.assertIsNotNone(claims)
        self.assertEqual(claims["uid"], 9)
        self.assertEqual(claims["sub"], "u9")

    @override_settings(IM_SELF_SECRET="t" * 32)
    def test_reject_tampered(self):
        token = mint_im_token(9, 3600)
        self.assertIsNone(verify_im_token(token[:-1] + ("A" if token[-1] != "A" else "B")))


class SelfBackendTests(SimpleTestCase):
    """门面按账号灰度分发,未命中时仍走腾讯。"""

    @override_settings(IM_BACKEND="self", IM_SELF_GRAYLIST="2")
    @patch("im.client.self_client.send_custom_elem", return_value=True)
    def test_gray_recipient_dispatches(self, mocked):
        self.assertTrue(send_custom_elem("u1", "u2", {"type": "match_notice"}, "hi"))
        mocked.assert_called_once()

    @override_settings(IM_BACKEND="self", IM_SELF_GRAYLIST="1")
    @patch("im.client._request")
    def test_non_gray_recipient_stays_tencent(self, request):
        request.return_value = {"ErrorCode": 0}
        self.assertTrue(send_custom_elem("u1", "u2", {"type": "x"}, "hi"))
        request.assert_called_once()

    @override_settings(IM_BACKEND="tencent")
    @patch("im.client._request")
    def test_tencent_still_default(self, request):
        request.return_value = {"ErrorCode": 0}
        self.assertTrue(send_custom_elem("u1", "u2", {"type": "x"}, "hi"))


class UserSigSelfTests(APITestCase):
    """``/im/user_sig`` 的双分支与灰度。"""

    def setUp(self):
        self.user = User.objects.create_user(phone="13800000001")

    @override_settings(
        IM_BACKEND="self",
        IM_SELF_GRAYLIST="all",
        IM_SELF_WS_URL="wss://im.example/ws",
        IM_SELF_HTTP_URL="https://im.example/api",
        IM_SELF_SECRET="t" * 32,
        IM_SELF_TOKEN_TTL=86400,
    )
    @patch("im.views.ensure_account", return_value=True)
    def test_self_branch_returns_token(self, _):
        self.client.force_authenticate(self.user)
        response = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["backend"], "self")
        self.assertEqual(response.data["ws_url"], "wss://im.example/ws")
        self.assertTrue(response.data["token"])

    @override_settings(IM_BACKEND="self", IM_SELF_GRAYLIST="")
    @patch("im.views.gen_user_sig", return_value="tencent-sig")
    def test_not_in_graylist_falls_back(self, _):
        self.client.force_authenticate(self.user)
        response = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(response.data["backend"], "tencent")
        self.assertEqual(response.data["user_sig"], "tencent-sig")


class SelfNoticeTests(SimpleTestCase):
    """自建后端下的封禁/解封通知。"""

    @override_settings(IM_BACKEND="self", IM_SELF_GRAYLIST="9")
    @patch("im.client.self_client.send_custom_elem", return_value=True)
    @patch("im.client.self_client.kick_user", return_value=True)
    def test_heavy_ban_blocks_and_notifies(self, kick, send):
        with patch("im.tasks._user") as user:
            user.return_value.im_user_id = "u9"
            ban_notice.run(9, "heavy", "违规")
        send.assert_called_once()
        kick.assert_called_once_with("u9", True)

    @override_settings(IM_BACKEND="self", IM_SELF_GRAYLIST="9")
    @patch("im.client.self_client.send_ban_lifted", return_value=True)
    def test_ban_lifted_unblocks(self, lifted):
        with patch("im.tasks._user") as user:
            user.return_value.im_user_id = "u9"
            ban_lifted.run(9)
        lifted.assert_called_once_with("u9")

class ChatImageModelTests(TestCase):
    """聊天图片元数据:默认状态、可读表示、随用户级联删除。"""

    def setUp(self):
        self.media_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.media_dir, ignore_errors=True)
        override = self.settings(MEDIA_ROOT=self.media_dir)
        override.enable()
        self.addCleanup(override.disable)
        self.user = User.objects.create_user(phone="13900139001")

    def test_defaults_to_visible_and_str_is_readable(self):
        image = ChatImage.objects.create(
            owner=self.user,
            file=SimpleUploadedFile("a.jpg", PNG_1PX, content_type="image/jpeg"),
            thumb=SimpleUploadedFile("a_thumb.jpg", PNG_1PX, content_type="image/jpeg"),
            width=10, height=20, bytes=len(PNG_1PX))
        self.assertEqual(image.status, ChatImageStatus.VISIBLE)
        self.assertIn("chat_image#", str(image))

    def test_cascade_deletes_rows_with_user(self):
        ChatImage.objects.create(
            owner=self.user,
            file=SimpleUploadedFile("a.jpg", PNG_1PX, content_type="image/jpeg"),
            thumb=SimpleUploadedFile("a_thumb.jpg", PNG_1PX, content_type="image/jpeg"),
            width=10, height=20, bytes=len(PNG_1PX))
        self.user.delete()
        self.assertEqual(ChatImage.objects.count(), 0)

    def test_signed_urls_are_absolute_and_signed(self):
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
        image = ChatImage.objects.create(
            owner=self.user,
            file=SimpleUploadedFile("b.jpg", PNG_1PX, content_type="image/jpeg"),
            thumb=SimpleUploadedFile("b_thumb.jpg", PNG_1PX, content_type="image/jpeg"),
            width=1, height=1, bytes=len(PNG_1PX),
            status=ChatImageStatus.EXPIRED)
        self.assertIsNone(image.expired_at)

def _jpeg_with_orientation(size=(40, 20), orientation=6):
    """生成一张带 EXIF 方向标签的 JPEG(6 = 顺时针 90°,显示时宽高互换)。

    Args:
        size: 原始像素尺寸(宽, 高)。
        orientation: EXIF Orientation 值。

    Returns:
        JPEG 字节内容。
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

        Args:
            name: 文件名。
            content: 文件字节内容。
            content_type: MIME 类型。

        Returns:
            DRF 测试客户端的响应对象。
        """
        return self.client.post(
            self.url, {"file": SimpleUploadedFile(name, content, content_type=content_type)},
            format="multipart")

    def test_upload_returns_urls_and_dimensions(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201, response.data)
        data = response.data
        self.assertTrue(data["url"].startswith("http://cdn.test/media/chat/"))
        self.assertIn("?e=", data["url"])
        self.assertIn("&s=", data["url"])
        self.assertTrue(urlsplit(data["thumb_url"]).path.endswith("_thumb.jpg"))
        self.assertIn("&s=", data["thumb_url"])
        self.assertEqual((data["width"], data["height"]), (1, 1))
        self.assertEqual(data["size"], len(PNG_1PX))
        image = ChatImage.objects.get()
        self.assertEqual(image.owner_id, self.user.id)
        self.assertTrue(image.file.storage.exists(image.file.name))
        self.assertTrue(image.thumb.storage.exists(image.thumb.name))

    def test_uploaded_url_verifies_with_auth_helper(self):
        data = self.upload().data
        parts = urlsplit(data["url"])
        query = parse_qs(parts.query)
        self.assertTrue(media_sign.verify(parts.path, query["e"][0], query["s"][0]))

    def test_rejects_non_image(self):
        response = self.upload(name="a.txt", content=b"not an image", content_type="text/plain")
        self.assertEqual(response.status_code, 400)

    def test_rejects_oversized_file(self):
        with override_settings(CHAT_IMAGE_MAX_BYTES=10):
            response = self.upload()
        self.assertEqual(response.status_code, 400)
        self.assertIn("5MB", str(response.data))

    def test_rejects_too_large_side(self):
        with override_settings(CHAT_IMAGE_MAX_SIDE=0):
            response = self.upload()
        self.assertEqual(response.status_code, 400)

    def test_throttled_after_rate(self):
        # DRF 的 THROTTLE_RATES 是类属性,在 import 时就绑定了;测试只能替换这个属性
        with patch.object(ChatImageThrottle, "THROTTLE_RATES", {"chat_image": "2/hour"}):
            self.assertEqual(self.upload().status_code, 201)
            self.assertEqual(self.upload().status_code, 201)
            self.assertEqual(self.upload().status_code, 429)

    def test_heavy_banned_user_is_forbidden(self):
        profile = get_profile(self.user)          # 资料行是懒创建的,不能直接 user.profile
        profile.status = ProfileStatus.BANNED_HEAVY
        profile.save(update_fields=["status"])
        self.assertEqual(self.upload().status_code, 403)

    def test_exif_orientation_swaps_dimensions_and_reencodes(self):
        content = _jpeg_with_orientation()
        response = self.upload(name="rotated.jpg", content=content, content_type="image/jpeg")
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual((response.data["width"], response.data["height"]), (20, 40))
        self.assertTrue(urlsplit(response.data["url"]).path.endswith(".jpg"))


class MediaSignTests(SimpleTestCase):
    """聊天图片签名:共享向量、过期、篡改、路径白名单、未配置密钥时的放行。"""

    def test_shared_vector_matches_imserver(self):
        self.assertEqual(
            media_sign.signature("/media/chat/2026/10/12-abc.jpg", 1761782400,
                                 secret="test-media-secret"),
            "2b46b854b31a88877e318e3d12cb743fe76fccb2977e2d7ced879d7b3547d419")

    def test_expiry_is_bucket_aligned(self):
        # 1761779999 落在 1761778800 这个整点桶里,加 24h
        with override_settings(IM_MEDIA_SIGN_TTL=86400):
            self.assertEqual(media_sign.expires_at(1761779999), 1761865200)

    def test_sign_url_replaces_existing_query(self):
        with override_settings(IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=86400):
            signed = media_sign.sign_url("http://cdn.test/media/chat/a.jpg?e=1&s=old",
                                         now=1761782400)
        self.assertTrue(signed.startswith("http://cdn.test/media/chat/a.jpg?e="))
        self.assertNotIn("s=old", signed)

    def test_verify_accepts_valid_and_rejects_tampered(self):
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
        with override_settings(IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=60):
            signed = media_sign.sign_url("/media/chat/a.jpg", now=1761782400)
            query = parse_qs(urlsplit(signed).query)
            self.assertFalse(media_sign.verify("/media/chat/a.jpg", query["e"][0],
                                               query["s"][0], now=1761868800))
            self.assertFalse(media_sign.verify("/media/photos/a.jpg", query["e"][0],
                                               query["s"][0], now=1761782400))

    def test_disabled_secret_passes_everything(self):
        with override_settings(IM_MEDIA_SIGN_SECRET=""):
            self.assertEqual(media_sign.sign_url("/media/chat/a.jpg"), "/media/chat/a.jpg")
            self.assertTrue(media_sign.verify("/media/chat/a.jpg", "0", "bad"))


class ChatImageAuthTests(APITestCase):
    """nginx 子请求验签:有效 204、缺头/过期/篡改 403、无需 JWT。"""

    def setUp(self):
        self.url = "/api/v1/im/images/auth"
        self.media = "/media/chat/2026/10/12-abc.jpg"

    def auth(self, original):
        """带 ``X-Original-URI`` 调验签接口。

        Args:
            original: nginx 传入的原始 URI。

        Returns:
            DRF 响应对象。
        """
        return self.client.get(self.url, HTTP_X_ORIGINAL_URI=original)

    def signed(self):
        """生成一个当前有效的签名 URL。

        Returns:
            带 ``?e=&s=`` 的路径。
        """
        with override_settings(IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=86400):
            return media_sign.sign_url(self.media, now=int(time.time()))

    def test_valid_signature_passes_without_jwt(self):
        self.assertEqual(self.auth(self.signed()).status_code, 204)

    def test_missing_header_is_forbidden(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], 403)

    def test_expired_signature_is_forbidden(self):
        with override_settings(IM_MEDIA_SIGN_SECRET="s", IM_MEDIA_SIGN_TTL=60):
            stale = media_sign.sign_url(self.media, now=1)
            self.assertEqual(self.auth(stale).status_code, 403)

    def test_non_chat_path_is_forbidden(self):
        with override_settings(IM_MEDIA_SIGN_SECRET="s"):
            signed = media_sign.sign_url("/media/photos/a.jpg", now=int(time.time()))
        self.assertEqual(self.auth(signed).status_code, 403)

    def test_heavy_banned_user_can_still_view(self):
        user = User.objects.create_user(phone="13900139009")
        profile = get_profile(user)
        profile.status = ProfileStatus.BANNED_HEAVY
        profile.save(update_fields=["status"])
        self.assertEqual(self.auth(self.signed()).status_code, 204)


