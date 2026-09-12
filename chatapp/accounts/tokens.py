"""JWT 令牌:在标准令牌上带一个会话版本(session_version)claim。

单设备登录的数据源:登录时 `User.session_version += 1` 并写进令牌;
鉴权/刷新时比对令牌里的版本与数据库当前值,不一致 = 已被新设备顶下线。
"""

from rest_framework_simplejwt.tokens import AccessToken, RefreshToken


class SessionAccessToken(AccessToken):
    @classmethod
    def for_user(cls, user):
        token = super().for_user(user)
        token["session_version"] = user.session_version
        return token


class SessionRefreshToken(RefreshToken):
    access_token_class = SessionAccessToken

    @classmethod
    def for_user(cls, user):
        token = super().for_user(user)
        token["session_version"] = user.session_version
        return token
