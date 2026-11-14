"""appconfig 测试。

文件信息:
    文件名称          appconfig/tests.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.test import override_settings
from rest_framework.test import APITestCase


class AppConfigTests(APITestCase):
    """公开版本配置接口。"""

    @override_settings(MIN_APP_VERSION="1.1.0", LATEST_APP_VERSION="1.2.0",
                       APP_DOWNLOAD_URL="https://example.com/app.apk")
    def test_public_config(self):
        """匿名可读,返回值与 settings 里的三项版本配置一致。

        参数说明:
            无。
        """
        response = self.client.get("/api/v1/app/config")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["min_app_version"], "1.1.0")
        self.assertEqual(response.data["latest_version"], "1.2.0")
        self.assertEqual(response.data["download_url"], "https://example.com/app.apk")
