"""资料相关接口的限流。

照片上传、他人资料卡、在线状态与资料语音(批次 R)都按账号计数,额度统一配在
``settings.DEFAULT_THROTTLE_RATES`` 里;在线状态的额度说明见
``settings.PRESENCE_RATE``(一个前台页面约每小时轮询 80 次)。

文件信息:
    文件名称          users/throttles.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from rest_framework.throttling import SimpleRateThrottle

from config.throttling import UserScopedThrottle


class PhotoUploadThrottle(UserScopedThrottle):
    """按用户限流照片上传;额度见 ``settings.DEFAULT_THROTTLE_RATES["upload_photo"]``。

    参数说明:
        DRF 按 ``Throttle()`` 无参构造,额度从缓存/设置里按 ``scope`` 读取。

    返回参数:
        供 ``@throttle_classes`` 使用的限流实例。

    使用示例:
        ``@throttle_classes([PhotoUploadThrottle])``

    备注信息:
        只挂在 ``users.views.upload_photo`` 上;超限由 DRF 统一回 429(错误契约在同处统一)。
    """

    scope = "upload_photo"


class PublicProfileThrottle(UserScopedThrottle):
    """按用户限流他人资料卡;额度见 ``settings.DEFAULT_THROTTLE_RATES["public_profile"]``。

    参数说明:
        DRF 按 ``Throttle()`` 无参构造,额度从缓存/设置里按 ``scope`` 读取。

    返回参数:
        供 ``@throttle_classes`` 使用的限流实例。

    使用示例:
        ``@throttle_classes([PublicProfileThrottle])``

    备注信息:
        与 ``users.services.record_profile_view`` 的抓取广度告警互补:限流负责挡住,
        告警负责发现(两者窗口不同)。
    """

    scope = "public_profile"


class ProfileVoiceThrottle(UserScopedThrottle):
    """按用户限流资料语音上传/删除;额度见 ``settings.PROFILE_VOICE_RATE``。

    上传与删除共用一个计数桶:两者都是「改资料」动作,额度(默认 10 次/小时)
    对正常用户(录一次 + 一两次替换)足够,对脚本则够紧。

    参数说明:
        DRF 按 ``Throttle()`` 无参构造,额度从缓存/设置里按 ``scope`` 读取。

    返回参数:
        供 ``@throttle_classes`` 使用的限流实例。

    使用示例:
        ``@throttle_classes([ProfileVoiceThrottle])``

    备注信息:
        POST 与 DELETE 共用 ``scope``,所以删除也吃同一份额度;
        额度值配在 ``PROFILE_VOICE_RATE`` 而不是 ``DEFAULT_THROTTLE_RATES``。
    """

    scope = "profile_voice"


class PresenceThrottle(SimpleRateThrottle):
    """按用户限流在线状态查询;额度在 settings.DEFAULT_THROTTLE_RATES["presence"]。

    参数说明:
        DRF 按 ``Throttle()`` 无参构造,额度从缓存/设置里按 ``scope`` 读取。

    返回参数:
        供 ``@throttle_classes`` 使用的限流实例。

    使用示例:
        ``@throttle_classes([PresenceThrottle])``

    备注信息:
        故意不用 ``UserScopedThrottle``:缓存键在这里自定义(见 ``get_cache_key``),
        只按用户 id 计数。
    """

    scope = "presence"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        与短信接口按 IP 限流不同:在线状态是登录后才会调用的接口,
        按用户计数比按 IP 更准确(同一出口 IP 可能有多台设备)。

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该用户在 ``presence`` 作用域下的缓存键。

        使用示例:
            ``throttle.get_cache_key(request, view)``

        备注信息:
            假定请求已通过认证(``request.user.id`` 必有值) —— 该接口在全局鉴权之后,
            未登录请求到不了这里。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
