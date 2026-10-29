"""运营后台的第二因子(TOTP)页面。

设计要点:
    1. 首次进入且未绑定密钥时,自动生成一个待确认密钥放进 session,页面显示
       secret 与 ``otpauth://`` 地址;用户输入 App 上的 6 位码确认后才写入数据库
       (避免「生成了但没绑成功」导致下次登录被锁);
    2. 已绑定时只显示验证码输入框;
    3. 每个用户 5 分钟内最多尝试 10 次,防止在线爆破 6 位码。
"""

import logging
import time

from django.conf import settings
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from accounts import totp

from .decorators import staff_required

logger = logging.getLogger(__name__)

OTP_ATTEMPT_LIMIT = 10
OTP_ATTEMPT_TTL = 300


def mark_verified(request) -> None:
    """记录「第二因子已通过」的时间戳。

    Args:
        request: Django 请求对象(原地写 session)。
    """
    request.session["otp_verified_at"] = int(time.time())
    request.session.pop("otp_verified", None)   # 清掉旧版本的布尔标记


def is_verified(request) -> bool:
    """判断当前 session 的第二因子是否仍在有效期内(M-6)。

    没有时间戳(旧版本 session 或从未验证)一律视为未验证,强制重验一次。

    Args:
        request: Django 请求对象。

    Returns:
        在 ``OPS_OTP_TTL`` 内验证过返回 ``True``。
    """
    raw = request.session.get("otp_verified_at")
    if raw is None:
        return False
    try:
        verified_at = int(raw)
    except (TypeError, ValueError):
        return False
    return int(time.time()) - verified_at < int(settings.OPS_OTP_TTL)


def _attempt_key(user_id: int) -> str:
    """OTP 尝试次数的缓存键。

    Args:
        user_id: 账号 id。

    Returns:
        缓存键字符串。
    """
    return f"ops:otp:attempt:{user_id}"


def _too_many_attempts(user_id: int) -> bool:
    """判断是否已超过 OTP 尝试次数。

    Args:
        user_id: 账号 id。

    Returns:
        超过上限返回 ``True``。
    """
    return int(cache.get(_attempt_key(user_id), 0) or 0) >= OTP_ATTEMPT_LIMIT


def _bump_attempt(user_id: int) -> None:
    """OTP 失败计数 +1。

    Args:
        user_id: 账号 id。
    """
    key = _attempt_key(user_id)
    if not cache.add(key, 1, OTP_ATTEMPT_TTL):
        try:
            cache.incr(key)
        except ValueError:
            cache.set(key, 1, OTP_ATTEMPT_TTL)


@staff_required
def otp_verify(request):
    """第二因子验证/绑定页(GET/POST /ops/otp/)。

    Args:
        request: Django 请求对象;POST 带 ``code`` 与可选 ``next``。

    Returns:
        GET 渲染验证页;POST 成功跳回 ``next``(或举报列表),失败回显错误。
    """
    user = request.user
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    if is_verified(request):
        return _safe_redirect(next_url)

    if _too_many_attempts(user.id):
        return render(request, "ops/otp.html", {
            "error": "尝试次数过多,请 5 分钟后再试", "secret": "", "uri": "",
            "next": next_url, "setup": False,
        }, status=429)

    setup = not bool(user.totp_secret)
    secret = user.totp_secret
    if setup:
        secret = request.session.get("otp_pending_secret") or totp.generate_secret()
        request.session["otp_pending_secret"] = secret

    error = ""
    if request.method == "POST":
        code = request.POST.get("code", "")
        if totp.verify(secret, code):
            if setup:
                user.totp_secret = secret
                user.save(update_fields=["totp_secret"])
            request.session.pop("otp_pending_secret", None)
            mark_verified(request)
            cache.delete(_attempt_key(user.id))
            return _safe_redirect(next_url)
        _bump_attempt(user.id)
        error = "验证码不正确,请重新输入"

    return render(request, "ops/otp.html", {
        "error": error,
        "secret": secret if setup else "",
        "uri": totp.provisioning_uri(secret, user.phone) if setup else "",
        "next": next_url,
        "setup": setup,
    })


def _safe_redirect(next_url: str):
    """只允许站内跳转,防止开放重定向。

    ``ALLOWED_HOSTS`` 为空时 ``url_has_allowed_host_and_scheme`` 会放开任意主机,
    因此这种情况退化为「只允许站内相对路径」(L-6)。

    Args:
        next_url: 用户提交的下一跳地址。

    Returns:
        站内地址的 302;``next`` 为空或站外时回到举报列表。
    """
    allowed_hosts = {host for host in settings.ALLOWED_HOSTS if host and host != "*"}
    if next_url:
        if allowed_hosts and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts=allowed_hosts):
            return redirect(next_url)
        if not allowed_hosts and next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
    return redirect(reverse("ops:reports"))
