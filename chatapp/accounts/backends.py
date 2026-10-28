"""认证后端:后台登录失败锁定(账号 + IP 双维度)。

设计要点:
    1. 复用 Django 的 ``ModelBackend``,只在其前后加计数,不改密码校验逻辑;
    2. 账号维度防「盯着一个账号爆破」,IP 维度防「换账号撞库」;
    3. 达到上限后**直接返回 None**(与密码错误表现一致,不泄漏锁定状态),
       锁定时间 ``OPS_LOGIN_LOCK_SECONDS`` 到期自动恢复;
    4. 登录成功清空账号维度的计数;IP 维度保留到自然过期,避免同一出口继续撞库。
"""

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.core.cache import cache

from config.net import client_ip


class ThrottledModelBackend(ModelBackend):
    """带失败锁定的认证后端。"""

    def authenticate(self, request, username=None, password=None, **kwargs):
        """认证并在失败时累计锁定计数。

        Args:
            request: 当前请求,用于取 IP;可能为 ``None``。
            username: 登录标识(本项目是手机号)。
            password: 密码明文。
            **kwargs: 透传给父类。

        Returns:
            认证成功的用户;失败、被锁定或参数缺失时返回 ``None``。
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

        Args:
            key: 缓存键。

        Returns:
            达到上限返回 ``True``。
        """
        return int(cache.get(key, 0) or 0) >= int(settings.OPS_LOGIN_MAX_ATTEMPTS)

    def _bump(self, key: str) -> None:
        """失败计数 +1;首次失败时设置锁定窗口。

        Args:
            key: 缓存键。
        """
        ttl = int(settings.OPS_LOGIN_LOCK_SECONDS)
        if not cache.add(key, 1, ttl):
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, ttl)
