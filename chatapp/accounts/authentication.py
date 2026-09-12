"""自定义 JWT 鉴权:在标准校验之外,再核对「会话版本」。

令牌签发后用户又在别的设备登录(session_version 变了)→ 本令牌作废,
返回 401 + code=40101(带专门的中文提示),前端据此强退到登录页。
"""

from rest_framework_simplejwt.authentication import JWTAuthentication

from .exceptions import SingleDeviceSessionConflict
from .models import SESSION_VERSION_DEFAULT


class SessionJwtAuthentication(JWTAuthentication):
    def get_user(self, validated_token):
        user = super().get_user(validated_token)
        # 兼容没有该 claim 的历史令牌(等同于初始版本);正式签发的令牌都带它
        token_version = validated_token.get("session_version", SESSION_VERSION_DEFAULT)
        if token_version != user.session_version:
            raise SingleDeviceSessionConflict()
        return user
