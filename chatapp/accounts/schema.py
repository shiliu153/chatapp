"""OpenAPI schema 扩展(账号与鉴权)。

设计要点:
    ``SessionJwtAuthentication`` 是自定义认证类,drf-spectacular 不认识它;不注册扩展时
    生成 schema 会把每个接口的认证都报成「无法解析认证方式」,客户端生成器也就拿不到
    ``securitySchemes``。扩展类在定义时即注册进 drf-spectacular 的注册表,所以必须
    **在生成 schema 之前被导入** —— 由 ``AccountsConfig.ready()`` 负责(见 accounts/apps.py)。

注意事项:
    本模块只影响 OpenAPI 生成物,不改变任何运行时行为。

文件信息:
    文件名称          accounts/schema.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SessionJwtAuthenticationScheme(OpenApiAuthenticationExtension):
    """把 ``SessionJwtAuthentication`` 映射成 OpenAPI 的 HTTP Bearer 方案。

    参数说明:
        无(无参构造,注册由 drf-spectacular 的扩展注册表在导入时完成)。

    返回参数:
        扩展实例本身;其副作用是让 ``target_class`` 指向的认证类可被 schema 识别。

    使用示例:
        ``import accounts.schema``

    备注信息:
        ``target_class`` 按字符串导入路径匹配,因此本模块不 import 认证类,避免循环依赖;
        必须由 ``AccountsConfig.ready()`` 提前导入,否则生成 schema 时注册表里还没有它。
    """

    target_class = "accounts.authentication.SessionJwtAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema):
        """返回 ``components.securitySchemes`` 中的认证方案定义。

        参数说明:
            auto_schema: drf-spectacular 传入的当前 ``AutoSchema`` 实例(本实现未使用)。

        返回参数:
            OpenAPI 3.0 的 securityScheme 字典。

        使用示例:
            ``SessionJwtAuthenticationScheme().get_security_definition(auto_schema)``

        备注信息:
            结构固定为 ``http`` + ``bearer`` + ``JWT``;方案名取类属性 ``name``
            (``bearerAuth``),各接口的 ``security`` 引用同一个名字。
        """
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
