"""准入机制的部署期安全检查:把「固定码 + 名单空」从静默 fail-open 变成 check 红。

命中条件的四项同时成立才报错:
    1. 不是 ``DEBUG``(开发环境本来就该放行);
    2. 不是测试运行(``TESTING``,用例会临时改设置,不能因此变红);
    3. ``SMS_DEV_MODE`` 为真 —— 验证码固定 ``123456``,「知道号码 = 能接管账号」;
    4. ``SMS_PHONE_WHITELIST`` 为空 —— 连兜底种子都没有。

此时如果库内 ``accounts.PhoneAllowlist`` 也是空的,准入名单就形同虚设(库与种子都空,
严格模式下谁都进不来、非严格模式下谁都能进)。前一种情况是部署事故,后一种是安全缺口,
两者都不该静默通过 —— 所以宁可 ``manage.py check`` 变红,也不要在生产上悄悄全开。

为什么放在 check 而不是启动即崩(``raise ImproperlyConfigured``):``migrate`` /
``allowlist_seed_import`` 等运维命令本身要在「名单还没配好」的机器上跑,硬崩会把
自己锁死;``check`` 既能进部署流水线当门禁,又能用 ``--skip-checks`` 应急绕过。

关联文档:
    - 整改依据:docs/security/2026-11-08-api-security-audit-round4.md §4.2 M-1
    - 运维入口:docs/ops/runbook.md「准入名单的日常运维」
"""

from django.conf import settings
from django.core.checks import Error, Tags, register

#: 检查项标识;部署流水线与文档统一引用它(``manage.py check --deploy`` 输出里可见)。
DEV_SMS_WITHOUT_ALLOWLIST_ID = "accounts.E001"


@register(Tags.security)
def check_dev_sms_requires_allowlist(app_configs, **kwargs):
    """固定验证码已开、而准入名单种子为空时报警。

    Args:
        app_configs: Django 传入的待检查 app 列表;本检查看全局设置,不按 app 过滤。
        **kwargs: 检查框架的其它关键字参数(``databases`` 等),本检查不使用。

    Returns:
        list: 命中时一条 ``checks.Error``(id ``accounts.E001``),否则空列表。
    """
    if settings.DEBUG or getattr(settings, "TESTING", False):
        return []
    if not getattr(settings, "SMS_DEV_MODE", False):
        return []
    if settings.SMS_PHONE_WHITELIST:
        return []
    return [
        Error(
            "生产开启了固定验证码(SMS_DEV_MODE=1),但没有任何准入名单种子",
            hint=(
                "准入闸门是长期机制,必须配好名单再上线。三条出路任选其一:"
                "① 在 .env 设 SMS_PHONE_WHITELIST=13x...,13y... 当兜底种子;"
                "② 跑 python manage.py allowlist_seed_import 把种子导入数据库"
                "(名单仍为空时本检查会拦住所有管理命令,先加 --skip-checks);"
                "③ 确认这是封闭测试实例,显式设 SMS_ALLOWLIST_STRICT=0 并接受"
                "「任意手机号都能用固定码登录」的风险。"
            ),
            obj=None,
            id=DEV_SMS_WITHOUT_ALLOWLIST_ID,
        )
    ]
