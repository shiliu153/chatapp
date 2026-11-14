"""运营审核台:举报处理、照片审核、用户管理、封禁日志、广场治理、运营看板与准入名单。

设计要点:
    1. **用 Django 模板 + HTMX 局部刷新,不用 DRF**:审核台是内部工具,追求开发速度。
       全部接口挂在 ``/ops/`` 前缀下,**不在** ``/api/v1`` 内,因此不受
       ``ApiDocsCoverageTests`` 的接口文档门禁约束;
    2. **鉴权靠 ``@staff_required`` 装饰器**:未登录跳登录页,非 ``is_staff`` 直接 403;
    3. **封禁与解封统一走 ``_apply_status_change``**:审计与 IM 通知都复用
       ``moderation.services.log_ban_change``,与 Django admin 完全同源;
    4. **准入名单(B-1c)是安全边界的操作台**:本项目不接短信商,名单内 = 自己人,
       因此加号/停用都要留操作人;写路径必须调 ``accounts.allowlist.invalidate()``,
       否则 App/Web 侧还要等快照 TTL 才生效。每次加号/启停还要在同一个事务里写一条
       ``PhoneAllowlistEvent``(R4-B2):``is_active`` 只存当前状态,历史只能靠流水;
    5. **运营看板是只读页**:数据全部来自 ``stats.DailyMetric`` 快照表(``metrics_daily``
       每天写一行),页面不写任何表、不查 IM 库、不算实时指标 —— 实时归 Prometheus。
       配对率与近 7 日汇总在视图里算好再进上下文,模板里不做除法。

注意事项:
    解封时必须先把状态改回 ``INCOMPLETE`` 再调 ``refresh_status()`` ——
    封禁态不参与完善度重算,不先脱离封禁态就永远算不回真实状态。

文件信息:
    文件名称          ops/views.py
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
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts import allowlist as allowlist_module
from accounts.models import (PhoneAllowlist, PhoneAllowlistAction,
                             PhoneAllowlistEvent, User)
from accounts.validators import mask_phone
from config.net import client_ip
from config.params import optional_id
from discovery.cache_keys import invalidate_pool_globally
from feed.models import Post, PostReport
from feed.services import delete_post
from feedback.models import Feedback, FeedbackStatus, FeedbackType
from im.models import ChatImage, ChatImageStatus, ChatVoice, ChatVoiceStatus
from moderation.models import (BanAction, BanLog, Block, Report, ReportStatus,
                               ReportType)
from moderation.services import log_ban_change, notify_report_handled
from stats import metrics as stats_metrics
from users.models import Photo, PhotoStatus, Profile, ProfileStatus
from users.services import review_photos

from .decorators import staff_required
from .forms import PhoneAllowlistForm
from .models import MediaAccessLog

logger = logging.getLogger(__name__)

# 与举报详情页的证据窗口保持一致:最近 7 天被举报过的人,其聊天媒体优先进入视野。
MEDIA_REPORT_WINDOW_DAYS = 7

# 准入名单一页最多展示多少条;名单总量是几十到几百的量级,不做分页。
ALLOWLIST_PAGE_SIZE = 200

# 「最近操作」表最多展示多少条流水;审计才是全量查询,页面只要扫一眼最近发生过什么。
ALLOWLIST_EVENT_LIMIT = 20

# 运营看板趋势表取多少行、顶部数字卡的「近 N 日」窗口。两个数字写死在这里 ——
# 「近 30 天」「近 7 日」是口径不是可调参数,别让视图与模板各说一套。
METRICS_TREND_DAYS = 30
METRICS_SUMMARY_DAYS = 7


def _reported_user_ids(days: int = MEDIA_REPORT_WINDOW_DAYS) -> set[int]:
    """取最近 ``days`` 天被举报过的用户 id 集合。

    备注信息:
        ``days`` 默认取 ``MEDIA_REPORT_WINDOW_DAYS``(7 天),与举报详情页的证据窗口
        一致;只取 ``target_id``,重复的 id 由 ``set`` 去重,调用方直接放进
        ``owner_id__in`` 过滤。窗口内没人被举报时返回空集,此时按 reported 过滤会
        得到空列表而不是全量。
    """
    return set(Report.objects.filter(
        created_at__gte=timezone.now() - timedelta(days=days),
    ).values_list("target_id", flat=True))


def _log_media_access(request, kind: str, filter_name: str, count: int) -> None:
    """记录一次私聊媒体列表浏览;审计写失败只告警,绝不影响页面。

    备注信息:
        ``kind`` 取 ``MediaAccessLog.Kind`` 的 image / voice,``filter_name`` 取
        all / reported / user;``staff`` 取当前登录账号(未登录存 NULL),
        ``ip`` 取 ``client_ip(request)``,取不到时存 NULL。``MediaAccessLog`` 写库异常
        被吞掉只记一条 warning —— 抽审页不能因为审计表写不进去就 500。
    """
    try:
        MediaAccessLog.objects.create(
            staff=request.user if request.user.is_authenticated else None,
            kind=kind,
            filter=filter_name,
            count=count,
            ip=client_ip(request) or None,
        )
    except Exception:
        logger.warning("媒体访问审计写入失败", exc_info=True)



@staff_required
def home(request):
    """审核台首页:直接跳到举报列表。(/ops/)

    参数说明:
        无(只接收 Django 自动注入的 ``request``)。

    返回参数:
        指向举报列表的 302 重定向响应。

    使用示例:
        ``client.get("/ops/")``

    备注信息:
        首页不留空壳,登录后第一屏就是待处理举报;重定向目标 ``ops:reports``
        (``/ops/reports/``)由 ``@staff_required`` 保证只有运营账号能进来。

        整个 ``/ops/`` 与 ``/admin/`` 还受 ``ops.middleware.StaffSecurityMiddleware``
        保护:``OPS_ALLOWED_IPS`` 非空时不在白名单内的 IP 一律 403(登录页也走这条判断);
        ``OPS_OTP_REQUIRED=1``(生产默认)时运营账号必须先过 ``/ops/otp/`` 的 TOTP 第二
        因子。登录失败达 ``OPS_LOGIN_MAX_ATTEMPTS``(默认 5 次)后按账号与 IP 双维度锁
        ``OPS_LOGIN_LOCK_SECONDS``(默认 900 秒,即 15 分钟),锁定期间返回 ``None``,
        表现与密码错误一致,不泄漏锁定状态。
    """
    return redirect("ops:reports")


@staff_required
def reports_list(request):
    """举报列表页,支持按状态与类型过滤。(/ops/reports/)

    参数说明:
        request: Django 请求对象,支持 ``status`` 与 ``type`` 查询参数。

    返回参数:
        渲染后的举报列表页;最多展示 200 条。

    使用示例:
        ``client.get("/ops/reports/?status=pending&type=harassment")``

    备注信息:
        ``status`` 默认 ``pending``,``type`` 默认空;取值不在枚举内时忽略该条件而不是
        报错。排序 ``-status`` 是字符串降序,让 pending 排在 handled 之前(与 Django
        admin 审核台同款),同一状态内按 ``-created_at``;硬截断 200 条,不做分页。
    """
    status = request.GET.get("status", ReportStatus.PENDING)
    rtype = request.GET.get("type", "")
    qs = (Report.objects.select_related("reporter__profile", "target__profile")
          .annotate(target_report_count=Count("target__reports_received", distinct=True)))
    if status in ReportStatus.values:
        qs = qs.filter(status=status)
    if rtype in ReportType.values:
        qs = qs.filter(type=rtype)
    # -status:字符串降序让 "pending" 排在 "handled" 前(与 admin 审核台同款)
    qs = qs.order_by("-status", "-created_at")[:200]
    return render(request, "ops/reports_list.html", {
        "reports": qs, "status": status, "rtype": rtype, "types": ReportType.choices,
    })


@staff_required
def report_detail(request, report_id):
    """举报详情页(含举报人与被举报人的历史记录)。(/ops/reports/<int:report_id>/)

    参数说明:
        request: Django 请求对象。
        report_id: 举报主键,不存在时 404。

    返回参数:
        渲染后的举报详情页。

    使用示例:
        ``client.get("/ops/reports/12/")``

    备注信息:
        上下文全部由 ``_report_context`` 拼,HTMX 封禁/处理的局部刷新复用同一份,
        保证整页与局部显示一致。
    """
    report = get_object_or_404(
        Report.objects.select_related("reporter", "target", "handled_by"), pk=report_id)
    return render(request, "ops/report_detail.html", _report_context(report))


def _report_context(report):
    """拼举报详情页的上下文(含双方各自的历史举报与封禁记录)。

    备注信息:
        举报详情里直接给证据:被举报人最近 7 天的聊天图片与语音各取 12 条 —— 图片无
        机器审核、语音不做转写,全部靠运营人工看与听。双方各自的历史举报各取 10 条并
        排除当前这条;``getattr(..., "profile", None)`` 兜住资料行还没建出来的账号,
        模板按 ``None`` 渲染。
    """
    return {
        "report": report,
        "reporter_profile": getattr(report.reporter, "profile", None),
        "target_profile": getattr(report.target, "profile", None),
        "reporter_reports": Report.objects.filter(reporter=report.reporter)
                                           .exclude(pk=report.pk)[:10],
        "target_reports": Report.objects.filter(target=report.target)
                                        .exclude(pk=report.pk)[:10],
        "target_ban_logs": BanLog.objects.filter(user=report.target)[:10],
        # 举报详情里直接给证据:被举报人最近 7 天的聊天图片(图片无机器审核,靠人工抽审)
        "chat_images": ChatImage.objects.select_related("owner").filter(
            owner=report.target,
            created_at__gte=timezone.now() - timedelta(days=7),
        ).order_by("-created_at")[:12],
        # 语音同理:可直接试听,不做转写
        "chat_voices": ChatVoice.objects.select_related("owner").filter(
            owner=report.target,
            created_at__gte=timezone.now() - timedelta(days=7),
        ).order_by("-created_at")[:12],
    }


def _apply_status_change(user, action, reason, operator):
    """把封禁/解封动作落到资料上,并记录审计与 IM 通知。

    备注信息:
        ``action`` 取 ``ban_light`` / ``ban_heavy`` / ``unban``;封禁把资料状态改成
        ``BANNED_LIGHT`` / ``BANNED_HEAVY`` 并把 ``reason`` 截断到 200 字写进
        ``ban_reason``,解封清空 ``ban_reason`` 且忽略 ``reason``。审计与踢 IM 统一走
        ``moderation.services.log_ban_change``,与 Django admin 完全同源。解封必须先把
        状态置回 ``INCOMPLETE`` 再调 ``refresh_status()`` —— 封禁态不参与完善度重算,
        不先脱离封禁态就永远算不回真实状态。资料行不存在时 ``get_or_create`` 补一行。
    """
    profile, _ = Profile.objects.get_or_create(user=user)
    old_status = profile.status
    if action == "unban":
        profile.ban_reason = ""
        profile.status = ProfileStatus.INCOMPLETE
        profile.save(update_fields=["status", "ban_reason"])
        profile.refresh_status()   # 回到 complete/incomplete(封禁态不参与重算,必须先在非封禁态)
    else:
        profile.status = (ProfileStatus.BANNED_LIGHT if action == "ban_light"
                          else ProfileStatus.BANNED_HEAVY)
        profile.ban_reason = reason[:200]
        profile.save(update_fields=["status", "ban_reason"])
    log_ban_change(user, old_status, profile.status, reason[:200], operator)
    return profile


@require_POST
@staff_required
def report_handle(request, report_id):
    """把举报标记为已处理,并通知举报者。(/ops/reports/<int:report_id>/handle)

    参数说明:
        request: Django 请求对象,POST 可带 ``note`` 作为处理备注(截断 200 字)。
        report_id: 举报主键,不存在时 404。

    返回参数:
        举报面板的局部片段 ``ops/partials/report_panel.html``。

    使用示例:
        ``client.post("/ops/reports/12/handle", {"note": "已警告对方"})``

    备注信息:
        只处理 ``PENDING`` 状态的举报:已是 handled 的重复提交既不改写处理人/备注,
        也不重复通知。``notify_report_handled`` 走 Celery(``on_commit`` 入队)给举报者
        发 IM 灰条 + 站内通知,响应路径内不直接发网络请求。
    """
    report = get_object_or_404(Report, pk=report_id)
    if report.status == ReportStatus.PENDING:
        report.status = ReportStatus.HANDLED
        report.handled_note = request.POST.get("note", "").strip()[:200]
        report.handled_by = request.user
        report.handled_at = timezone.now()
        report.save(update_fields=["status", "handled_note", "handled_by", "handled_at"])
        notify_report_handled(report)
    return render(request, "ops/partials/report_panel.html",
                  {"report": report, "error": None})


@require_POST
@staff_required
def report_ban(request, report_id):
    """从举报详情页直接封禁被举报人,并把该举报一并标记为已处理。(/ops/reports/<int:report_id>/ban)

    参数说明:
        request: Django 请求对象,POST 需带 ``level``(``ban_light`` / ``ban_heavy``)
            与 ``reason``。
        report_id: 举报主键,不存在时 404。

    返回参数:
        举报面板的局部片段,``error`` 字段回显校验失败原因。

    使用示例:
        ``client.post("/ops/reports/12/ban", {"level": "ban_heavy", "reason": "涉黄"})``

    备注信息:
        级别非法或原因为空时只回显错误,不改变任何状态;封禁落库与审计走
        ``_apply_status_change``。封禁成功后若举报仍是 pending,一并标 handled、备注
        写「封禁处理」并通知举报者,避免留下已经失效的待办。
    """
    report = get_object_or_404(Report.objects.select_related("target"), pk=report_id)
    level = request.POST.get("level")
    reason = request.POST.get("reason", "").strip()
    error = None
    if level not in ("ban_light", "ban_heavy"):
        error = "未知的封禁级别"
    elif not reason:
        error = "封禁必须填写原因"
    if error is None:
        _apply_status_change(report.target, level, reason, request.user)
        if report.status == ReportStatus.PENDING:
            report.status = ReportStatus.HANDLED
            report.handled_note = "封禁处理"
            report.handled_by = request.user
            report.handled_at = timezone.now()
            report.save(update_fields=["status", "handled_note", "handled_by", "handled_at"])
            notify_report_handled(report)
    return render(request, "ops/partials/report_panel.html",
                  {"report": report, "error": error})


@staff_required
def photos(request):
    """照片审核列表页,默认展示待审核。(/ops/photos/)

    参数说明:
        request: Django 请求对象,支持 ``status`` 查询参数。

    返回参数:
        渲染后的照片网格页;最多展示 120 张。

    使用示例:
        ``client.get("/ops/photos/?status=pending")``

    备注信息:
        这个队列里有没有东西由 ``AUTO_APPROVE`` 决定:生产默认 0(先审后发),新照片落
        ``pending`` 只能在这里审;``DEBUG`` / 测试默认 1(自动过审),队列通常为空。
        ``status`` 不在 ``PhotoStatus`` 取值内时不过滤;``skipped`` 初值恒为 0,只有
        批量接口 ``photo_review`` 才会写非零值。
    """
    status = request.GET.get("status", PhotoStatus.PENDING)
    qs = Photo.objects.select_related("user", "reviewed_by").order_by("-created_at")
    if status in PhotoStatus.values:
        qs = qs.filter(status=status)
    return render(request, "ops/photos.html",
                  {"photos": qs[:120], "status": status, "skipped": 0})


@require_POST
@staff_required
def photo_review(request):
    """批量通过或驳回所选照片,并回吐刷新后的照片网格。(/ops/photos/review)

    参数说明:
        request: Django 请求对象,POST 需带 ``ids``(多值)、``action``
            (``approve`` / ``reject``)与可选 ``status``。

    返回参数:
        照片网格的局部片段,``skipped`` 为页面陈旧、照片已被删除的条数。

    使用示例:
        ``client.post("/ops/photos/review", {"ids": ["3", "4"], "action": "approve"})``

    备注信息:
        ``ids`` 逐条人工解析:非数字一律丢弃 —— ``pk__in`` 求值时会抛 ``ValueError``
        (500),且不能用 ``str.isdigit()`` 过滤(``"²".isdigit()`` 为真但 ``int()`` 会
        抛);``<= 0`` 同样丢弃,一次最多审 500 张,避免超大表单打库。任何状态都可再审
        (已通过可撤回驳回);``skipped`` 与照片总数之差只统计已不存在的 id。过审/驳回
        直接决定谁能进候选池,因此必须 ``invalidate_pool_globally()`` 让全站候选池缓存
        失效。``action`` 不在映射内或 ``ids`` 为空时不动库,只回吐当前列表。
    """
    ids = set()
    for value in request.POST.getlist("ids"):
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            # 非数字一律丢弃:``pk__in`` 求值时会抛 ValueError(500)。
            # 注意不能用 ``str.isdigit()`` 过滤 —— "²".isdigit() 为真但 int() 会抛(M-7)。
            continue
        if parsed > 0:
            ids.add(parsed)
    ids = set(sorted(ids)[:500])   # 一次最多审 500 张,避免超大表单打库
    action = request.POST.get("action")
    status_map = {"approve": PhotoStatus.APPROVED, "reject": PhotoStatus.REJECTED}
    skipped = 0
    if action in status_map and ids:
        # 任何状态都可再审(已通过可撤回驳回);skipped 只统计页面陈旧、照片已被删除的 id
        targets = Photo.objects.filter(pk__in=ids)
        skipped = len(ids) - targets.count()
        review_photos(targets, status_map[action], request.user)
        # 过审/驳回直接决定谁能进候选池,必须让全站候选池缓存失效。
        invalidate_pool_globally()
    status = request.POST.get("status", PhotoStatus.PENDING)
    qs = Photo.objects.select_related("user", "reviewed_by").order_by("-created_at")
    if status in PhotoStatus.values:
        qs = qs.filter(status=status)
    return render(request, "ops/partials/photo_grid.html",
                  {"photos": qs[:120], "status": status, "skipped": skipped})


@staff_required
def users_search(request):
    """按手机号精确匹配或昵称模糊匹配搜索用户。(/ops/users/)

    参数说明:
        request: Django 请求对象,支持 ``q`` 查询参数。

    返回参数:
        渲染后的搜索结果页;``q`` 为空时不返回任何结果。

    使用示例:
        ``client.get("/ops/users/?q=13800138000")``

    备注信息:
        手机号走 ``phone=q`` 精确匹配、昵称走 ``nickname__icontains`` 模糊匹配,两者是
        OR 关系,结果按 ``id`` 升序截断 50 条。手机号不在本页脱敏 —— 这个页面的用途
        就是按号码找人。
    """
    q = request.GET.get("q", "").strip()
    results = []
    if q:
        results = (User.objects.filter(Q(phone=q) | Q(profile__nickname__icontains=q))
                   .select_related("profile").order_by("id")[:50])
    return render(request, "ops/users_search.html", {"q": q, "results": results})


@staff_required
def user_detail(request, user_id):
    """用户详情页(资料、封禁记录、举报与拉黑关系)。(/ops/users/<int:user_id>/)

    参数说明:
        request: Django 请求对象。
        user_id: 目标账号 id,不存在时 404。

    返回参数:
        渲染后的用户详情页。

    使用示例:
        ``client.get("/ops/users/42/")``

    备注信息:
        账号 id 取自 ``users.id``(不是 profile 主键);上下文由 ``_user_context`` 拼,
        HTMX 封禁局部刷新复用同一份。
    """
    user = get_object_or_404(User.objects.select_related("profile"), pk=user_id)
    return render(request, "ops/user_detail.html", _user_context(user))


def _user_context(user):
    """拼用户详情页的上下文(封禁记录、收到的/发出的举报、拉黑关系)。

    备注信息:
        六类关联记录各取 20 条上限:封禁日志带操作人、收到的举报带举报人、发出的举报
        带被举报人、发出与收到的拉黑各带对端账号;``target_profile`` 用
        ``getattr(user, "profile", None)`` 兜住没有资料行的账号,模板按 ``None`` 渲染。
    """
    return {
        "target_user": user,
        "target_profile": getattr(user, "profile", None),
        "ban_logs": BanLog.objects.filter(user=user).select_related("operator")[:20],
        "reports_received": Report.objects.filter(target=user).select_related("reporter")[:20],
        "reports_made": Report.objects.filter(reporter=user).select_related("target")[:20],
        "blocks_made": Block.objects.filter(blocker=user).select_related("blocked")[:20],
        "blocks_received": Block.objects.filter(blocked=user).select_related("blocker")[:20],
    }


@require_POST
@staff_required
def user_ban(request, user_id):
    """从用户详情页执行封禁或解封。(/ops/users/<int:user_id>/ban)

    参数说明:
        request: Django 请求对象,POST 需带 ``action``
            (``ban_light`` / ``ban_heavy`` / ``unban``)与封禁时的 ``reason``。
        user_id: 目标账号 id,不存在时 404。

    返回参数:
        封禁面板的局部片段 ``ops/partials/user_ban_panel.html``,``error`` 字段回显
        校验失败原因。

    使用示例:
        ``client.post("/ops/users/42/ban", {"action": "ban_light", "reason": "骚扰"})``

    备注信息:
        解封不需要原因,封禁原因必填;未知 ``action`` 回显「未知操作」且不改任何状态。
        无论成功失败都重新拼一份 ``_user_context`` 回吐,保证局部刷新后的面板与实库
        一致。
    """
    user = get_object_or_404(User, pk=user_id)
    action = request.POST.get("action")
    reason = request.POST.get("reason", "").strip()
    error = None
    if action == "unban":
        _apply_status_change(user, action, reason, request.user)
    elif action in ("ban_light", "ban_heavy"):
        if not reason:
            error = "封禁必须填写原因"
        else:
            _apply_status_change(user, action, reason, request.user)
    else:
        error = "未知操作"
    ctx = _user_context(user)
    ctx["error"] = error
    return render(request, "ops/partials/user_ban_panel.html", ctx)


def _rate(numerator: int, denominator: int) -> float | None:
    """算一个比值,分母为 0 时返回 ``None``。

    备注信息:
        ``None`` 与 ``0.0`` 语义不同:前者是「没采到 / 无法计算」,模板渲染 ``—``;
        后者是「真的是 0%」。分子分母都由调用方现算,本函数不查库。
    """
    if not denominator:
        return None
    return numerator / denominator


def _format_rate(rate: float | None) -> str | None:
    """把配对率格式化成百分比文本。

    备注信息:
        格式化放在这里而不是模板:模板只做展示,不做除法,也不做数字格式化。
        ``rate`` 为 ``None`` 时原样返回,由模板渲染 ``—``;保留一位小数,如 ``"40.0%"``。
    """
    if rate is None:
        return None
    return f"{rate * 100:.1f}%"


def _metrics_summary(window: list) -> dict:
    """把「近 7 日」窗口内的快照汇总成顶部数字卡要的数字。

    口径(与 ``docs/ops/runbook.md`` §9 一致):
        1. 配对率 = ``Σmatches / Σswipes_like``,分母为 0 时留空;
        2. 日均 DAU 只在**采到 DAU 的天**上平均 —— 当天没采到不参与平均,
           否则会把「没采到」当成「0 人」拉低均值;
        3. 消息量按天求和,一天都没采到则留空(采到了 0 条算 0,不算空)。

    备注信息:
        ``window`` 是窗口内的快照行列表,可以只有几天也可以为空;``start`` / ``end``
        取窗口首尾日期(``window`` 按日期倒序传入,``end`` 是 ``window[0]``)。采不到的
        聚合值一律 ``None``,由模板渲染 ``—``。
    """
    daus = [row.dau for row in window if row.dau is not None]
    messages = [row.messages for row in window if row.messages is not None]
    return {
        "days": len(window),
        "start": window[-1].date if window else None,
        "end": window[0].date if window else None,
        "new_users": sum(row.new_users for row in window),
        "avg_dau": f"{sum(daus) / len(daus):.1f}" if daus else None,
        "match_rate": _format_rate(_rate(
            sum(row.matches for row in window),
            sum(row.swipes_like for row in window),
        )),
        "messages": sum(messages) if messages else None,
    }


def _metrics_trend(rows: list) -> list:
    """把快照行整理成模板可以直接渲染的行(配对率在这里算好)。

    备注信息:
        ``rows`` 来自 ``stats.metrics.recent_rows``(一条 SQL、按日期倒序);缺失值保持
        ``None``,由模板 ``default_if_none`` 渲染 ``—``。配对率复用
        ``stats.metrics.match_rate(row)``,与单日口径同一份实现(分母为 0 返回
        ``None``),再经 ``_format_rate`` 转成 ``"40.0%"`` 文本。
    """
    return [{
        "date": row.date,
        "dau": row.dau,
        "new_users": row.new_users,
        "profiles_completed": row.profiles_completed,
        "swipes_like": row.swipes_like,
        "swipes_pass": row.swipes_pass,
        "matches": row.matches,
        "match_rate": _format_rate(stats_metrics.match_rate(row)),
        "messages": row.messages,
        "retention_d1": row.retention_d1,
        "retention_d7": row.retention_d7,
    } for row in rows]


def _hour_bars(row) -> list:
    """把一行的 24 个小时桶算成横条(宽度百分比在这里算好,模板只贴 ``width``)。

    备注信息:
        只取 ``active_hours`` 的前 24 个桶,``pct`` 是相对当日最高峰的百分比(CSS 横条
        宽度),当日无人活跃时全是 0。``row`` 为 ``None``、``active_hours`` 不是列表或为
        空时返回空列表 —— 看板不能因为一行的时段分布是脏数据就整页 500。
    """
    if row is None or not isinstance(row.active_hours, list) or not row.active_hours:
        return []
    counts = row.active_hours[:24]
    peak = max(counts) if counts else 0
    return [{
        "hour": f"{hour:02d}",
        "count": count,
        "pct": round(count / peak * 100, 1) if peak else 0,
    } for hour, count in enumerate(counts)]


@staff_required
def metrics(request):
    """运营看板:昨日数字卡、近 30 天趋势表与活跃时段。(/ops/metrics/)

    数据全部来自 V-1 写好并由 ``manage.py metrics_daily`` 每天写入的
    ``stats.DailyMetric`` 快照表 —— 本页**只读**:一条 SQL 取 30 行
    (``stats.metrics.recent_rows``),汇总、配对率、时段横条宽度全在这份内存列表上算,
    模板里不做除法。缺失值(``None``)由模板渲染成 ``—``,与「采到了 0」严格区分。

    参数说明:
        request: Django 请求对象。

    返回参数:
        渲染后的看板页;快照表为空时同样返回 200(页面给「还没有数据」提示,不抛异常)。

    使用示例:
        ``client.get("/ops/metrics/")``

    备注信息:
        「昨日」「近 7 日」「近 30 天」三个窗口都从这份列表上切,窗口长度取
        ``METRICS_TREND_DAYS`` / ``METRICS_SUMMARY_DAYS``;活跃时段用最近一行**真的
        采到**小时分布的快照,最新那行 ``active_hours`` 为空(当天 Redis 没记录)时退到
        前一天,比显示「暂无数据」更有用。页面不写任何表、不查 IM 库、不算实时指标。
    """
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)
    # 一条 SQL 取完趋势表要用的行,后面所有计算都在这份内存列表上做(不在循环里查库)。
    rows = stats_metrics.recent_rows(METRICS_TREND_DAYS)
    yesterday_row = next((row for row in rows if row.date == yesterday), None)
    window_start = yesterday - timedelta(days=METRICS_SUMMARY_DAYS - 1)
    window = [row for row in rows if window_start <= row.date <= yesterday]
    # 活跃时段用「最近一行**真的采到**小时分布的快照」:最新那行的 active_hours 可能是
    # 空的(当天 Redis 没记录),退到前一天比显示「暂无数据」更有用。
    activity_row = next((row for row in rows if row.active_hours), None)
    return render(request, "ops/metrics.html", {
        "rows": _metrics_trend(rows),
        "summary": _metrics_summary(window),
        "latest": rows[0] if rows else None,
        "hour_bars": _hour_bars(activity_row),
        "activity_date": activity_row.date if activity_row else None,
        "today": today,
        "yesterday": yesterday,
        "yesterday_dau": yesterday_row.dau if yesterday_row else None,
        "yesterday_new_users": yesterday_row.new_users if yesterday_row else None,
    })


@staff_required
def logs(request):
    """封禁审计与拉黑记录查询页。(/ops/logs/)

    参数说明:
        request: Django 请求对象,支持 ``action`` / ``phone`` / ``date`` 过滤。

    返回参数:
        渲染后的日志页;封禁日志最多 200 条、拉黑记录最多 100 条。

    使用示例:
        ``client.get("/ops/logs/?action=ban_heavy&phone=13800138000")``

    备注信息:
        三个过滤条件互相独立、可叠加:``action`` 不在 ``BanAction`` 取值内时不过滤,
        ``phone`` 精确匹配账号手机号,``date`` 按自然日过滤。``date`` 解析失败
        (``created_at__date`` 求值抛 ``ValidationError``)时清空该条件继续出页面,不回
        500。拉黑记录只读、不提供解绑入口。
    """
    action = request.GET.get("action", "")
    phone = request.GET.get("phone", "").strip()
    date = request.GET.get("date", "").strip()
    qs = BanLog.objects.select_related("user", "operator").order_by("-created_at")
    if action in BanAction.values:
        qs = qs.filter(action=action)
    if phone:
        qs = qs.filter(user__phone=phone)
    if date:
        try:
            qs = qs.filter(created_at__date=date)
        except ValidationError:
            date = ""
    blocks = Block.objects.select_related("blocker", "blocked").order_by("-created_at")[:100]
    return render(request, "ops/logs.html", {
        "ban_logs": qs[:200], "blocks": blocks,
        "action": action, "phone": phone, "date": date,
        "actions": BanAction.choices,
    })


def _posts_queryset():
    """审核台用的动态查询集(带赞/评数注解,按发布时间倒序,最多 200 条)。

    备注信息:
        赞数与评论数用 ``Count(..., distinct=True)`` 注解,避免多表 JOIN 时重复计数;
        ``select_related("author__profile")`` 与 ``prefetch_related("images")`` 把列表页
        的查询数压到常量级;按 ``-created_at, -id`` 排序,同一秒发布的动态顺序也稳定。
    """
    return (Post.objects.select_related("author__profile")
            .prefetch_related("images")
            .annotate(like_count=Count("likes", distinct=True),
                      comment_count=Count("comments", distinct=True))
            .order_by("-created_at", "-id")[:200])


@staff_required
def posts(request):
    """动态治理列表页。(/ops/posts/)

    参数说明:
        request: Django 请求对象。

    返回参数:
        渲染后的动态列表页。

    使用示例:
        ``client.get("/ops/posts/")``

    备注信息:
        列表数据来自 ``_posts_queryset``,与删除后的局部刷新同一份查询,整页与局部口径
        一致;本页只读,删除走 ``post_delete``。
    """
    return render(request, "ops/posts.html", {"posts": _posts_queryset()})


@require_POST
@staff_required
def post_delete(request, post_id):
    """运营删除一条动态,并回吐刷新后的动态表格。(/ops/posts/<int:post_id>/delete)

    参数说明:
        request: Django 请求对象。
        post_id: 动态主键,不存在时 404。

    返回参数:
        动态表格的局部片段。

    使用示例:
        ``client.post("/ops/posts/88/delete")``

    备注信息:
        删除走 ``feed.services.delete_post``(作者自删与运营删除共用同一条路径):先把该
        动态全部 pending 举报标 handled 并逐个通知举报者,再删图片文件与动态行,因此
        不会在举报队列里留下悬空记录。
    """
    post = get_object_or_404(Post, pk=post_id)
    delete_post(post)
    return render(request, "ops/partials/posts_table.html", {"posts": _posts_queryset()})


def _post_reports_queryset(status):
    """按状态过滤动态举报(按状态与时间倒序,最多 200 条)。

    备注信息:
        ``status`` 不在 ``ReportStatus`` 取值内(例如 ``all``)时不过滤;``-status`` 是
        字符串降序,让 pending 排在 handled 之前,与举报列表页同款口径;同一状态内按
        ``-created_at``,最新的举报在前。
    """
    qs = (PostReport.objects.select_related("post__author__profile", "reporter", "handled_by")
          .order_by("-status", "-created_at"))
    if status in ReportStatus.values:
        qs = qs.filter(status=status)
    return qs[:200]


def _render_post_reports(request):
    """渲染动态举报表格片段,状态优先取 POST 再取 GET。

    备注信息:
        HTMX 局部刷新的 POST 里带着当前筛选,先取 POST 才能让过滤条件不跳回默认视图;
        两者都没有时退回 ``ReportStatus.PENDING``。列表与状态的取值口径都来自
        ``_post_reports_queryset``,整页与局部共用。
    """
    status = (request.POST.get("status") or request.GET.get("status")
              or ReportStatus.PENDING)
    return render(request, "ops/partials/post_reports_table.html",
                  {"reports": _post_reports_queryset(status), "status": status})


@staff_required
def post_reports(request):
    """动态举报列表页。(/ops/post-reports/)

    参数说明:
        request: Django 请求对象,支持 ``status`` 查询参数。

    返回参数:
        渲染后的动态举报页。

    使用示例:
        ``client.get("/ops/post-reports/?status=pending")``

    备注信息:
        这里的举报是广场动态专用的 ``PostReport``,与用户举报 ``Report`` 是两张表、两个
        队列,处理入口也不共用;``types`` 供模板渲染筛选下拉。
    """
    status = request.GET.get("status", ReportStatus.PENDING)
    return render(request, "ops/post_reports.html", {
        "reports": _post_reports_queryset(status), "status": status,
        "types": ReportType.choices,
    })


@require_POST
@staff_required
def post_report_handle(request, report_id):
    """把动态举报标记为已处理,并通知举报者。(/ops/post-reports/<int:report_id>/handle)

    参数说明:
        request: Django 请求对象,POST 可带 ``note`` 作为处理备注(截断 200 字)。
        report_id: 动态举报主键,不存在时 404。

    返回参数:
        动态举报表格的局部片段。

    使用示例:
        ``client.post("/ops/post-reports/7/handle", {"note": "已警告"})``

    备注信息:
        只处理 ``PENDING`` 状态的举报,重复提交不改写处理人/备注、也不重复通知;通知复用
        ``moderation.services.notify_report_handled``,由 Celery 在事务提交后发 IM 灰条与
        站内通知。
    """
    report = get_object_or_404(PostReport, pk=report_id)
    if report.status == ReportStatus.PENDING:
        report.status = ReportStatus.HANDLED
        report.handled_note = request.POST.get("note", "").strip()[:200]
        report.handled_by = request.user
        report.handled_at = timezone.now()
        report.save(update_fields=["status", "handled_note", "handled_by", "handled_at"])
        notify_report_handled(report)
    return _render_post_reports(request)


@require_POST
@staff_required
def post_report_delete_post(request, report_id):
    """删掉被举报的动态,并关闭该动态的全部待处理举报。(/ops/post-reports/<int:report_id>/delete-post)

    参数说明:
        request: Django 请求对象。
        report_id: 动态举报主键,不存在时 404。

    返回参数:
        动态举报表格的局部片段。

    使用示例:
        ``client.post("/ops/post-reports/7/delete-post")``

    备注信息:
        动态还在时调 ``feed.services.delete_post``:该动态全部 pending 举报一起标
        handled、逐个通知举报者,再删图片文件与动态行;动态已被作者删除(``post`` 置空)
        但举报还挂着时只关闭当前这条,备注写「动态已删除」。已是 handled 的举报不做任何
        改动。
    """
    report = get_object_or_404(PostReport.objects.select_related("post"), pk=report_id)
    if report.status == ReportStatus.PENDING:
        if report.post is not None:
            delete_post(report.post)   # 内部:该动态全部 pending 标 handled + 各举报者通知 + 删行
        else:
            # 动态已被作者删除(post 置空)但举报还挂着:只关闭这条
            report.status = ReportStatus.HANDLED
            report.handled_note = "动态已删除"
            report.handled_by = request.user
            report.handled_at = timezone.now()
            report.save(update_fields=["status", "handled_note", "handled_by", "handled_at"])
            notify_report_handled(report)
    return _render_post_reports(request)


def _feedback_queryset(request):
    """按筛选参数取反馈列表(列表页与 HTMX 局部共用)。

    备注信息:
        返回 ``(queryset, status, ftype)``:``queryset`` 已按 ``-created_at`` 排序并截断
        200 条,``status`` / ``ftype`` 回传给模板渲染筛选态;``status`` 或 ``type`` 不在
        枚举取值内(如 ``all``)时不加该条件。两个参数只从 GET 读,因此 POST 的局部刷新
        (``feedback_handle``)拿不到筛选条件,会退回默认的 pending 视图。
    """
    status = request.GET.get("status", FeedbackStatus.PENDING)
    ftype = request.GET.get("type", "")
    qs = Feedback.objects.select_related("user__profile", "handled_by")
    if status in FeedbackStatus.values:
        qs = qs.filter(status=status)
    if ftype in FeedbackType.values:
        qs = qs.filter(type=ftype)
    return qs.order_by("-created_at")[:200], status, ftype


@staff_required
def feedback_list(request):
    """意见反馈列表页,默认只看待处理。(/ops/feedback/)

    参数说明:
        request: Django 请求对象,支持 ``status`` 与 ``type`` 查询参数。

    返回参数:
        渲染后的反馈列表页;最多展示 200 条。

    使用示例:
        ``client.get("/ops/feedback/?status=pending&type=bug")``

    备注信息:
        筛选、排序与截断都在 ``_feedback_queryset`` 里,整页与局部片段共用同一口径;
        ``types`` 供模板渲染类型下拉。
    """
    qs, status, ftype = _feedback_queryset(request)
    return render(request, "ops/feedback.html", {
        "feedbacks": qs, "status": status, "ftype": ftype,
        "types": FeedbackType.choices,
    })


@require_POST
@staff_required
def feedback_handle(request, feedback_id):
    """把一条反馈标记为已处理。(/ops/feedback/<int:feedback_id>/handle)

    参数说明:
        request: Django 请求对象,POST 可带 ``note`` 作为处理备注(截断 200 字)。
        feedback_id: 反馈主键,不存在时 404。

    返回参数:
        反馈表格的 HTMX 局部片段。

    使用示例:
        ``client.post("/ops/feedback/5/handle", {"note": "已记录,下个版本修"})``

    备注信息:
        只处理 ``PENDING`` 的反馈:已处理的不再改写备注与处理人。反馈处理只落库,不给
        用户发通知(与举报处理不同),用户侧看不到处理进度。
    """
    feedback = get_object_or_404(Feedback, pk=feedback_id)
    if feedback.status == FeedbackStatus.PENDING:
        feedback.status = FeedbackStatus.HANDLED
        feedback.handled_note = request.POST.get("note", "").strip()[:200]
        feedback.handled_by = request.user
        feedback.handled_at = timezone.now()
        feedback.save(update_fields=["status", "handled_note", "handled_by", "handled_at"])
    qs, status, ftype = _feedback_queryset(request)
    return render(request, "ops/partials/feedback_table.html", {
        "feedbacks": qs, "status": status, "ftype": ftype,
    })

@staff_required
def chat_images(request):
    """聊天图片抽审列表,按时间倒序最多 120 条。(/ops/chat-images/)

    参数说明:
        request: Django 请求对象,支持 ``user`` 查询参数(按发送者过滤)、
            ``reported=1``(只看最近 7 天被举报过的发送者)。

    返回参数:
        渲染后的聊天图片表格页。

    使用示例:
        ``client.get("/ops/chat-images/?reported=1")``

    备注信息:
        只列 ``ChatImageStatus.VISIBLE`` 的行,已删除的不再出现;``user`` 用
        ``optional_id`` 解析,非法值与非正数按未传处理;``reported=1`` 与 ``user`` 同时
        在场时两个条件叠加。每次浏览都写一条 ``MediaAccessLog`` 审计(筛选条件与返回
        条数一起记),审计写失败只告警,不影响出页面。
    """
    qs = ChatImage.objects.select_related("owner").filter(
        status=ChatImageStatus.VISIBLE).order_by("-created_at")
    user_id = optional_id(request.GET.get("user"))
    if user_id:
        qs = qs.filter(owner_id=user_id)
    filter_name = "all"
    if request.GET.get("reported") == "1":
        qs = qs.filter(owner_id__in=_reported_user_ids())
        filter_name = "reported"
    images = list(qs[:120])
    _log_media_access(request, MediaAccessLog.Kind.IMAGE, filter_name, len(images))
    return render(request, "ops/chat_images.html",
                  {"images": images, "reported": filter_name == "reported"})


@require_POST
@staff_required
def chat_image_delete(request, image_id):
    """删除一张聊天图片:删原图与缩略图文件,行保留并记审计。(/ops/chat-images/<int:image_id>/delete)

    参数说明:
        request: Django 请求对象。
        image_id: 聊天图片主键,不存在时 404。

    返回参数:
        刷新后的表格局部片段。

    使用示例:
        ``client.post("/ops/chat-images/31/delete")``

    备注信息:
        行不物理删除:状态置 ``DELETED`` 并写 ``deleted_by`` / ``deleted_at``,保留「谁在
        什么时候删了什么」的痕迹,聊天记录里的图片因此变成已删除而不是凭空消失。
        ``file`` / ``thumb`` 为空时跳过对应文件;删文件与改状态不在同一事务,删文件抛出的
        异常不捕获。
    """
    image = get_object_or_404(ChatImage, pk=image_id)
    for field in (image.file, image.thumb):
        if field:
            default_storage.delete(field.name)
    image.status = ChatImageStatus.DELETED
    image.deleted_by = request.user
    image.deleted_at = timezone.now()
    image.save(update_fields=["status", "deleted_by", "deleted_at"])
    qs = ChatImage.objects.select_related("owner").filter(
        status=ChatImageStatus.VISIBLE).order_by("-created_at")
    return render(request, "ops/partials/chat_images_table.html", {"images": qs[:120]})


@staff_required
def chat_voices(request):
    """聊天语音抽审列表,按时间倒序最多 120 条。(/ops/chat-voices/)

    参数说明:
        request: Django 请求对象,支持 ``user`` 查询参数(按发送者过滤)、
            ``reported=1``(只看最近 7 天被举报过的发送者)。

    返回参数:
        渲染后的聊天语音表格页。

    使用示例:
        ``client.get("/ops/chat-voices/?user=42")``

    备注信息:
        只列 ``ChatVoiceStatus.VISIBLE`` 的行;语音只提供试听、不做转写,判定完全靠人工
        听。``user`` 走 ``optional_id`` 解析,``reported=1`` 与它叠加时取交集;每次浏览写
        一条 ``MediaAccessLog`` 审计,写失败只告警。
    """
    qs = ChatVoice.objects.select_related("owner").filter(
        status=ChatVoiceStatus.VISIBLE).order_by("-created_at")
    user_id = optional_id(request.GET.get("user"))
    if user_id:
        qs = qs.filter(owner_id=user_id)
    filter_name = "all"
    if request.GET.get("reported") == "1":
        qs = qs.filter(owner_id__in=_reported_user_ids())
        filter_name = "reported"
    voices = list(qs[:120])
    _log_media_access(request, MediaAccessLog.Kind.VOICE, filter_name, len(voices))
    return render(request, "ops/chat_voices.html",
                  {"voices": voices, "reported": filter_name == "reported"})


@require_POST
@staff_required
def chat_voice_delete(request, voice_id):
    """删除一条聊天语音:删文件,行保留并记审计。(/ops/chat-voices/<int:voice_id>/delete)

    参数说明:
        request: Django 请求对象。
        voice_id: 聊天语音主键,不存在时 404。

    返回参数:
        刷新后的表格局部片段。

    使用示例:
        ``client.post("/ops/chat-voices/9/delete")``

    备注信息:
        与图片删除同口径:行不物理删除,状态置 ``DELETED`` 并写 ``deleted_by`` /
        ``deleted_at``;``file`` 为空时跳过删文件,删文件的异常不捕获。
    """
    voice = get_object_or_404(ChatVoice, pk=voice_id)
    if voice.file:
        default_storage.delete(voice.file.name)
    voice.status = ChatVoiceStatus.DELETED
    voice.deleted_by = request.user
    voice.deleted_at = timezone.now()
    voice.save(update_fields=["status", "deleted_by", "deleted_at"])
    qs = ChatVoice.objects.select_related("owner").filter(
        status=ChatVoiceStatus.VISIBLE).order_by("-created_at")
    return render(request, "ops/partials/chat_voices_table.html", {"voices": qs[:120]})


def _allowlist_context(request):
    """拼准入名单页的上下文(列表、筛选、库/种子规模),整页与 HTMX 局部共用。

    备注信息:
        筛选参数 ``status``(active/disabled/all)与 ``q``(手机号或备注模糊匹配)优先取
        POST 再退回 GET —— HTMX 局部刷新的 POST 里也带着当前筛选,刷新后不会跳回默认
        视图。``registered`` 是「这些号码里哪些已经注册了账号」的集合,用来提醒运营「加了
        号还没人用过」和「这个号已经有账号了」;``events`` 是最近
        ``ALLOWLIST_EVENT_LIMIT`` 条操作流水,号码与操作人都在这里脱敏(操作人缺失时给
        ``—``);``seed_count`` 是 ``SMS_PHONE_WHITELIST`` 的种子条数,``active_total`` /
        ``disabled_total`` 是库表两侧的规模。列表按 ``-is_active, -created_at`` 排序并
        截断 ``ALLOWLIST_PAGE_SIZE`` 条,名单不做分页。
    """
    status = request.POST.get("status") or request.GET.get("status") or "active"
    q = (request.POST.get("q") or request.GET.get("q") or "").strip()
    qs = PhoneAllowlist.objects.select_related("created_by").order_by(
        "-is_active", "-created_at")
    if status == "active":
        qs = qs.filter(is_active=True)
    elif status == "disabled":
        qs = qs.filter(is_active=False)
    if q:
        qs = qs.filter(Q(phone__icontains=q) | Q(note__icontains=q))
    records = list(qs[:ALLOWLIST_PAGE_SIZE])
    registered = set(
        User.objects.filter(phone__in=[r.phone for r in records])
        .values_list("phone", flat=True)
    )
    events = [
        {
            "created_at": event.created_at,
            "phone": mask_phone(event.phone),
            "action": event.get_action_display(),
            "operator": mask_phone(event.operator.phone) if event.operator else "—",
        }
        for event in PhoneAllowlistEvent.objects.select_related("operator")
        [:ALLOWLIST_EVENT_LIMIT]
    ]
    return {
        "records": records,
        "registered": registered,
        "events": events,
        "status": status,
        "q": q,
        "error": None,
        "notice": None,
        "seed_count": len(settings.SMS_PHONE_WHITELIST),
        "active_total": PhoneAllowlist.objects.filter(is_active=True).count(),
        "disabled_total": PhoneAllowlist.objects.filter(is_active=False).count(),
    }


def _render_allowlist_panel(request, error=None, notice=None):
    """渲染名单面板的 HTMX 局部片段(表单 + 表格一起换,输入框随之清空)。

    备注信息:
        ``error`` / ``notice`` 覆盖 ``_allowlist_context`` 里的 ``None`` 初值;整块重渲染的
        目的就是让加号成功后的输入框跟着清空、表格回到最新状态。
    """
    ctx = _allowlist_context(request)
    ctx["error"] = error
    ctx["notice"] = notice
    return render(request, "ops/partials/allowlist_panel.html", ctx)


@staff_required
def allowlist_page(request):
    """准入名单管理页:列表 + 加号表单 + 启用/停用。(/ops/allowlist/)

    为什么这个页面存在(B-1c):本项目不接短信商,固定验证码 + 名单是**长期机制**,
    「加一个人」不能靠 SSH 改 `.env` 再重启 gunicorn —— 那既容易改错(一个逗号
    就把所有人挡在外面),也无法回答「谁加的、为什么加」。

    参数说明:
        request: Django 请求对象,支持 ``status`` 与 ``q`` 查询参数。

    返回参数:
        渲染后的名单页。

    使用示例:
        ``client.get("/ops/allowlist/?status=disabled")``

    备注信息:
        名单内 = 自己人,名单本身就是准入安全边界,因此写路径一律留操作人与流水(见
        ``allowlist_add`` / ``allowlist_toggle``)。页面只读库表 ``accounts.PhoneAllowlist``,
        ``.env`` 的种子名单只以条数形式展示;加号与启停都走 POST 局部刷新。
    """
    return render(request, "ops/allowlist.html", _allowlist_context(request))


@require_POST
@staff_required
def allowlist_add(request):
    """把一个手机号加进准入名单;已停用的号码重复提交视为「重新启用」。(/ops/allowlist/add)

    三种情形分别留一条流水(R4-B2):

    1. 库里没有这个号 → 新建,写 ``add``;
    2. 库里有但已停用 → 重新启用,写 ``enable``;
    3. 本来就在启用,只是改了备注 → **不写**流水:准入面没变,写进去只是噪声,
       会把「谁被放进来 / 谁被拿掉」这类真正要紧的记录埋掉。

    写库后立刻清名单快照缓存,所以该号码**下一次请求**就能登录,不用重启 web。

    参数说明:
        request: Django 请求对象,POST 需带 ``phone``,可选 ``note``(最长 100 字)。

    返回参数:
        名单面板的局部片段,带 ``notice`` 或 ``error``。

    使用示例:
        ``client.post("/ops/allowlist/add", {"phone": "13800138000", "note": "本人小号"})``

    备注信息:
        手机号格式与登录接口同一份规则(``PhoneAllowlistForm`` 调
        ``accounts.validators.is_valid_phone``),避免「能加进名单、登录却报格式错」。
        名单改动与它的流水在同一个事务里:要么「放进来并且留下是谁放的」,要么两样都
        没有 —— 只成功一半,这张安全边界就不可审计了。``allowlist_module.invalidate()``
        刻意放在流水之后:先落事件再让缓存失效,否则可能出现「缓存已清、事件还没写」。
        表单校验失败时把各字段错误拼成一段中文回显,不写库。
    """
    form = PhoneAllowlistForm(request.POST)
    if not form.is_valid():
        errors = "；".join(
            f"{form.fields[name].label}{''.join(msgs)}" for name, msgs in form.errors.items())
        return _render_allowlist_panel(request, error=errors)
    phone = form.cleaned_data["phone"]
    note = form.cleaned_data["note"]
    # 名单改动与它的流水必须在同一个事务里:要么「放进来并且留下是谁放的」,
    # 要么两样都没有 —— 只成功一半,这张安全边界就不可审计了。
    with transaction.atomic():
        record, created = PhoneAllowlist.objects.get_or_create(
            phone=phone, defaults={"note": note, "created_by": request.user})
        was_active = None           # 只有「已存在」分支才有意义,分支外只用于挑提示文案
        if created:
            PhoneAllowlistEvent.objects.create(
                phone=phone, action=PhoneAllowlistAction.ADD,
                operator=request.user, note=note)
        else:
            was_active = record.is_active
            record.is_active = True
            if note:
                record.note = note
            record.save(update_fields=["is_active", "note", "updated_at"])
            if not was_active:
                PhoneAllowlistEvent.objects.create(
                    phone=phone, action=PhoneAllowlistAction.ENABLE,
                    operator=request.user, note=record.note)
        # 放在流水之后:先落事件再让缓存失效,否则可能「缓存已清、事件还没写」。
        allowlist_module.invalidate()
    if created:
        return _render_allowlist_panel(
            request, notice=f"{mask_phone(phone)} 已加入名单,立即生效")
    if was_active:
        notice = f"{mask_phone(phone)} 已在名单中,备注已更新"
    else:
        notice = f"{mask_phone(phone)} 已重新启用,立即生效"
    return _render_allowlist_panel(request, notice=notice)


@require_POST
@staff_required
def allowlist_toggle(request, entry_id):
    """启用/停用一个号码;停用立刻生效(该号码下一次发码即 403)。(/ops/allowlist/<int:entry_id>/toggle)

    只改 ``is_active``,不删记录 —— 名单本身就是安全边界,「谁曾经被放进来、
    什么时候被拿掉」要留得住:每次切换都写一条 ``enable`` / ``disable`` 流水。

    参数说明:
        request: Django 请求对象。
        entry_id: 名单记录主键,不存在时 404。

    返回参数:
        名单面板的局部片段,带 ``notice``。

    使用示例:
        ``client.post("/ops/allowlist/7/toggle")``

    备注信息:
        状态翻转与流水、缓存失效在同一事务内完成:``allowlist_module.invalidate()`` 放在
        流水之后(先落事件再失效缓存),此后该号码的下一次请求立刻按新状态判定,不需要
        重启 web。流水里记下当时的 ``note``,号码在提示文案里脱敏。
    """
    record = get_object_or_404(PhoneAllowlist, pk=entry_id)
    with transaction.atomic():
        record.is_active = not record.is_active
        record.save(update_fields=["is_active", "updated_at"])
        PhoneAllowlistEvent.objects.create(
            phone=record.phone,
            action=(PhoneAllowlistAction.ENABLE if record.is_active
                    else PhoneAllowlistAction.DISABLE),
            operator=request.user, note=record.note)
        allowlist_module.invalidate()      # 与加号同理:先落流水再失效缓存
    masked = mask_phone(record.phone)
    notice = (f"{masked} 已启用,立即生效" if record.is_active
              else f"{masked} 已停用,该号码即刻无法收发验证码")
    return _render_allowlist_panel(request, notice=notice)
