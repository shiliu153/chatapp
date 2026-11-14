"""IM 接口的限流:聊天图片与语音上传。

文件信息:
    文件名称          im/throttles.py
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


class UserSigThrottle(UserScopedThrottle):
    """按用户限流 IM 凭证签发;额度见 ``settings.DEFAULT_THROTTLE_RATES["user_sig"]``。

    参数说明:
        无(DRF 在视图初始化时无参实例化)。

    返回参数:
        限流器实例。

    使用示例:
        ``@throttle_classes([UserSigThrottle])``

    备注信息:
        缓存键与额度读取都在基类 ``config.throttling.UserScopedThrottle``,本类只声明
        ``scope``;超限按统一错误契约返回 429。
    """

    scope = "user_sig"


class ChatImageThrottle(SimpleRateThrottle):
    """按用户限流聊天图片上传;额度在 settings.DEFAULT_THROTTLE_RATES["chat_image"]。

    参数说明:
        无(DRF 在视图初始化时无参实例化)。

    返回参数:
        限流器实例。

    使用示例:
        ``@throttle_classes([ChatImageThrottle])``

    备注信息:
        直接继承 DRF ``SimpleRateThrottle`` 并自行实现 ``get_cache_key``,不走
        ``UserScopedThrottle``;计数维度是用户 id,未登录请求由鉴权层先挡掉。
    """

    scope = "chat_image"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该用户在 ``chat_image`` 作用域下的缓存键。

        使用示例:
            ``self.get_cache_key(request, view)``

        备注信息:
            键格式来自 DRF 的 ``cache_format``;``request.user.id`` 为 ``None``(匿名)
            时会生成含 ``None`` 的键,实际由鉴权层提前拒绝。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}


class ChatVoiceThrottle(SimpleRateThrottle):
    """按用户限流聊天语音上传;额度在 settings.DEFAULT_THROTTLE_RATES["chat_voice"]。

    参数说明:
        无(DRF 在视图初始化时无参实例化)。

    返回参数:
        限流器实例。

    使用示例:
        ``@throttle_classes([ChatVoiceThrottle])``

    备注信息:
        语音上传要跑 ffmpeg 转码,是 IM 侧最贵的同步路径,额度按单账号控制;计数维度
        是用户 id,与图片上传分开计。
    """

    scope = "chat_voice"

    def get_cache_key(self, request, view):
        """按用户 id 生成限流缓存键。

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该用户在 ``chat_voice`` 作用域下的缓存键。

        使用示例:
            ``self.get_cache_key(request, view)``

        备注信息:
            键格式来自 DRF 的 ``cache_format``;与 ``ChatImageThrottle`` 共用实现,只有
            ``scope`` 不同。
        """
        return self.cache_format % {"scope": self.scope, "ident": request.user.id}
