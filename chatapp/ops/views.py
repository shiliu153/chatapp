"""运营审核台:举报处理、照片审核、用户管理、封禁日志与广场治理。

设计要点:
    1. **用 Django 模板 + HTMX 局部刷新,不用 DRF**:审核台是内部工具,追求开发速度。
       全部接口挂在 ``/ops/`` 前缀下,**不在** ``/api/v1`` 内,因此不受
       ``ApiDocsCoverageTests`` 的接口文档门禁约束;
    2. **鉴权靠 ``@staff_required`` 装饰器**:未登录跳登录页,非 ``is_staff`` 直接 403;
    3. **封禁与解封统一走 ``_apply_status_change``**:审计与 IM 通知都复用
       ``moderation.services.log_ban_change``,与 Django admin 完全同源。

注意事项:
    解封时必须先把状态改回 ``INCOMPLETE`` 再调 ``refresh_status()`` ——
    封禁态不参与完善度重算,不先脱离封禁态就永远算不回真实状态。
"""

from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from feed.models import Post, PostReport
from feed.services import delete_post
from feedback.models import Feedback, FeedbackStatus, FeedbackType
from moderation.models import (BanAction, BanLog, Block, Report, ReportStatus,
                               ReportType)
from moderation.services import log_ban_change, notify_report_handled
from users.models import Photo, PhotoStatus, Profile, ProfileStatus
from users.services import review_photos

from .decorators import staff_required


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
    ids = set(request.POST.getlist("ids"))
    action = request.POST.get("action")
    status_map = {"approve": PhotoStatus.APPROVED, "reject": PhotoStatus.REJECTED}
    skipped = 0
    if action in status_map and ids:
        # 任何状态都可再审(已通过可撤回驳回);skipped 只统计页面陈旧、照片已被删除的 id
        targets = Photo.objects.filter(pk__in=ids)
        skipped = len(ids) - targets.count()
        review_photos(targets, status_map[action], request.user)
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
