from rest_framework.test import APITestCase


class ErrorEnvelopeTests(APITestCase):
    def test_error_response_uses_code_message_envelope(self):
        resp = self.client.post("/api/v1/health")  # health 只允许 GET,触发 405
        self.assertEqual(resp.status_code, 405)
        self.assertEqual(resp.json()["code"], 405)
        self.assertIn("message", resp.json())
