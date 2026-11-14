"""自定义 JWT 鉴权:在标准校验之外,再核对「该端」的会话版本。

设计要点:
    令牌签发后用户又在**同一类端**上登录时,该端的 ``DeviceSession.version`` 会被
    +1,本令牌随即作废,返回 401 + code=40101(带专门的中文提示),前端据此强退到
    登录页。**另一端不受影响** —— 一个 App + 一个网页可以同时在线(批次 K)。

    判端只看**令牌里的 ``ct`` claim**,不看请求头:头缺失或被伪造会让端判定漂移,
    例如 Web 某处漏带 ``X-Client`` 就会被当成 App,把真 App 顶掉。

注意事项:
    本类是全项目 DRF 侧唯一的认证入口(见 ``settings.REST_FRAMEWORK``)。认证通过时
    顺带刷新在线状态,因此「在线」由认证请求驱动,不需要独立的在线心跳接口。

文件信息:
    文件名称          accounts/authentication.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from rest_framework_simplejwt.authentication import JWTAuthentication

from users.presence import touch

from .device_session import client_type_of_token, current_version, legacy_token_version
from .exceptions import SingleDeviceSessionConflict


class SessionJwtAuthentication(JWTAuthentication):
    """带会话版本校验的 JWT 认证(按端)。

    参数说明:
        无(未自定义 ``__init__``,沿用 DRF ``JWTAuthentication`` 的构造)。

    返回参数:
        认证器实例本身;DRF 通过 ``authenticate()`` 调用它并取回 ``(user, token)``。

    使用示例:
        ``"DEFAULT_AUTHENTICATION_CLASSES": ["accounts.authentication.SessionJwtAuthentication"]``

    备注信息:
        只重写 ``get_user``:签名与有效期校验仍走 DRF 原实现,额外比对令牌里的 ``ct``
        claim 所指那一端的 ``DeviceSession.version``;不一致返回 401 + code=40101。
    """

    def get_user(self, validated_token):
        """校验令牌在**本端**的会话版本并取出用户。

        参数说明:
            validated_token: 已通过签名与有效期校验的 JWT。

        返回参数:
            令牌对应的用户实例。

        使用示例:
            ``SessionJwtAuthentication().get_user(validated_token)``

        备注信息:
            令牌版本与该端的当前版本不一致时抛 ``SingleDeviceSessionConflict``
            (401 + code=40101),即账号已在同类端的其他设备登录。老令牌没有 ``ct``
            claim 时按 ``app`` 兜底(等价于升级前的行为,见 ``client_type_of_token``)。
            认证通过即调用 ``users.presence.touch`` 刷新「最后活跃」,失败静默。
        """
        user = super().get_user(validated_token)
        # 老令牌没有 ct claim → 按 app 兜底(等价于升级前的行为)
        client_type = client_type_of_token(validated_token)
        if legacy_token_version(validated_token) != current_version(user, client_type):
            raise SingleDeviceSessionConflict()
        touch(user.id)   # 认证通过即刷新「最后活跃」;失败静默(内部兜底)
        return user
