from django.test import SimpleTestCase, override_settings

from .signature import _hmac_sha256, decode_user_sig, gen_user_sig

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
