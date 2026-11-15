"""审核台的表单:登录,以及准入名单的加号。

设计要点:
    1. 登录复用 Django 自带的 ``AuthenticationForm``,只加一条 ``is_staff`` 校验 ——
       普通用户即使密码正确也不能进审核台,此时提示是明确的「该账号无运营权限」而**不**
       伪装成密码错误:审核台不开放注册,「这个号不是运营号」不是需要隐藏的信息,
       说清楚比让人反复试密码更省事;
    2. 准入名单表单的手机号格式与登录接口**同一份规则**(``accounts.validators``),
       否则会出现「能加进名单、登录却报格式错」的诡异状态。
"""

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from accounts.validators import is_valid_phone


class OpsLoginForm(AuthenticationForm):
    """审核台登录表单:在标准校验之外要求账号是运营账号。"""

    def confirm_login_allowed(self, user):
        """在父类校验通过后追加 ``is_staff`` 检查。

        参数说明:
            user: 已通过账号密码校验的用户。

        使用示例:
            ``form.is_valid()`` 时由 Django 的 ``AuthenticationForm`` 调用
            (登录页 ``/ops/login/``,见 ``ops/urls.py`` 与 ``ops/tests.py`` 的 ``OpsAuthTests``)。

        备注信息:
            该账号没有运营权限时主动抛出 ``ValidationError``(``code="no_staff"``)。
        """
        super().confirm_login_allowed(user)
        if not user.is_staff:
            raise ValidationError("该账号无运营权限", code="no_staff")


class PhoneAllowlistForm(forms.Form):
    """把一个手机号加进准入名单。

    只校验格式;「是否已在名单里」交给视图处理 —— 重复提交一个已停用的号码
    应当是「重新启用」而不是报错(运营手上只有这一个入口,报错只是白跑一趟)。

    Attributes:
        phone: 11 位手机号。
        note: 备注(谁在用、为什么加),最长 100 字,可空。
    """

    phone = forms.CharField(max_length=20, label="手机号",
                            widget=forms.TextInput(attrs={"placeholder": "11 位手机号"}))
    note = forms.CharField(max_length=100, required=False, label="备注",
                           widget=forms.TextInput(attrs={"placeholder": "谁在用 / 为什么加"}))

    def clean_phone(self):
        """去掉首尾空白并校验手机号格式。

        返回参数:
            规范化后的手机号。

        使用示例:
            ``PhoneAllowlistForm(request.POST).is_valid()`` 时由 ``full_clean`` 调用
            (见 ``ops/views.py`` 的 ``allowlist_add``)。

        备注信息:
            不是中国大陆 11 位手机号时主动抛出 ``ValidationError``。
        """
        phone = self.cleaned_data["phone"].strip()
        if not is_valid_phone(phone):
            raise ValidationError("手机号格式不正确(11 位,1 开头)")
        return phone

    def clean_note(self):
        """去掉备注首尾空白。

        返回参数:
            去空白后的备注,可能为空串。

        使用示例:
            ``note = form.cleaned_data["note"]``(见 ``ops/views.py`` 的 ``allowlist_add``)。

        备注信息:
            无特殊约束。
        """
        return self.cleaned_data["note"].strip()
