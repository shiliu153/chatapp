import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings
from rest_framework.test import APITestCase
from rest_framework_simplejwt.tokens import RefreshToken

from users.models import Profile, ProfileStatus

from .client import _request, import_account, kick_user, send_custom_elem, send_match_notice, send_text
from .signature import _hmac_sha256, decode_user_sig, gen_user_sig

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


@override_settings(**IM_TEST_SETTINGS)
class UserSigApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(phone="13800138000")
        token = RefreshToken.for_user(self.user).access_token
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    def test_returns_sig_for_current_user(self):
        resp = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["im_user_id"], f"u{self.user.id}")
        self.assertEqual(data["sdkappid"], "1400000000")
        self.assertEqual(data["expire"], 604800)
        self.assertEqual(decode_user_sig(data["user_sig"])["TLS.identifier"], f"u{self.user.id}")

    def test_requires_auth(self):
        self.client.credentials()
        resp = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(resp.status_code, 401)

    def test_heavy_banned_rejected(self):
        Profile.objects.create(user=self.user, status=ProfileStatus.BANNED_HEAVY)
        resp = self.client.post("/api/v1/im/user_sig")
        self.assertEqual(resp.status_code, 403)
        self.assertEqual(resp.json()["code"], 403)
