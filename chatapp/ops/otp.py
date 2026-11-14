"""运营后台的第二因子(TOTP)页面。

设计要点:
    1. 首次进入且未绑定密钥时,自动生成一个待确认密钥放进 session,页面显示
       secret 与 ``otpauth://`` 地址;用户输入 App 上的 6 位码确认后才写入数据库
       (避免「生成了但没绑成功」导致下次登录被锁);
    2. 已绑定时只显示验证码输入框;
    3. 每个用户 5 分钟内最多尝试 10 次,防止在线爆破 6 位码。

文件信息:
    文件名称          ops/otp.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
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

    参数说明:
        request: Django 请求对象(原地写 session)。

    返回参数:
        无返回值。

    使用示例:
        ``mark_verified(request)``

    备注信息:
        只写 ``otp_verified_at``(秒级 Unix 时间戳),有效期的判定完全交给
        ``is_verified`` 现算,不在写入时定死过期时间;同时清掉旧版本 session 里的布尔
        标记 ``otp_verified``,避免升级后残留标记被误读。
    """
    request.session["otp_verified_at"] = int(time.time())
    request.session.pop("otp_verified", None)   # 清掉旧版本的布尔标记


def is_verified(request) -> bool:
    """判断当前 session 的第二因子是否仍在有效期内(M-6)。

    没有时间戳(旧版本 session 或从未验证)一律视为未验证,强制重验一次。

    参数说明:
        request: Django 请求对象。

    返回参数:
        在 ``OPS_OTP_TTL`` 内验证过返回 ``True``,否则 ``False``。

    使用示例:
        ``is_verified(request)``

    备注信息:
        时间戳不是整数(脏 session)时同样返回 ``False``,不向上抛;``OPS_OTP_TTL``
        默认 12 小时,每次现读设置,便于测试用 ``override_settings`` 改小。调用方是
        ``StaffSecurityMiddleware``,它拿这个结果决定是否把运营账号跳到 ``/ops/otp/``。
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

    备注信息:
        按账号 id 计,键形如 ``ops:otp:attempt:<user_id>``,不掺 IP —— 换出口 IP 也
        绕不过次数上限;缓存后端是 Redis,键的 TTL 由 ``_bump_attempt`` 设置。
    """
    return f"ops:otp:attempt:{user_id}"


def _too_many_attempts(user_id: int) -> bool:
    """判断是否已超过 OTP 尝试次数。

    备注信息:
        计数缺失或非数字时按 0 处理(``cache.get`` 兜底为 0),因此从未失败过的账号一定
        不超限;阈值取模块常量 ``OTP_ATTEMPT_LIMIT``(10 次),超限时调用方返回 429。
    """
    return int(cache.get(_attempt_key(user_id), 0) or 0) >= OTP_ATTEMPT_LIMIT


def _bump_attempt(user_id: int) -> None:
    """OTP 失败计数 +1。

    备注信息:
        首次失败用 ``cache.add`` 建键并设 ``OTP_ATTEMPT_TTL``(300 秒)窗口,之后
        ``cache.incr``;键刚好过期或值类型不对时 ``incr`` 抛 ``ValueError``,回退为重新
        ``set`` 计数 1,窗口从此刻重新计时。只有失败才计数,验证通过时由
        ``otp_verify`` 直接删键清零。
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

    参数说明:
        request: Django 请求对象;POST 带 ``code`` 与可选 ``next``。

    返回参数:
        GET 渲染验证页;POST 成功跳回 ``next``(或举报列表),失败回显错误。

    使用示例:
        ``client.post("/ops/otp/", {"code": "123456", "next": "/ops/reports/"})``

    备注信息:
        已通过且在 ``OPS_OTP_TTL`` 内(session 里时间戳仍有效)直接跳过页面,避免刷新
        重复输入。首次进入(``user.totp_secret`` 为空)时生成待确认密钥放 session,页面
        显示 secret 与 ``otpauth://`` 地址;只有验证码正确才把密钥写进
        ``User.totp_secret``,避免「生成了但没绑成功」导致下次登录被锁。失败计数按账号在
        Redis 里累计,达 ``OTP_ATTEMPT_LIMIT``(10 次 / ``OTP_ATTEMPT_TTL`` 300 秒)
        后直接渲染 429,不再校验验证码;验证通过时清计数并 ``mark_verified``。
        本页本身受 ``StaffSecurityMiddleware`` 豁免(否则会无限重定向),但
        ``OPS_ALLOWED_IPS`` 的 IP 白名单在豁免之前判断,后台登录页同样不放给公网;
        ``OPS_OTP_REQUIRED=1``(生产默认)时该中间件才强制运营账号来这里过第二因子。
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

    备注信息:
        两套判据:``ALLOWED_HOSTS`` 去掉空串与 ``*`` 后非空时按
        ``url_has_allowed_host_and_scheme`` 校验主机;去掉后为空时只接受以单个 ``/``
        开头的相对路径(``//host`` 这类协议相对地址仍然被挡)。``next`` 为空或校验不过时
        一律回举报列表 ``ops:reports``,不回显错误。
    """
    allowed_hosts = {host for host in settings.ALLOWED_HOSTS if host and host != "*"}
    if next_url:
        if allowed_hosts and url_has_allowed_host_and_scheme(
                next_url, allowed_hosts=allowed_hosts):
            return redirect(next_url)
        if not allowed_hosts and next_url.startswith("/") and not next_url.startswith("//"):
            return redirect(next_url)
    return redirect(reverse("ops:reports"))
