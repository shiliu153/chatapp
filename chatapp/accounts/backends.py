"""认证后端:后台登录失败锁定(账号 + IP 双维度)。

设计要点:
    1. 复用 Django 的 ``ModelBackend``,只在其前后加计数,不改密码校验逻辑;
    2. 账号维度防「盯着一个账号爆破」,IP 维度防「换账号撞库」;
    3. 达到上限后**直接返回 None**(与密码错误表现一致,不泄漏锁定状态),
       锁定时间 ``OPS_LOGIN_LOCK_SECONDS`` 到期自动恢复;
    4. 登录成功清空账号维度的计数;IP 维度保留到自然过期,避免同一出口继续撞库。

文件信息:
    文件名称          accounts/backends.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.cache import cache

from config.net import client_ip


class ThrottledModelBackend(ModelBackend):
    """带失败锁定的认证后端。

    参数说明:
        无(无参构造,``ModelBackend`` 不接收构造参数)。

    返回参数:
        认证后端实例,由 Django 按 ``AUTHENTICATION_BACKENDS`` 配置创建。

    使用示例:
        ``ThrottledModelBackend().authenticate(request, username=phone, password=raw)``

    备注信息:
        只覆写 ``authenticate`` 与两个私有计数方法,密码校验、权限方法一律走父类;
        计数阈值与窗口读 ``OPS_LOGIN_MAX_ATTEMPTS`` / ``OPS_LOGIN_LOCK_SECONDS``,
        缓存后端故障时 ``cache`` 调用抛出的异常不在此处捕获。
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        """认证并在失败时累计锁定计数。

        参数说明:
            request: 当前请求,用于取 IP;可能为 ``None``。
            username: 登录标识(本项目是手机号)。
            password: 密码明文。
            **kwargs: 透传给父类。

        返回参数:
            认证成功的用户;失败、被锁定或参数缺失时返回 ``None``。

        使用示例:
            ``backend.authenticate(request, username="13800138000", password=raw)``

        备注信息:
            账号维度与 IP 维度任一达到上限都直接返回 ``None``,与密码错误的表现一致,
            不泄漏锁定状态;失败时两个维度都 +1,成功只清账号维度 —— IP 维度保留到
            自然过期,避免同一出口继续撞库。``request`` 为 ``None`` 时 ``client_ip``
            返回空串,该次调用会与其它无请求调用共用同一个 IP 计数键。
        """
        if username is None:
            username = kwargs.get(get_user_model().USERNAME_FIELD)
        if username is None or password is None:
            return None

        account_key = f"ops:login:fail:account:{username}"
        ip_key = f"ops:login:fail:ip:{client_ip(request)}"
        if self._locked(account_key) or self._locked(ip_key):
            return None

        user = super().authenticate(request, username=username, password=password, **kwargs)
        if user is None:
            self._bump(account_key)
            self._bump(ip_key)
            return None
        cache.delete(account_key)
        return user

    def _locked(self, key: str) -> bool:
        """判断某个维度是否已达到失败上限。

        参数说明:
            key: 缓存键。

        返回参数:
            达到上限返回 ``True``。

        使用示例:
            ``self._locked("ops:login:fail:account:13800138000")``

        备注信息:
            计数缺省按 0 处理,因此从未失败过的维度一定不锁;阈值每次现读设置,
            便于测试里用 ``override_settings`` 改小。
        """
        return int(cache.get(key, 0) or 0) >= int(settings.OPS_LOGIN_MAX_ATTEMPTS)

    def _bump(self, key: str) -> None:
        """失败计数 +1;首次失败时设置锁定窗口。

        参数说明:
            key: 缓存键。

        返回参数:
            无返回值。

        使用示例:
            ``self._bump("ops:login:fail:ip:127.0.0.1")``

        备注信息:
            首次失败用 ``cache.add`` 建键并设 ``OPS_LOGIN_LOCK_SECONDS`` 窗口,之后
            ``cache.incr``;键已过期或值类型不对时 ``incr`` 抛 ``ValueError``,
            回退为重新 ``set`` 计数 1,窗口从此刻重新计时。
        """
        ttl = int(settings.OPS_LOGIN_LOCK_SECONDS)
        if not cache.add(key, 1, ttl):
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, ttl)
