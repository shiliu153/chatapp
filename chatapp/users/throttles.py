"""资料相关接口的限流。

照片上传、他人资料卡、在线状态与资料语音(批次 R)都按账号计数,额度统一配在
``settings.DEFAULT_THROTTLE_RATES`` 里;在线状态的额度说明见
``settings.PRESENCE_RATE``(一个前台页面约每小时轮询 80 次)。
"""

from rest_framework.throttling import SimpleRateThrottle

from config.throttling import UserScopedThrottle


class PhotoUploadThrottle(UserScopedThrottle):
    """按用户限流照片上传;额度见 ``settings.DEFAULT_THROTTLE_RATES["upload_photo"]``。"""

    scope = "upload_photo"


class PublicProfileThrottle(UserScopedThrottle):
    """按用户限流他人资料卡;额度见 ``settings.DEFAULT_THROTTLE_RATES["public_profile"]``。"""

    scope = "public_profile"


class ProfileVoiceThrottle(UserScopedThrottle):
    """按用户限流资料语音上传/删除;额度见 ``settings.PROFILE_VOICE_RATE``。

    上传与删除共用一个计数桶:两者都是「改资料」动作,额度(默认 10 次/小时)
    对正常用户(录一次 + 一两次替换)足够,对脚本则够紧。
    """

    scope = "profile_voice"


class PresenceThrottle(SimpleRateThrottle):
    """按用户限流在线状态查询;额度在 settings.DEFAULT_THROTTLE_RATES["presence"]。"""

    scope = "presence"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        与短信接口按 IP 限流不同:在线状态是登录后才会调用的接口,
        按用户计数比按 IP 更准确(同一出口 IP 可能有多台设备)。

        Args:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        Returns:
            该用户在 ``presence`` 作用域下的缓存键。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
