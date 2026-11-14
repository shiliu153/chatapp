"""JWT 令牌:在标准令牌上带会话版本(session_version)与端类型(ct)两个 claim。

设计要点:
    多端在线的数据源 —— 登录时只把**本端**的会话版本 +1
    (``accounts.device_session.bump``),并把它与端类型一起写进令牌;
    鉴权与刷新时用令牌自带的 ``ct`` 回查该端的当前版本,不一致即表示已被顶下线。

    ``ct`` 是端类型(``app`` / ``web``),**鉴权按它回查端会话**,不看请求头 ——
    头只在签发时用来决定写哪一端(见 ``accounts.device_session``)。

文件信息:
    文件名称          accounts/tokens.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from .device_session import CLIENT_APP, current_version


class SessionAccessToken(AccessToken):
    """带会话版本与端类型的访问令牌。

    参数说明:
        token: 可选的原始 JWT 字符串或令牌实例，默认 ``None`` 表示新建空令牌；
            传入时按 ``verify`` 决定是否先校验。
        verify: 是否校验令牌的有效期与类型，默认 ``True``；鉴权环节保持默认即可。

    返回参数:
        构造出的是令牌实例，不是字符串；要取字面量用 ``str(token)``。

    使用示例:
        ``token = SessionAccessToken.for_user(user, "web")``

    备注信息:
        claim 由 :meth:`for_user` 写入：``session_version`` 取签发那一刻该端的版本
        (``current_version``，没有端会话行时回落历史列)，``ct`` 记端类型。
        鉴权用它回查该端当前版本，不一致即视为被同端新登录顶下线，返回 401 + ``40101``。
    """

    @classmethod
    def for_user(cls, user, client_type=CLIENT_APP):
        """为指定用户签发访问令牌。

        参数说明:
            user: 目标用户。
            client_type: ``"app"`` 或 ``"web"``,决定写哪一端的会话版本。

        返回参数:
            写入了 ``session_version`` 与 ``ct`` claim 的访问令牌(实例，非字符串)。

        使用示例:
            ``token = SessionAccessToken.for_user(user, "app")``

        备注信息:
            只读版本、**不递增**——递增发生在登录路径(``device_session.bump``)。
            返回值通常交给 DRF 序列化为字符串返回给客户端。
        """
        token = super().for_user(user)
        token["session_version"] = current_version(user, client_type)
        token["ct"] = client_type
        return token


class SessionRefreshToken(RefreshToken):
    """带会话版本与端类型的刷新令牌;由它换发出的 access 同样是会话版本令牌。

    参数说明:
        token: 可选的原始 JWT 字符串或令牌实例，默认 ``None`` 表示新建空令牌；
            传入时按 ``verify`` 决定是否先校验。
        verify: 是否校验令牌的有效期与类型，默认 ``True``。

    返回参数:
        构造出的是令牌实例，不是字符串；要取字面量用 ``str(token)``。

    使用示例:
        ``refresh = SessionRefreshToken.for_user(user, "web")``

    备注信息:
        ``access_token_class`` 指向 :class:`SessionAccessToken`，所以刷新换发出来的
        access 自动带上 ``session_version`` 与 ``ct``，刷新链路无需手工补 claim。
        校验传入的刷新令牌用 ``SessionRefreshToken(raw)`` 形式（见 ``accounts.views``）。
    """

    access_token_class = SessionAccessToken

    @classmethod
    def for_user(cls, user, client_type=CLIENT_APP):
        """为指定用户签发刷新令牌。

        参数说明:
            user: 目标用户。
            client_type: ``"app"`` 或 ``"web"``,决定写哪一端的会话版本。

        返回参数:
            写入了 ``session_version`` 与 ``ct`` claim 的刷新令牌(实例，非字符串)。

        使用示例:
            ``refresh = SessionRefreshToken.for_user(user, "web")``

        备注信息:
            只读版本、**不递增**。刷新即轮换，旧刷新令牌由 simplejwt 黑名单机制作废
            (``SessionRefreshToken(raw).blacklist()``)。
        """
        token = super().for_user(user)
        token["session_version"] = current_version(user, client_type)
        token["ct"] = client_type
        return token
