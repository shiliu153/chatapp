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

    Args:
        days: 回看天数。

    Returns:
        用户 id 集合;没有人被举报时为空集。
    """
    return set(Report.objects.filter(
        created_at__gte=timezone.now() - timedelta(days=days),
    ).values_list("target_id", flat=True))


def _log_media_access(request, kind: str, filter_name: str, count: int) -> None:
    """记录一次私聊媒体列表浏览;审计写失败只告警,绝不影响页面。

    Args:
        request: Django 请求对象。
        kind: ``MediaAccessLog.Kind`` 取值(image/voice)。
        filter_name: 筛选条件(all/reported/user)。
        count: 本次返回的条数。
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
    """审核台首页:直接跳到举报列表。

    Args:
        request: Django 请求对象。

    Returns:
        指向举报列表的重定向。
    """
    return redirect("ops:reports")


@staff_required
def reports_list(request):
    """举报列表页,支持按状态与类型过滤。

    Args:
        request: Django 请求对象,支持 ``status`` 与 ``type`` 查询参数。

    Returns:
        渲染后的举报列表页;最多展示 200 条。
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
    """举报详情页(含举报人与被举报人的历史记录)。

    Args:
        request: Django 请求对象。
        report_id: 举报主键。

    Returns:
        渲染后的举报详情页。
    """
    report = get_object_or_404(
        Report.objects.select_related("reporter", "target", "handled_by"), pk=report_id)
    return render(request, "ops/report_detail.html", _report_context(report))


def _report_context(report):
    """拼举报详情页的上下文(含双方各自的历史举报与封禁记录)。

    Args:
        report: 举报对象。

    Returns:
        模板上下文字典;HTMX 局部刷新复用同一份,保证整页与局部一致。
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

    封禁审计与踢 IM 统一走 ``log_ban_change``,与 Django admin 同源。

    Args:
        user: 目标用户。
        action: ``ban_light`` / ``ban_heavy`` / ``unban``。
        reason: 封禁原因;解封时忽略。
        operator: 执行操作的运营账号。

    Returns:
        更新后的资料对象。
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
    """把举报标记为已处理,并通知举报者。

    已是「已处理」的举报不会重复处理,因此也不会重复通知。

    Args:
        request: Django 请求对象,POST 可带 ``note`` 作为处理备注。

    Returns:
        举报面板的局部片段。
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
    """从举报详情页直接封禁被举报人,并把该举报一并标记为已处理。

    封禁原因必填;级别非法或原因为空时只回显错误,不改变任何状态。

    Args:
        request: Django 请求对象,POST 需带 ``level`` 与 ``reason``。

    Returns:
        举报面板的局部片段(带 ``error`` 字段)。
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
    """照片审核列表页,默认展示待审核。

    Args:
        request: Django 请求对象,支持 ``status`` 查询参数。

    Returns:
        渲染后的照片网格页;最多展示 120 张。
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
    """批量通过或驳回所选照片,并回吐刷新后的照片网格。

    Args:
        request: Django 请求对象,POST 需带 ``ids``(多值)、``action``
            (``approve`` / ``reject``)与可选 ``status``。

    Returns:
        照片网格的局部片段,``skipped`` 为页面陈旧、照片已被删除的条数。
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
    """按手机号精确匹配或昵称模糊匹配搜索用户。

    Args:
        request: Django 请求对象,支持 ``q`` 查询参数。

    Returns:
        渲染后的搜索结果页;``q`` 为空时不返回任何结果。
    """
    q = request.GET.get("q", "").strip()
    results = []
    if q:
        results = (User.objects.filter(Q(phone=q) | Q(profile__nickname__icontains=q))
                   .select_related("profile").order_by("id")[:50])
    return render(request, "ops/users_search.html", {"q": q, "results": results})


@staff_required
def user_detail(request, user_id):
    """用户详情页(资料、封禁记录、举报与拉黑关系)。

    Args:
        request: Django 请求对象。
        user_id: 目标账号 id。

    Returns:
        渲染后的用户详情页。
    """
    user = get_object_or_404(User.objects.select_related("profile"), pk=user_id)
    return render(request, "ops/user_detail.html", _user_context(user))


def _user_context(user):
    """拼用户详情页的上下文(封禁记录、收到的/发出的举报、拉黑关系)。

    Args:
        user: 目标用户。

    Returns:
        模板上下文字典;HTMX 封禁局部刷新复用同一份,保证整页与局部一致。
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
    """从用户详情页执行封禁或解封。

    封禁原因必填;解封不需要原因。

    Args:
        request: Django 请求对象,POST 需带 ``action``
            (``ban_light`` / ``ban_heavy`` / ``unban``)与封禁时的 ``reason``。

    Returns:
        封禁面板的局部片段(带 ``error`` 字段)。
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

    Args:
        numerator: 分子(如当日新增配对数)。
        denominator: 分母(如当日「喜欢」次数)。

    Returns:
        比值 ``numerator / denominator``;分母为 0 返回 ``None``(看板渲染 ``—``)。
    """
    if not denominator:
        return None
    return numerator / denominator


def _format_rate(rate: float | None) -> str | None:
    """把配对率格式化成百分比文本。

    格式化放在这里而不是模板:模板只做展示,不做除法,也不做数字格式化。

    Args:
        rate: 比值(``0.4`` 表示 40%);``None`` 表示分母为 0。

    Returns:
        ``"40.0%"`` 这样的文本;``None`` 原样返回,由模板渲染 ``—``。
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

    Args:
        window: 窗口内的快照行(可以只有几天,也可以为空)。

    Returns:
        含 ``days`` / ``start`` / ``end`` / ``new_users`` / ``avg_dau`` /
        ``match_rate`` / ``messages`` 的字典;采不到的聚合值一律 ``None``。
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

    Args:
        rows: ``stats.metrics.recent_rows`` 返回的 ``DailyMetric`` 列表。

    Returns:
        每行一个字典,缺失值保持 ``None``,由模板用 ``default_if_none`` 渲染 ``—``。
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

    Args:
        row: 带 ``active_hours`` 的快照行;``None`` 或没有时段分布时返回空列表。

    Returns:
        24 条 ``{"hour": "09", "count": 3, "pct": 60.0}``;``pct`` 是相对当日最高峰
        的百分比(CSS 横条宽度),当日无人活跃时全是 ``0``。列不是列表(脏数据)时返回
        空列表 —— 看板不能因为一行的时段分布不对就整页 500。
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
    """运营看板:昨日数字卡、近 30 天趋势表与活跃时段。

    数据全部来自 V-1 写好并由 ``manage.py metrics_daily`` 每天写入的
    ``stats.DailyMetric`` 快照表 —— 本页**只读**:一条 SQL 取 30 行
    (``stats.metrics.recent_rows``),汇总、配对率、时段横条宽度全在这份内存列表上算,
    模板里不做除法。缺失值(``None``)由模板渲染成 ``—``,与「采到了 0」严格区分。

    Args:
        request: Django 请求对象。

    Returns:
        渲染后的看板页;快照表为空时同样返回 200(页面给「还没有数据」提示,不抛异常)。
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
    """封禁审计与拉黑记录查询页。

    Args:
        request: Django 请求对象,支持 ``action`` / ``phone`` / ``date`` 过滤。

    Returns:
        渲染后的日志页;封禁日志最多 200 条、拉黑记录最多 100 条。
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

    Returns:
        已排序并注解的 ``Post`` 查询集切片。
    """
    return (Post.objects.select_related("author__profile")
            .prefetch_related("images")
            .annotate(like_count=Count("likes", distinct=True),
                      comment_count=Count("comments", distinct=True))
            .order_by("-created_at", "-id")[:200])


@staff_required
def posts(request):
    """动态治理列表页。

    Args:
        request: Django 请求对象。

    Returns:
        渲染后的动态列表页。
    """
    return render(request, "ops/posts.html", {"posts": _posts_queryset()})


@require_POST
@staff_required
def post_delete(request, post_id):
    """运营删除一条动态,并回吐刷新后的动态表格。

    删除走 ``feed.services.delete_post``,会连带关闭该动态的待处理举报并通知举报者。

    Args:
        request: Django 请求对象。
        post_id: 动态主键。

    Returns:
        动态表格的局部片段。
    """
    post = get_object_or_404(Post, pk=post_id)
    delete_post(post)
    return render(request, "ops/partials/posts_table.html", {"posts": _posts_queryset()})


def _post_reports_queryset(status):
    """按状态过滤动态举报(按状态与时间倒序,最多 200 条)。

    Args:
        status: 举报状态;非 ``ReportStatus`` 取值时不过滤。

    Returns:
        已排序的 ``PostReport`` 查询集切片。
    """
    qs = (PostReport.objects.select_related("post__author__profile", "reporter", "handled_by")
          .order_by("-status", "-created_at"))
    if status in ReportStatus.values:
        qs = qs.filter(status=status)
    return qs[:200]


def _render_post_reports(request):
    """渲染动态举报表格片段,状态优先取 POST 再取 GET。

    Args:
        request: Django 请求对象。

    Returns:
        动态举报表格的局部片段。
    """
    status = (request.POST.get("status") or request.GET.get("status")
              or ReportStatus.PENDING)
    return render(request, "ops/partials/post_reports_table.html",
                  {"reports": _post_reports_queryset(status), "status": status})


@staff_required
def post_reports(request):
    """动态举报列表页。

    Args:
        request: Django 请求对象,支持 ``status`` 查询参数。

    Returns:
        渲染后的动态举报页。
    """
    status = request.GET.get("status", ReportStatus.PENDING)
    return render(request, "ops/post_reports.html", {
        "reports": _post_reports_queryset(status), "status": status,
        "types": ReportType.choices,
    })


@require_POST
@staff_required
def post_report_handle(request, report_id):
    """把动态举报标记为已处理,并通知举报者。

    Args:
        request: Django 请求对象,POST 可带 ``note`` 作为处理备注。
        report_id: 动态举报主键。

    Returns:
        动态举报表格的局部片段。
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
    """删掉被举报的动态,并关闭该动态的全部待处理举报。

    动态已被作者删除时(``post`` 被置空)只关闭当前这条举报。

    Args:
        request: Django 请求对象。
        report_id: 动态举报主键。

    Returns:
        动态举报表格的局部片段。
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

    Args:
        request: Django 请求对象,支持 ``status`` 与 ``type``。

    Returns:
        ``(queryset, status, ftype)``;``status=all`` 时不按状态过滤。
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
    """意见反馈列表页,默认只看待处理。

    Args:
        request: Django 请求对象,支持 ``status`` 与 ``type`` 查询参数。

    Returns:
        渲染后的反馈列表页;最多展示 200 条。
    """
    qs, status, ftype = _feedback_queryset(request)
    return render(request, "ops/feedback.html", {
        "feedbacks": qs, "status": status, "ftype": ftype,
        "types": FeedbackType.choices,
    })


@require_POST
@staff_required
def feedback_handle(request, feedback_id):
    """把一条反馈标记为已处理。

    已处理的反馈不会重复改写备注与处理人。

    Args:
        request: Django 请求对象,POST 可带 ``note`` 作为处理备注。
        feedback_id: 反馈主键。

    Returns:
        反馈表格的 HTMX 局部片段。
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
    """聊天图片抽审列表,按时间倒序最多 120 条。

    Args:
        request: Django 请求对象,支持 ``user`` 查询参数(按发送者过滤)、
            ``reported=1``(只看最近 7 天被举报过的发送者);每次浏览写一条审计。

    Returns:
        渲染后的聊天图片表格页。
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
    """删除一张聊天图片:删原图与缩略图文件,行保留并记审计。

    Args:
        request: Django 请求对象。
        image_id: 聊天图片主键。

    Returns:
        刷新后的表格局部片段。
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
    """聊天语音抽审列表,按时间倒序最多 120 条。

    Args:
        request: Django 请求对象,支持 ``user`` 查询参数(按发送者过滤)、
            ``reported=1``(只看最近 7 天被举报过的发送者);每次浏览写一条审计。

    Returns:
        渲染后的聊天语音表格页。
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
    """删除一条聊天语音:删文件,行保留并记审计。

    Args:
        request: Django 请求对象。
        voice_id: 聊天语音主键。

    Returns:
        刷新后的表格局部片段。
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

    Args:
        request: Django 请求对象;筛选参数 ``status``(active/disabled/all)与
            ``q``(手机号或备注模糊匹配)优先取 POST,再退回 GET ——
            HTMX 局部刷新的 POST 里也带着当前筛选,刷新后不会跳回默认视图。

    Returns:
        模板上下文字典;``registered`` 是「这些号码里哪些已经注册了账号」的集合,
        用来提醒运营「加了号还没人用过」和「这个号已经有账号了」;``events`` 是
        最近 ``ALLOWLIST_EVENT_LIMIT`` 条操作流水,号码与操作人都在这里脱敏。
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

    Args:
        request: Django 请求对象。
        error: 需要回显的错误文案;``None`` 表示无错误。
        notice: 操作成功的提示文案;``None`` 表示无提示。

    Returns:
        名单面板的局部片段响应。
    """
    ctx = _allowlist_context(request)
    ctx["error"] = error
    ctx["notice"] = notice
    return render(request, "ops/partials/allowlist_panel.html", ctx)


@staff_required
def allowlist_page(request):
    """准入名单管理页:列表 + 加号表单 + 启用/停用。

    为什么这个页面存在(B-1c):本项目不接短信商,固定验证码 + 名单是**长期机制**,
    「加一个人」不能靠 SSH 改 `.env` 再重启 gunicorn —— 那既容易改错(一个逗号
    就把所有人挡在外面),也无法回答「谁加的、为什么加」。

    Args:
        request: Django 请求对象,支持 ``status`` 与 ``q`` 查询参数。

    Returns:
        渲染后的名单页。
    """
    return render(request, "ops/allowlist.html", _allowlist_context(request))


@require_POST
@staff_required
def allowlist_add(request):
    """把一个手机号加进准入名单;已停用的号码重复提交视为「重新启用」。

    三种情形分别留一条流水(R4-B2):

    1. 库里没有这个号 → 新建,写 ``add``;
    2. 库里有但已停用 → 重新启用,写 ``enable``;
    3. 本来就在启用,只是改了备注 → **不写**流水:准入面没变,写进去只是噪声,
       会把「谁被放进来 / 谁被拿掉」这类真正要紧的记录埋掉。

    写库后立刻清名单快照缓存,所以该号码**下一次请求**就能登录,不用重启 web。

    Args:
        request: Django 请求对象,POST 需带 ``phone``,可选 ``note``。

    Returns:
        名单面板的局部片段,带 ``notice`` 或 ``error``。
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
    """启用/停用一个号码;停用立刻生效(该号码下一次发码即 403)。

    只改 ``is_active``,不删记录 —— 名单本身就是安全边界,「谁曾经被放进来、
    什么时候被拿掉」要留得住:每次切换都写一条 ``enable`` / ``disable`` 流水。

    Args:
        request: Django 请求对象。
        entry_id: 名单记录主键。

    Returns:
        名单面板的局部片段,带 ``notice``。
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
