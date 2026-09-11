from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError


class OpsLoginForm(AuthenticationForm):
    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise ValidationError("该账号无运营权限", code="no_staff")
