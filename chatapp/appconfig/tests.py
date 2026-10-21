"""appconfig 测试。"""

from django.test import override_settings
from rest_framework.test import APITestCase


class AppConfigTests(APITestCase):
    """公开版本配置接口。"""

    @override_settings(MIN_APP_VERSION="1.1.0", LATEST_APP_VERSION="1.2.0",
                       APP_DOWNLOAD_URL="https://example.com/app.apk")
    def test_public_config(self):
        response = self.client.get("/api/v1/app/config")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["min_app_version"], "1.1.0")
        self.assertEqual(response.data["latest_version"], "1.2.0")
        self.assertEqual(response.data["download_url"], "https://example.com/app.apk")
