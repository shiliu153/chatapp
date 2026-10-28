"""IM 接口的限流:聊天图片与语音上传。"""

from rest_framework.throttling import SimpleRateThrottle

from config.throttling import UserScopedThrottle


class UserSigThrottle(UserScopedThrottle):
    """按用户限流 IM 凭证签发;额度见 ``settings.DEFAULT_THROTTLE_RATES["user_sig"]``。"""

    scope = "user_sig"


class ChatImageThrottle(SimpleRateThrottle):
    """按用户限流聊天图片上传;额度在 settings.DEFAULT_THROTTLE_RATES["chat_image"]。"""

    scope = "chat_image"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该用户在 ``chat_image`` 作用域下的缓存键。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}


class ChatVoiceThrottle(SimpleRateThrottle):
    """按用户限流聊天语音上传;额度在 settings.DEFAULT_THROTTLE_RATES["chat_voice"]。"""

    scope = "chat_voice"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该用户在 ``chat_voice`` 作用域下的缓存键。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
