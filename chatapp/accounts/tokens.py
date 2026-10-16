"""JWT 令牌:在标准令牌上带一个会话版本(session_version)claim。

设计要点:
    单设备登录的数据源 —— 登录时 ``User.session_version += 1`` 并写进令牌;
    鉴权与刷新时比对令牌里的版本与数据库当前值,不一致即表示已被新设备顶下线。
"""

from rest_framework_simplejwt.tokens import AccessToken, RefreshToken


class SessionAccessToken(AccessToken):
    """带会话版本的访问令牌。"""

    @classmethod
    def for_user(cls, user):
        """为指定用户签发访问令牌。

        Args:
            user: 目标用户。

        Returns:
            写入了 ``session_version`` claim 的访问令牌。
        """
        token = super().for_user(user)
        token["session_version"] = user.session_version
        return token


class SessionRefreshToken(RefreshToken):
    """带会话版本的刷新令牌;由它换发出的 access 同样是会话版本令牌。"""

    access_token_class = SessionAccessToken

    @classmethod
    def for_user(cls, user):
        """为指定用户签发刷新令牌。

        Args:
            user: 目标用户。

        Returns:
            写入了 ``session_version`` claim 的刷新令牌。
        """
        token = super().for_user(user)
        token["session_version"] = user.session_version
        return token
