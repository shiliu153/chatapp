"""审核台的登录表单。

设计要点:
    复用 Django 自带的 ``AuthenticationForm``,只加一条 ``is_staff`` 校验 ——
    普通用户即使密码正确也不能进审核台(登录失败提示与密码错误一致,不泄漏账号属性)。
"""

from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError


class OpsLoginForm(AuthenticationForm):
    """审核台登录表单:在标准校验之外要求账号是运营账号。"""

    def confirm_login_allowed(self, user):
        """在父类校验通过后追加 ``is_staff`` 检查。

        Args:
            user: 已通过账号密码校验的用户。

        Raises:
            ValidationError: 该账号没有运营权限。
        """
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise ValidationError("该账号无运营权限", code="no_staff")
