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

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该用户在 ``chat_image`` 作用域下的缓存键。

        使用示例:
            DRF 每次限流检查时调用 ``throttle.get_cache_key(request, view)``(见 ``config/throttling.py`` 的 ``UserScopedThrottle``)

        备注信息:
            键里的 ``ident`` 恒为 ``request.user.id``;额度由 ``chat_image`` 作用域读取。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}


class ChatVoiceThrottle(SimpleRateThrottle):
    """按用户限流聊天语音上传;额度在 settings.DEFAULT_THROTTLE_RATES["chat_voice"]。"""

    scope = "chat_voice"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该用户在 ``chat_voice`` 作用域下的缓存键。

        使用示例:
            DRF 每次限流检查时调用 ``throttle.get_cache_key(request, view)``(见 ``config/throttling.py`` 的 ``UserScopedThrottle``)

        备注信息:
            键里的 ``ident`` 恒为 ``request.user.id``;额度由 ``chat_voice`` 作用域读取。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
