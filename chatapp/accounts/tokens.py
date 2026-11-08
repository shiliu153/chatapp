"""JWT 令牌:在标准令牌上带会话版本(session_version)与端类型(ct)两个 claim。

设计要点:
    多端在线的数据源 —— 登录时只把**本端**的会话版本 +1
    (``accounts.device_session.bump``),并把它与端类型一起写进令牌;
    鉴权与刷新时用令牌自带的 ``ct`` 回查该端的当前版本,不一致即表示已被顶下线。

    ``ct`` 是端类型(``app`` / ``web``),**鉴权按它回查端会话**,不看请求头 ——
    头只在签发时用来决定写哪一端(见 ``accounts.device_session``)。
"""

from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from .device_session import CLIENT_APP, current_version


class SessionAccessToken(AccessToken):
    """带会话版本与端类型的访问令牌。"""

    @classmethod
    def for_user(cls, user, client_type=CLIENT_APP):
        """为指定用户签发访问令牌。

        Args:
            user: 目标用户。
            client_type: ``"app"`` 或 ``"web"``,决定写哪一端的会话版本。

        Returns:
            写入了 ``session_version`` 与 ``ct`` claim 的访问令牌。
        """
        token = super().for_user(user)
        token["session_version"] = current_version(user, client_type)
        token["ct"] = client_type
        return token


class SessionRefreshToken(RefreshToken):
    """带会话版本与端类型的刷新令牌;由它换发出的 access 同样是会话版本令牌。"""

    access_token_class = SessionAccessToken

    @classmethod
    def for_user(cls, user, client_type=CLIENT_APP):
        """为指定用户签发刷新令牌。

        Args:
            user: 目标用户。
            client_type: ``"app"`` 或 ``"web"``,决定写哪一端的会话版本。

        Returns:
            写入了 ``session_version`` 与 ``ct`` claim 的刷新令牌。
        """
        token = super().for_user(user)
        token["session_version"] = current_version(user, client_type)
        token["ct"] = client_type
        return token
