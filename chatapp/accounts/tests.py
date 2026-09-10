from django.contrib.auth import get_user_model
from django.test import TestCase

User = get_user_model()


class UserManagerTests(TestCase):
    def test_create_user_requires_phone(self):
        user = User.objects.create_user(phone="13800138000")
        self.assertEqual(user.phone, "13800138000")
        self.assertFalse(user.has_usable_password())  # 验证码登录:无密码

    def test_create_superuser(self):
        admin = User.objects.create_superuser(phone="13900139000", password="admin-pass")
        self.assertTrue(admin.is_staff)
        self.assertTrue(admin.is_superuser)
