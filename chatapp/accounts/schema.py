"""OpenAPI schema 扩展(账号与鉴权)。

设计要点:
    ``SessionJwtAuthentication`` 是自定义认证类,drf-spectacular 不认识它;不注册扩展时
    生成 schema 会把每个接口的认证都报成「无法解析认证方式」,客户端生成器也就拿不到
    ``securitySchemes``。扩展类在定义时即注册进 drf-spectacular 的注册表,所以必须
    **在生成 schema 之前被导入** —— 由 ``AccountsConfig.ready()`` 负责(见 accounts/apps.py)。

注意事项:
    本模块只影响 OpenAPI 生成物,不改变任何运行时行为。
"""

from drf_spectacular.extensions import OpenApiAuthenticationExtension


class SessionJwtAuthenticationScheme(OpenApiAuthenticationExtension):
    """把 ``SessionJwtAuthentication`` 映射成 OpenAPI 的 HTTP Bearer 方案。"""

    target_class = "accounts.authentication.SessionJwtAuthentication"
    name = "bearerAuth"

    def get_security_definition(self, auto_schema):
        """返回 ``components.securitySchemes`` 中的认证方案定义。

        Args:
            auto_schema: drf-spectacular 传入的当前 ``AutoSchema`` 实例(本实现未使用)。

        Returns:
            OpenAPI 3.0 的 securityScheme 字典。
        """
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
