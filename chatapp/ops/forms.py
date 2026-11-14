"""审核台的表单:登录,以及准入名单的加号。

设计要点:
    1. 登录复用 Django 自带的 ``AuthenticationForm``,只加一条 ``is_staff`` 校验 ——
       普通用户即使密码正确也不能进审核台(登录失败提示与密码错误一致,不泄漏账号属性);
    2. 准入名单表单的手机号格式与登录接口**同一份规则**(``accounts.validators``),
       否则会出现「能加进名单、登录却报格式错」的诡异状态。

文件信息:
    文件名称          ops/forms.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.exceptions import ValidationError

from accounts.validators import is_valid_phone


class OpsLoginForm(AuthenticationForm):
    """审核台登录表单:在标准校验之外要求账号是运营账号。

    参数说明:
        request: 当前请求,可为 ``None``。
        data: 表单数据,取 ``username``(手机号)与 ``password``。

    返回参数:
        表单实例;校验通过后 ``get_user()`` 返回该运营账号。

    使用示例:
        ``OpsLoginForm(request, data={"username": phone, "password": password})``

    备注信息:
        账号密码的校验完全沿用父类,只重写 ``confirm_login_allowed`` 一道钩子;
        构造参数与父类 ``AuthenticationForm`` 一致。
    """

    def confirm_login_allowed(self, user):
        """在父类校验通过后追加 ``is_staff`` 检查。

        参数说明:
            user: 已通过账号密码校验的用户。

        返回参数:
            无返回值。

        使用示例:
            ``form.confirm_login_allowed(user)``

        备注信息:
            父类实现已拦掉 ``is_active=False`` 的账号,这里只管 ``is_staff``;
            不通过时抛 ``ValidationError``(code=``no_staff``),文案「该账号无运营权限」
            由 ``LoginView`` 原样渲染到登录页。
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

    参数说明:
        data: 表单数据;``phone`` 必填(字段级只限最大长度 20),``note`` 可空(最长 100)。

    返回参数:
        表单实例;``is_valid()`` 通过后 ``cleaned_data`` 是两个已去首尾空白的字符串。

    使用示例:
        ``PhoneAllowlistForm({"phone": "13800138000", "note": "运营"})``

    备注信息:
        真正的 11 位格式校验在 ``clean_phone``,字段的 ``max_length=20`` 只防超长输入;
        「是否已在名单里」不在这里判,由视图决定是新增、启用还是只改备注。
    """

    phone = forms.CharField(max_length=20, label="手机号",
                            widget=forms.TextInput(attrs={"placeholder": "11 位手机号"}))
    note = forms.CharField(max_length=100, required=False, label="备注",
                           widget=forms.TextInput(attrs={"placeholder": "谁在用 / 为什么加"}))

    def clean_phone(self):
        """去掉首尾空白并校验手机号格式。

        参数说明:
            无。

        返回参数:
            规范化(去首尾空白)后的手机号。

        使用示例:
            ``form.cleaned_data["phone"]``

        备注信息:
            格式规则复用 ``accounts.validators.is_valid_phone``,与登录接口同一份;
            不通过时抛 ``ValidationError``,提示「手机号格式不正确(11 位,1 开头)」。
        """
        phone = self.cleaned_data["phone"].strip()
        if not is_valid_phone(phone):
            raise ValidationError("手机号格式不正确(11 位,1 开头)")
        return phone

    def clean_note(self):
        """去掉备注首尾空白。

        参数说明:
            无。

        返回参数:
            去空白后的备注,可能为空串。

        使用示例:
            ``form.cleaned_data["note"]``

        备注信息:
            100 字上限由字段的 ``max_length`` 在字段层拦截,这里只做 ``strip()``;
            未填时字段返回空串,因此返回值恒为 ``str``,不会是 ``None``。
        """
        return self.cleaned_data["note"].strip()
