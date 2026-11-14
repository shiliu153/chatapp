"""短信接口的限流:发码与校验各自按客户端 IP 计数。

设计要点:
    额度配在 ``settings.DEFAULT_THROTTLE_RATES``,且 ``DEBUG`` 下会放宽 ——
    两台模拟器共享宿主机的 ``127.0.0.1``,不放宽会互相把对方限流掉。

文件信息:
    文件名称          accounts/throttles.py
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


class SmsSendThrottle(SimpleRateThrottle):
    """按 IP 限流发送验证码;额度在 settings.DEFAULT_THROTTLE_RATES["sms_send"]。

    参数说明:
        无(无参构造,实例由 DRF 按视图 ``throttle_classes`` 创建)。

    返回参数:
        限流器实例;``allow_request`` 返回 ``False`` 时视图直接回 429。

    使用示例:
        ``SmsSendThrottle()``

    备注信息:
        本类只决定「按什么身份计数」—— 这里固定按客户端 IP;额度与 ``DEBUG``
        放宽逻辑全部配在 settings,改额度不需要动代码。
    """

    scope = "sms_send"

    def get_cache_key(self, request, view):
        """按客户端 IP 生成限流缓存键。

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该 IP 在 ``sms_send`` 作用域下的缓存键。

        使用示例:
            ``self.get_cache_key(request, view)``

        备注信息:
            键格式取 ``SimpleRateThrottle.cache_format``,``ident`` 用 ``get_ident``
            (即客户端 IP);不区分手机号,同一出口的所有号码共用一个额度。
        """
        # SimpleRateThrottle 要求必须自己实现缓存键;这里按客户端 IP 计数
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class SmsVerifyThrottle(SimpleRateThrottle):
    """按 IP 限流校验验证码(防扫号);额度在 settings.DEFAULT_THROTTLE_RATES["sms_verify"]。

    参数说明:
        无(无参构造,实例由 DRF 按视图 ``throttle_classes`` 创建)。

    返回参数:
        限流器实例;``allow_request`` 返回 ``False`` 时视图直接回 429。

    使用示例:
        ``SmsVerifyThrottle()``

    备注信息:
        校验接口匿名可用,按 IP 计数用于防扫号;命中与否都计入额度 —— 计数发生在
        视图执行前,不存在「错了才计数」的分支。
    """

    scope = "sms_verify"

    def get_cache_key(self, request, view):
        """按客户端 IP 生成限流缓存键。

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该 IP 在 ``sms_verify`` 作用域下的缓存键。

        使用示例:
            ``self.get_cache_key(request, view)``

        备注信息:
            与发码限流分开计数(作用域不同),因此「发得太快」不会连带把校验也限掉。
        """
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class ProbeThrottle(SimpleRateThrottle):
    """按 IP 限流探针;额度在 settings.DEFAULT_THROTTLE_RATES["probe"](L1)。

    参数说明:
        无(无参构造,实例由 DRF 按视图 ``throttle_classes`` 创建)。

    返回参数:
        限流器实例;``allow_request`` 返回 ``False`` 时视图直接回 429。

    使用示例:
        ``ProbeThrottle()``

    备注信息:
        作用域 ``probe`` 是独立额度,与短信两条链路互不影响;按 IP 计数,
        因此同一出口的多个探针客户端共享额度。
    """

    scope = "probe"

    def get_cache_key(self, request, view):
        """按客户端 IP 生成限流缓存键。

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该 IP 在 ``probe`` 作用域下的缓存键。

        使用示例:
            ``self.get_cache_key(request, view)``

        备注信息:
            键里带作用域,与 ``sms_send`` / ``sms_verify`` / ``logout`` 的计数完全隔离。
        """
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}


class LogoutThrottle(SimpleRateThrottle):
    """按 IP 限流注销;额度在 settings.DEFAULT_THROTTLE_RATES["logout"](L-5)。

    注销本身是幂等的,但它是匿名接口且会写 token 黑名单表,必须限流防止被刷。

    参数说明:
        无(无参构造,实例由 DRF 按视图 ``throttle_classes`` 创建)。

    返回参数:
        限流器实例;``allow_request`` 返回 ``False`` 时视图直接回 429。

    使用示例:
        ``LogoutThrottle()``

    备注信息:
        按 IP 计数、不区分账号 —— 注销请求可能带的是已失效的令牌,拿不到可靠身份;
        额度只在请求进入视图前扣减,与注销是否真的写库无关。
    """

    scope = "logout"

    def get_cache_key(self, request, view):
        """按客户端 IP 生成限流缓存键。

        参数说明:
            request: 当前请求。
            view: 当前视图;DRF 接口要求,此处未使用。

        返回参数:
            该 IP 在 ``logout`` 作用域下的缓存键。

        使用示例:
            ``self.get_cache_key(request, view)``

        备注信息:
            作用域 ``logout`` 独立计数;「全端下线」与单端注销共用这一份额度。
        """
        return self.cache_format % {"scope": self.scope, "ident": self.get_ident(request)}
