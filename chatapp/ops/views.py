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
from im.models import (ChatImage, ChatImageStatus, ChatVoice, ChatVoiceStatus,
                       TranscodeStatus)
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

    参数说明:
        days: 回看天数。

    返回参数:
        用户 id 集合;没有人被举报时为空集。

    使用示例:
        ``qs = qs.filter(owner_id__in=_reported_user_ids())``(见本文件 ``chat_images``)

    备注信息:
        按 ``Report.target_id`` 收集并去重;窗口与举报详情页的证据窗口同一口径,由
        ``MEDIA_REPORT_WINDOW_DAYS`` 决定,两个入口不各写一套数字。
    """
    return set(Report.objects.filter(
        created_at__gte=timezone.now() - timedelta(days=days),
    ).values_list("target_id", flat=True))


def _log_media_access(request, kind: str, filter_name: str, count: int) -> None:
    """记录一次私聊媒体列表浏览;审计写失败只告警,绝不影响页面。

    参数说明:
        request: Django 请求对象。
        kind: ``MediaAccessLog.Kind`` 取值(image/voice)。
        filter_name: 筛选条件(all/reported/user)。
        count: 本次返回的条数。

    使用示例:
        ``_log_media_access(request, MediaAccessLog.Kind.IMAGE, filter_name, len(images))``
        (见本文件 ``chat_images``)

    备注信息:
        写库异常一律吞掉只打 warning 日志 —— 审计表故障不能让抽审页面 500。
        操作人取 ``request.user``(未登录留空),IP 取 ``client_ip(request)``。
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
    """审核台首页:直接跳到举报列表(GET /ops/)。

    参数说明:
        request: Django 请求对象。

    返回参数:
        指向举报列表的重定向(302,落地 ``/ops/reports/``)。

    使用示例:
        ``resp = self.client.get("/ops/")``(跳过首页落到 ``/ops/reports/``;
        ``ops/tests.py`` 未直接覆盖这个入口)

    备注信息:
        首页本身没有内容,只做 ``redirect("ops:reports")``;登录后的落地页在
        ``ops/otp.py`` 里同样用 ``reverse("ops:reports")`` 直达。
    """
    return redirect("ops:reports")


@staff_required
def reports_list(request):
    """举报列表页:按状态与类型过滤(GET /ops/reports/)。

    参数说明:
        request: Django 请求对象,支持 ``status`` 与 ``type`` 查询参数。

    返回参数:
        渲染后的举报列表页;最多展示 200 条。

    使用示例:
        ``resp = self.client.get("/ops/reports/")``(见 ``ops/tests.py`` 的 ``ReportListTests``)、
        ``self.client.get("/ops/reports/", {"status": "handled"})``(见同文件 ``test_handled_filter``)

    备注信息:
        按 ``-status`` 字符串降序排,让 ``pending`` 排在 ``handled`` 前(与 admin 审核台同款);
        非法 ``status`` / ``type`` 取值不过滤,退化成全量前 200 条。
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
    """举报详情页:含举报人与被举报人的历史记录(GET /ops/reports/<report_id>/)。

    参数说明:
        request: Django 请求对象。
        report_id: 举报主键。

    返回参数:
        渲染后的举报详情页,上下文由 ``_report_context`` 拼装(双方历史举报、封禁记录与
        最近 7 天的聊天图片 / 语音证据)。

    使用示例:
        ``resp = self.client.get(f"/ops/reports/{self.report.id}/")``
        (见 ``ops/tests.py`` 的 ``ReportDetailTests``)

    备注信息:
        举报不存在时由 ``get_object_or_404`` 返回 404 页面。
    """
    report = get_object_or_404(
        Report.objects.select_related("reporter", "target", "handled_by"), pk=report_id)
    return render(request, "ops/report_detail.html", _report_context(report))


def _report_context(report):
    """拼举报详情页的上下文:双方各自的历史举报、封禁记录与聊天媒体证据。

    参数说明:
        report: 举报对象。

    返回参数:
        模板上下文字典;HTMX 局部刷新复用同一份,保证整页与局部一致。

    使用示例:
        ``return render(request, "ops/report_detail.html", _report_context(report))``
        (见本文件 ``report_detail``)

    备注信息:
        只查库、不写库:双方各自的举报(各取最近 10 条,排除本条)、被举报人最近 7 天的
        聊天图片与语音(各 12 条)作为证据 —— 图片没有机器审核,靠人工抽审;语音可直接
        试听,不做转写。
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
        # 语音同理:可直接试听,不做转写(只列转码完成的 —— pending 行还没有正式文件)
        "chat_voices": ChatVoice.objects.select_related("owner").filter(
            owner=report.target,
            transcode_status=TranscodeStatus.READY,
            created_at__gte=timezone.now() - timedelta(days=7),
        ).order_by("-created_at")[:12],
    }


def _apply_status_change(user, action, reason, operator):
    """把封禁/解封动作落到资料上,并记录审计与 IM 通知。

    封禁审计与踢 IM 统一走 ``log_ban_change``,与 Django admin 同源。

    参数说明:
        user: 目标用户。
        action: ``ban_light`` / ``ban_heavy`` / ``unban``。
        reason: 封禁原因;解封时忽略。
        operator: 执行操作的运营账号。

    返回参数:
        更新后的资料对象。

    使用示例:
        ``_apply_status_change(user, action, reason, request.user)``(见本文件 ``user_ban``)、
        ``_apply_status_change(report.target, level, reason, request.user)``
        (见本文件 ``report_ban``)

    备注信息:
        解封必须先把状态改回 ``INCOMPLETE`` 再调 ``refresh_status()`` —— 封禁态不参与完善度
        重算,不先脱离封禁态就永远算不回真实状态。原因截断到 200 字后写库,审计与 IM 通知
        都走同一条 ``log_ban_change``,因此与 Django admin 完全同源。资料行不存在时先建。
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
    """把举报标记为已处理,并通知举报者(POST /ops/reports/<report_id>/handle)。

    已是「已处理」的举报不会重复处理,因此也不会重复通知。

    参数说明:
        request: Django 请求对象,POST 可带 ``note`` 作为处理备注。
        report_id: 举报主键。

    返回参数:
        举报面板的局部片段(HTMX 局部刷新,不是整页)。

    使用示例:
        ``self.client.post(f"/ops/reports/{self.report.id}/handle", {"note": "已警告"})``
        (见 ``ops/tests.py`` 的 ``ReportActionTests``)

    备注信息:
        只有 ``pending`` 状态会写库并调 ``notify_report_handled``;处理备注截断到 200 字,
        重复提交保留首次的处理人、时间与备注。
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
    """从举报详情页直接封禁被举报人,并把该举报一并标记为已处理(POST /ops/reports/<report_id>/ban)。

    封禁原因必填;级别非法或原因为空时只回显错误,不改变任何状态。

    参数说明:
        request: Django 请求对象,POST 需带 ``level`` 与 ``reason``。
        report_id: 举报主键。

    返回参数:
        举报面板的局部片段(带 ``error`` 字段;HTMX 局部刷新,不是整页)。

    使用示例:
        ``self.client.post(f"/ops/reports/{self.report.id}/ban", {"level": "ban_heavy", "reason": "色情图片"})``
        (见 ``ops/tests.py`` 的 ``test_quick_ban_heavy_bans_and_handles``)

    备注信息:
        封禁落库走 ``_apply_status_change``;举报仍是 ``pending`` 时才改成 ``handled``、
        备注写死「封禁处理」并通知举报者。级别与原因都不合法时只回显第一条错误,库表不动。
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
    """照片审核列表页:默认展示待审核(GET /ops/photos/)。

    参数说明:
        request: Django 请求对象,支持 ``status`` 查询参数。

    返回参数:
        渲染后的照片网格页;最多展示 120 张。

    使用示例:
        ``resp = self.client.get("/ops/photos/")``(见 ``ops/tests.py`` 的 ``OpsPhotoReviewTests``)

    备注信息:
        按创建时间倒序;非法 ``status`` 取值不过滤,退化成全部状态的前 120 张。
        生产 ``AUTO_APPROVE`` 默认 0,新资料图先落到这里等人工审。
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
    """批量通过或驳回所选照片,并回吐刷新后的照片网格(POST /ops/photos/review)。

    参数说明:
        request: Django 请求对象,POST 需带 ``ids``(多值)、``action``
            (``approve`` / ``reject``)与可选 ``status``。

    返回参数:
        照片网格的局部片段(HTMX 局部刷新,不是整页),``skipped`` 为页面陈旧、照片已被
        删除的条数。

    使用示例:
        ``self.client.post("/ops/photos/review", {"ids": "99999999", "action": "approve"})``
        (见 ``ops/tests.py`` 的 ``test_missing_photo_id_is_skipped_with_notice``)

    备注信息:
        非数字 ``ids`` 一律丢弃 —— ``pk__in`` 求值时会抛 ``ValueError``(500),且不能用
        ``str.isdigit()`` 过滤(``"²".isdigit()`` 为真但 ``int()`` 会抛)。一次最多审 500 张,
        避免超大表单打库。任何状态都可再审(已通过可撤回驳回)。过审 / 驳回直接决定谁能进
        候选池,因此审完让全站候选池缓存失效(``invalidate_pool_globally``)。
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
    """按手机号精确匹配或昵称模糊匹配搜索用户(GET /ops/users/)。

    参数说明:
        request: Django 请求对象,支持 ``q`` 查询参数。

    返回参数:
        渲染后的搜索结果页;``q`` 为空时不返回任何结果,最多 50 条。

    使用示例:
        ``resp = self.client.get("/ops/users/", {"q": "13800138000"})``
        (见 ``ops/tests.py`` 的 ``OpsUserSearchTests``)

    备注信息:
        手机号只做精确匹配(输入部分号码搜不到);昵称走 ``icontains`` 模糊匹配;两者取并集。
    """
    q = request.GET.get("q", "").strip()
    results = []
    if q:
        results = (User.objects.filter(Q(phone=q) | Q(profile__nickname__icontains=q))
                   .select_related("profile").order_by("id")[:50])
    return render(request, "ops/users_search.html", {"q": q, "results": results})


@staff_required
def user_detail(request, user_id):
    """用户详情页:资料、封禁记录、举报与拉黑关系(GET /ops/users/<user_id>/)。

    参数说明:
        request: Django 请求对象。
        user_id: 目标账号 id。

    返回参数:
        渲染后的用户详情页,上下文由 ``_user_context`` 拼装。

    使用示例:
        ``resp = self.client.get(f"/ops/users/{self.alice.id}/")``
        (见 ``ops/tests.py`` 的 ``OpsUserDetailTests``)

    备注信息:
        账号不存在时由 ``get_object_or_404`` 返回 404 页面。
    """
    user = get_object_or_404(User.objects.select_related("profile"), pk=user_id)
    return render(request, "ops/user_detail.html", _user_context(user))


def _user_context(user):
    """拼用户详情页的上下文:封禁记录、收到的 / 发出的举报与拉黑关系。

    参数说明:
        user: 目标用户。

    返回参数:
        模板上下文字典;HTMX 封禁局部刷新复用同一份,保证整页与局部一致。

    使用示例:
        ``ctx = _user_context(user)``(见本文件 ``user_ban``)、
        ``return render(request, "ops/user_detail.html", _user_context(user))``
        (见本文件 ``user_detail``)

    备注信息:
        只查库、不写库;封禁记录、收到的举报、发出的举报与两个方向的拉黑关系各取最近 20 条。
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
    """从用户详情页执行封禁或解封(POST /ops/users/<user_id>/ban)。

    封禁原因必填;解封不需要原因。

    参数说明:
        request: Django 请求对象,POST 需带 ``action``
            (``ban_light`` / ``ban_heavy`` / ``unban``)与封禁时的 ``reason``。
        user_id: 目标账号 id。

    返回参数:
        封禁面板的局部片段(带 ``error`` 字段;HTMX 局部刷新,不是整页)。

    使用示例:
        ``self.client.post(f"/ops/users/{self.user.id}/ban", {"action": "ban_light", "reason": "骚扰他人"})``
        (见 ``ops/tests.py`` 的 ``test_ban_light_dispatches_notice_no_kick``)

    备注信息:
        封禁落库统一走 ``_apply_status_change``;未知 ``action`` 只回显「未知操作」,封禁但
        原因为空只回显「封禁必须填写原因」,两种情况都不动库表,只回吐带错误的局部片段。
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

    参数说明:
        numerator: 分子(如当日新增配对数)。
        denominator: 分母(如当日「喜欢」次数)。

    返回参数:
        比值 ``numerator / denominator``;分母为 0 返回 ``None``(看板渲染 ``—``)。

    使用示例:
        ``_format_rate(_rate(sum(row.matches for row in window), sum(row.swipes_like for row in window)))``
        (见本文件 ``_metrics_summary``)

    备注信息:
        「采到 0」与「没采到」在看板上必须区分:0 参与求和,``None`` 不参与;分母为 0 返回
        ``None`` 而不是 0,避免把「没有数据」显示成「0%」。
    """
    if not denominator:
        return None
    return numerator / denominator


def _format_rate(rate: float | None) -> str | None:
    """把配对率格式化成百分比文本。

    格式化放在这里而不是模板:模板只做展示,不做除法,也不做数字格式化。

    参数说明:
        rate: 比值(``0.4`` 表示 40%);``None`` 表示分母为 0。

    返回参数:
        ``"40.0%"`` 这样的文本;``None`` 原样返回,由模板渲染 ``—``。

    使用示例:
        ``"match_rate": _format_rate(stats_metrics.match_rate(row))``
        (见本文件 ``_metrics_trend``)

    备注信息:
        固定保留一位小数;空值原样穿透,不在这一层把 ``None`` 变成 ``"0.0%"``。
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

    参数说明:
        window: 窗口内的快照行(可以只有几天,也可以为空)。

    返回参数:
        含 ``days`` / ``start`` / ``end`` / ``new_users`` / ``avg_dau`` /
        ``match_rate`` / ``messages`` 的字典;采不到的聚合值一律 ``None``。

    使用示例:
        ``"summary": _metrics_summary(window)``(见本文件 ``metrics``)

    备注信息:
        全部在这份内存列表上算,不在循环里查库;``window`` 由 ``metrics`` 按
        ``METRICS_SUMMARY_DAYS`` 从昨日往前筛好再传进来,本函数不碰数据库。
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

    参数说明:
        rows: ``stats.metrics.recent_rows`` 返回的 ``DailyMetric`` 列表。

    返回参数:
        每行一个字典,缺失值保持 ``None``,由模板用 ``default_if_none`` 渲染 ``—``。

    使用示例:
        ``"rows": _metrics_trend(rows)``(见本文件 ``metrics``)

    备注信息:
        配对率逐行调 ``stats_metrics.match_rate(row)`` 再经 ``_format_rate`` 转成百分比文本;
        模板只贴值,不做除法与数字格式化。
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

    参数说明:
        row: 带 ``active_hours`` 的快照行;``None`` 或没有时段分布时返回空列表。

    返回参数:
        24 条 ``{"hour": "09", "count": 3, "pct": 60.0}``;``pct`` 是相对当日最高峰
        的百分比(CSS 横条宽度),当日无人活跃时全是 ``0``。列不是列表(脏数据)时返回
        空列表 —— 看板不能因为一行的时段分布不对就整页 500。

    使用示例:
        ``"hour_bars": _hour_bars(activity_row)``(见本文件 ``metrics``)

    备注信息:
        ``pct`` 以当日最高峰为 100%,峰值是 0 时一律记 0;小时标签补零成两位,便于模板
        直接显示。
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
    """运营看板:昨日数字卡、近 30 天趋势表与活跃时段(GET /ops/metrics/)。

    数据全部来自 V-1 写好并由 ``manage.py metrics_daily`` 每天写入的
    ``stats.DailyMetric`` 快照表 —— 本页**只读**:一条 SQL 取 30 行
    (``stats.metrics.recent_rows``),汇总、配对率、时段横条宽度全在这份内存列表上算,
    模板里不做除法。缺失值(``None``)由模板渲染成 ``—``,与「采到了 0」严格区分。

    参数说明:
        request: Django 请求对象。

    返回参数:
        渲染后的看板页;快照表为空时同样返回 200(页面给「还没有数据」提示,不抛异常)。

    使用示例:
        ``resp = self.client.get("/ops/metrics/")``(见 ``ops/tests.py`` 的 ``OpsMetricsTests``)

    备注信息:
        活跃时段取「最近一行**真的采到**小时分布的快照」:最新那行 ``active_hours`` 可能是
        空的(当天 Redis 没记录),退到前一天比显示「暂无数据」更有用。页面不写任何表、
        不查 IM 库、不算实时指标 —— 实时归 Prometheus。
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
    """封禁审计与拉黑记录查询页(GET /ops/logs/)。

    参数说明:
        request: Django 请求对象,支持 ``action`` / ``phone`` / ``date`` 过滤。

    返回参数:
        渲染后的日志页;封禁日志最多 200 条、拉黑记录最多 100 条。

    使用示例:
        ``resp = self.client.get("/ops/logs/", {"action": "unban"})``
        (见 ``ops/tests.py`` 的 ``OpsLogsTests``)

    备注信息:
        非法 ``action`` 不过滤;``date`` 格式非法时 ``filter`` 抛的 ``ValidationError``
        就地兜住并清空该筛选,页面照常 200。
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

    返回参数:
        已排序并注解的 ``Post`` 查询集切片。

    使用示例:
        ``return render(request, "ops/posts.html", {"posts": _posts_queryset()})``
        (见本文件 ``posts``)

    备注信息:
        赞 / 评数用 ``distinct=True`` 的 ``Count`` 注解,避免两个连表相乘把计数放大;作者
        资料与动态图片一并预取,模板里不再逐条回查。
    """
    return (Post.objects.select_related("author__profile")
            .prefetch_related("images")
            .annotate(like_count=Count("likes", distinct=True),
                      comment_count=Count("comments", distinct=True))
            .order_by("-created_at", "-id")[:200])


@staff_required
def posts(request):
    """动态治理列表页(GET /ops/posts/)。

    参数说明:
        request: Django 请求对象。

    返回参数:
        渲染后的动态列表页(最多 200 条)。

    使用示例:
        ``resp = self.client.get("/ops/posts/")``(见 ``ops/tests.py`` 的 ``OpsPostsTests``)

    备注信息:
        数据来自 ``_posts_queryset``;本页只读,删除动作在 ``post_delete``。
    """
    return render(request, "ops/posts.html", {"posts": _posts_queryset()})


@require_POST
@staff_required
def post_delete(request, post_id):
    """运营删除一条动态,并回吐刷新后的动态表格(POST /ops/posts/<post_id>/delete)。

    删除走 ``feed.services.delete_post``,会连带关闭该动态的待处理举报并通知举报者。

    参数说明:
        request: Django 请求对象。
        post_id: 动态主键。

    返回参数:
        动态表格的局部片段(HTMX 局部刷新,不是整页)。

    使用示例:
        ``resp = self.client.post(f"/ops/posts/{self.post.id}/delete")``
        (见 ``ops/tests.py`` 的 ``test_delete_removes_post``)

    备注信息:
        删除逻辑全部在 ``feed.services.delete_post``,本视图只做 404 判断与重新渲染;动态
        不存在时由 ``get_object_or_404`` 返回 404 页面。
    """
    post = get_object_or_404(Post, pk=post_id)
    delete_post(post)
    return render(request, "ops/partials/posts_table.html", {"posts": _posts_queryset()})


def _post_reports_queryset(status):
    """按状态过滤动态举报(按状态与时间倒序,最多 200 条)。

    参数说明:
        status: 举报状态;非 ``ReportStatus`` 取值时不过滤。

    返回参数:
        已排序的 ``PostReport`` 查询集切片。

    使用示例:
        ``{"reports": _post_reports_queryset(status), "status": status}``
        (见本文件 ``post_reports``)

    备注信息:
        按 ``-status`` 字符串降序排,让 ``pending`` 排在 ``handled`` 前;举报与动态作者、
        举报者、处理人一并 ``select_related``,避免模板逐条回查。
    """
    qs = (PostReport.objects.select_related("post__author__profile", "reporter", "handled_by")
          .order_by("-status", "-created_at"))
    if status in ReportStatus.values:
        qs = qs.filter(status=status)
    return qs[:200]


def _render_post_reports(request):
    """渲染动态举报表格片段,状态优先取 POST 再取 GET。

    参数说明:
        request: Django 请求对象。

    返回参数:
        动态举报表格的局部片段(HTMX 局部刷新,不是整页)。

    使用示例:
        ``return _render_post_reports(request)``(见本文件 ``post_report_handle``)

    备注信息:
        状态取 ``POST.status``、再退 ``GET.status``,缺省 ``pending`` —— HTMX 局部刷新的
        POST 里也带着当前筛选,处理完刷新时不会跳回默认视图。
    """
    status = (request.POST.get("status") or request.GET.get("status")
              or ReportStatus.PENDING)
    return render(request, "ops/partials/post_reports_table.html",
                  {"reports": _post_reports_queryset(status), "status": status})


@staff_required
def post_reports(request):
    """动态举报列表页(GET /ops/post-reports/)。

    参数说明:
        request: Django 请求对象,支持 ``status`` 查询参数。

    返回参数:
        渲染后的动态举报页;最多展示 200 条。

    使用示例:
        ``resp = self.client.get("/ops/post-reports/")``
        (见 ``ops/tests.py`` 的 ``OpsPostReportsTests``)

    备注信息:
        列表复用 ``_post_reports_queryset``;非法 ``status`` 取值不过滤,退化成全量前 200 条。
    """
    status = request.GET.get("status", ReportStatus.PENDING)
    return render(request, "ops/post_reports.html", {
        "reports": _post_reports_queryset(status), "status": status,
        "types": ReportType.choices,
    })


@require_POST
@staff_required
def post_report_handle(request, report_id):
    """把动态举报标记为已处理,并通知举报者(POST /ops/post-reports/<report_id>/handle)。

    参数说明:
        request: Django 请求对象,POST 可带 ``note`` 作为处理备注。
        report_id: 动态举报主键。

    返回参数:
        动态举报表格的局部片段(HTMX 局部刷新,不是整页)。

    使用示例:
        ``self.client.post(f"/ops/post-reports/{self.report.id}/handle", {"note": "内容没问题"})``
        (见 ``ops/tests.py`` 的 ``test_ignore_marks_handled_and_notifies``)

    备注信息:
        只有 ``pending`` 状态会写库并调 ``notify_report_handled``;备注截断到 200 字,
        重复提交不再通知。
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
    """删掉被举报的动态,并关闭该动态的全部待处理举报(POST /ops/post-reports/<report_id>/delete-post)。

    动态已被作者删除时(``post`` 被置空)只关闭当前这条举报。

    参数说明:
        request: Django 请求对象。
        report_id: 动态举报主键。

    返回参数:
        动态举报表格的局部片段(HTMX 局部刷新,不是整页)。

    使用示例:
        ``self.client.post(f"/ops/post-reports/{self.report.id}/delete-post")``
        (见 ``ops/tests.py`` 的 ``test_delete_post_removes_and_closes_all_pending``)

    备注信息:
        有 ``post`` 时走 ``delete_post``(该动态全部 pending 标 handled、各举报者各通知一次、
        动态行删除);``post`` 已置空时只关当前这条,备注写「动态已删除」。已是 ``handled``
        的举报不再改写。
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

    参数说明:
        request: Django 请求对象,支持 ``status`` 与 ``type``。

    返回参数:
        ``(queryset, status, ftype)``;``status=all`` 时不按状态过滤。

    使用示例:
        ``qs, status, ftype = _feedback_queryset(request)``(见本文件 ``feedback_list``)

    备注信息:
        默认只看 ``pending``;非法 ``status`` / ``type`` 取值不过滤;按创建时间倒序,最多
        200 条。列表页与处理后的局部刷新共用同一份筛选逻辑,两处不会各说一套。
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
    """意见反馈列表页,默认只看待处理(GET /ops/feedback/)。

    参数说明:
        request: Django 请求对象,支持 ``status`` 与 ``type`` 查询参数。

    返回参数:
        渲染后的反馈列表页;最多展示 200 条。

    使用示例:
        ``resp = self.client.get("/ops/feedback/?status=handled")``
        (见 ``ops/tests.py`` 的 ``FeedbackOpsTests``)

    备注信息:
        筛选逻辑全在 ``_feedback_queryset``;``status=all`` 看全量,``type`` 只认
        ``FeedbackType`` 的取值。
    """
    qs, status, ftype = _feedback_queryset(request)
    return render(request, "ops/feedback.html", {
        "feedbacks": qs, "status": status, "ftype": ftype,
        "types": FeedbackType.choices,
    })


@require_POST
@staff_required
def feedback_handle(request, feedback_id):
    """把一条反馈标记为已处理(POST /ops/feedback/<feedback_id>/handle)。

    已处理的反馈不会重复改写备注与处理人。

    参数说明:
        request: Django 请求对象,POST 可带 ``note`` 作为处理备注。
        feedback_id: 反馈主键。

    返回参数:
        反馈表格的 HTMX 局部片段(不是整页)。

    使用示例:
        ``self.client.post(f"/ops/feedback/{self.pending.id}/handle", {"note": "已记录"})``
        (见 ``ops/tests.py`` 的 ``test_partial_root_is_hx_target``)

    备注信息:
        只有 ``pending`` 状态会写库,处理备注截断到 200 字;处理完按当前筛选重新渲染表格
        片段,筛选取 ``POST`` 再退 ``GET``。
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
    """聊天图片抽审列表,按时间倒序最多 120 条(GET /ops/chat-images/)。

    参数说明:
        request: Django 请求对象,支持 ``user`` 查询参数(按发送者过滤)、
            ``reported=1``(只看最近 7 天被举报过的发送者);每次浏览写一条审计。

    返回参数:
        渲染后的聊天图片表格页。

    使用示例:
        ``response = self.client.get("/ops/chat-images/?reported=1")``
        (见 ``ops/tests.py`` 的 ``ChatImageOpsTests``)

    备注信息:
        只列 ``VISIBLE`` 状态的图片;``user`` 非数字时忽略(``optional_id`` 返回 ``None``),
        不报错;每次浏览都写一条 ``MediaAccessLog``,审计写失败不影响页面。
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
    """删除一张聊天图片:删原图与缩略图文件,行保留并记审计(POST /ops/chat-images/<image_id>/delete)。

    参数说明:
        request: Django 请求对象。
        image_id: 聊天图片主键。

    返回参数:
        刷新后的表格局部片段(HTMX 局部刷新,不是整页)。

    使用示例:
        ``response = self.client.post(f"/ops/chat-images/{self.image.id}/delete")``
        (见 ``ops/tests.py`` 的 ``test_delete_marks_status_and_removes_files``)

    备注信息:
        行不删,只把状态置成 ``DELETED`` 并记 ``deleted_by`` / ``deleted_at`` —— 审计要留得住;
        原图与缩略图两个文件都从存储删掉。图片不存在时由 ``get_object_or_404`` 返回 404。
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
    """聊天语音抽审列表,按时间倒序最多 120 条(GET /ops/chat-voices/)。

    参数说明:
        request: Django 请求对象,支持 ``user`` 查询参数(按发送者过滤)、
            ``reported=1``(只看最近 7 天被举报过的发送者);每次浏览写一条审计。

    返回参数:
        渲染后的聊天语音表格页。

    使用示例:
        ``response = self.client.get("/ops/chat-voices/")``
        (见 ``ops/tests.py`` 的 ``ChatVoiceOpsTests``)

    备注信息:
        只列 ``VISIBLE`` 且转码完成(``transcode_status=ready``)的语音 —— ``pending`` 行还没有
        正式文件,``signed_file_url`` 给不出可试听地址;``user`` 非数字时忽略,不报错;每次浏览都写一条
        ``MediaAccessLog``,审计写失败不影响页面。
    """
    qs = ChatVoice.objects.select_related("owner").filter(
        status=ChatVoiceStatus.VISIBLE,
        transcode_status=TranscodeStatus.READY).order_by("-created_at")
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
    """删除一条聊天语音:删文件,行保留并记审计(POST /ops/chat-voices/<voice_id>/delete)。

    参数说明:
        request: Django 请求对象。
        voice_id: 聊天语音主键。

    返回参数:
        刷新后的表格局部片段(HTMX 局部刷新,不是整页)。

    使用示例:
        ``response = self.client.post(f"/ops/chat-voices/{self.voice.pk}/delete")``
        (见 ``ops/tests.py`` 的 ``test_delete_marks_status_and_removes_file``)

    备注信息:
        行不删,只把状态置成 ``DELETED`` 并记 ``deleted_by`` / ``deleted_at`` —— 审计要留得住;
        音频文件从存储删掉。语音不存在时由 ``get_object_or_404`` 返回 404。
    """
    voice = get_object_or_404(ChatVoice, pk=voice_id)
    if voice.file:
        default_storage.delete(voice.file.name)
    voice.status = ChatVoiceStatus.DELETED
    voice.deleted_by = request.user
    voice.deleted_at = timezone.now()
    voice.save(update_fields=["status", "deleted_by", "deleted_at"])
    qs = ChatVoice.objects.select_related("owner").filter(
        status=ChatVoiceStatus.VISIBLE,
        transcode_status=TranscodeStatus.READY).order_by("-created_at")
    return render(request, "ops/partials/chat_voices_table.html", {"voices": qs[:120]})


def _allowlist_context(request):
    """拼准入名单页的上下文(列表、筛选、库/种子规模),整页与 HTMX 局部共用。

    参数说明:
        request: Django 请求对象;筛选参数 ``status``(active/disabled/all)与
            ``q``(手机号或备注模糊匹配)优先取 POST,再退回 GET ——
            HTMX 局部刷新的 POST 里也带着当前筛选,刷新后不会跳回默认视图。

    返回参数:
        模板上下文字典;``registered`` 是「这些号码里哪些已经注册了账号」的集合,
        用来提醒运营「加了号还没人用过」和「这个号已经有账号了」;``events`` 是
        最近 ``ALLOWLIST_EVENT_LIMIT`` 条操作流水,号码与操作人都在这里脱敏。

    使用示例:
        ``return render(request, "ops/allowlist.html", _allowlist_context(request))``
        (见本文件 ``allowlist_page``)

    备注信息:
        记录取 ``ALLOWLIST_PAGE_SIZE`` 条(名单总量几十到几百,不分页);``seed_count`` 是
        ``settings.SMS_PHONE_WHITELIST`` 的种子规模,与库内的启用 / 停用条数分开展示。
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

    参数说明:
        request: Django 请求对象。
        error: 需要回显的错误文案;``None`` 表示无错误。
        notice: 操作成功的提示文案;``None`` 表示无提示。

    返回参数:
        名单面板的局部片段响应(HTMX 局部刷新,不是整页)。

    使用示例:
        ``return _render_allowlist_panel(request, error=errors)``(见本文件 ``allowlist_add``)、
        ``return _render_allowlist_panel(request, notice=notice)``(见本文件 ``allowlist_toggle``)

    备注信息:
        表单与表格放在同一个片段里一起换,加号 / 启停后输入框随之清空,不需要页面再单独刷新。
    """
    ctx = _allowlist_context(request)
    ctx["error"] = error
    ctx["notice"] = notice
    return render(request, "ops/partials/allowlist_panel.html", ctx)


@staff_required
def allowlist_page(request):
    """准入名单管理页:列表 + 加号表单 + 启用/停用(GET /ops/allowlist/)。

    为什么这个页面存在(B-1c):本项目不接短信商,固定验证码 + 名单是**长期机制**,
    「加一个人」不能靠 SSH 改 `.env` 再重启 gunicorn —— 那既容易改错(一个逗号
    就把所有人挡在外面),也无法回答「谁加的、为什么加」。

    参数说明:
        request: Django 请求对象,支持 ``status`` 与 ``q`` 查询参数。

    返回参数:
        渲染后的名单页(整页,不是片段)。

    使用示例:
        ``resp = self.client.get("/ops/allowlist/?status=all")``
        (见 ``ops/tests.py`` 的 ``OpsAllowlistTests``)

    备注信息:
        本页只读,写动作全在 ``allowlist_add`` 与 ``allowlist_toggle``;上下文由
        ``_allowlist_context`` 拼装,与 HTMX 局部刷新共用同一份。
    """
    return render(request, "ops/allowlist.html", _allowlist_context(request))


@require_POST
@staff_required
def allowlist_add(request):
    """把一个手机号加进准入名单;已停用的号码重复提交视为「重新启用」(POST /ops/allowlist/add)。

    三种情形分别留一条流水(R4-B2):

    1. 库里没有这个号 → 新建,写 ``add``;
    2. 库里有但已停用 → 重新启用,写 ``enable``;
    3. 本来就在启用,只是改了备注 → **不写**流水:准入面没变,写进去只是噪声,
       会把「谁被放进来 / 谁被拿掉」这类真正要紧的记录埋掉。

    写库后立刻清名单快照缓存,所以该号码**下一次请求**就能登录,不用重启 web。

    参数说明:
        request: Django 请求对象,POST 需带 ``phone``,可选 ``note``。

    返回参数:
        名单面板的局部片段,带 ``notice`` 或 ``error``(HTMX 局部刷新,不是整页)。

    使用示例:
        ``self.client.post("/ops/allowlist/add", {"phone": self.NEWCOMER, "note": "测试同事"})``
        (见 ``ops/tests.py`` 的 ``test_add_creates_entry_with_operator``)

    备注信息:
        表单校验失败只回显错误、不落库(避免「加进去却永远登不上」);名单改动与它的流水
        必须在同一个事务里,要么「放进来并且留下是谁放的」,要么两样都没有;缓存失效放在
        流水之后,否则可能出现「缓存已清、事件还没写」。
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
    """启用/停用一个号码;停用立刻生效,该号码下一次发码即 403(POST /ops/allowlist/<entry_id>/toggle)。

    只改 ``is_active``,不删记录 —— 名单本身就是安全边界,「谁曾经被放进来、
    什么时候被拿掉」要留得住:每次切换都写一条 ``enable`` / ``disable`` 流水。

    参数说明:
        request: Django 请求对象。
        entry_id: 名单记录主键。

    返回参数:
        名单面板的局部片段,带 ``notice``(HTMX 局部刷新,不是整页)。

    使用示例:
        ``self.client.post(f"/ops/allowlist/{record.id}/toggle")``
        (见 ``ops/tests.py`` 的 ``test_toggle_disables_and_blocks_immediately``)

    备注信息:
        状态切换与流水在同一个事务里;先落流水再让名单快照缓存失效(``allowlist_module.invalidate()``),
        停用因此立刻生效,不用重启 web、也不用等快照 TTL。记录不存在时由
        ``get_object_or_404`` 返回 404 页面。
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
