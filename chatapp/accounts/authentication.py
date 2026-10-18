"""自定义 JWT 鉴权:在标准校验之外,再核对「会话版本」。

设计要点:
    令牌签发后用户又在别的设备登录时,``session_version`` 会被 +1,本令牌随即作废,
    返回 401 + code=40101(带专门的中文提示),前端据此强退到登录页。

注意事项:
    本类是全项目 DRF 侧唯一的认证入口(见 ``settings.REST_FRAMEWORK``)。认证通过时
    顺带刷新在线状态,因此「在线」由认证请求驱动,不需要独立的在线心跳接口。
"""

from rest_framework_simplejwt.authentication import JWTAuthentication

from users.presence import touch

from .exceptions import SingleDeviceSessionConflict
from .models import SESSION_VERSION_DEFAULT


class SessionJwtAuthentication(JWTAuthentication):
    """带会话版本校验的 JWT 认证。"""

    def get_user(self, validated_token):
        """校验令牌的会话版本并取出用户。

        Args:
            validated_token: 已通过签名与有效期校验的 JWT。

        Returns:
            令牌对应的用户实例。

        Raises:
            SingleDeviceSessionConflict: 令牌版本与数据库当前版本不一致,
                即账号已在其他设备登录。
        """
        user = super().get_user(validated_token)
        # 兼容没有该 claim 的历史令牌(等同于初始版本);正式签发的令牌都带它
        token_version = validated_token.get("session_version", SESSION_VERSION_DEFAULT)
        if token_version != user.session_version:
            raise SingleDeviceSessionConflict()
        touch(user.id)   # 认证通过即刷新「最后活跃」;失败静默(内部兜底)
        return user
