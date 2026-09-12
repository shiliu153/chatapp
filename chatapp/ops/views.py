from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from accounts.models import User
from feed.models import Post, PostReport
from feed.services import delete_post
from moderation.models import (BanAction, BanLog, Block, Report, ReportStatus,
                               ReportType)
from moderation.services import log_ban_change, notify_report_handled
from users.models import Photo, PhotoStatus, Profile, ProfileStatus
from users.services import review_photos

from .decorators import staff_required


@staff_required
def home(request):
    return redirect("ops:reports")


@staff_required
def reports_list(request):
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
    report = get_object_or_404(
        Report.objects.select_related("reporter", "target", "handled_by"), pk=report_id)
    return render(request, "ops/report_detail.html", _report_context(report))


def _report_context(report):
    """举报详情页上下文;Task 3 的 HTMX 局部刷新也复用它。"""
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
    """ban_light / ban_heavy / unban。封禁审计与踢 IM 统一走 log_ban_change(与 admin 同源)。"""
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
    status = request.GET.get("status", PhotoStatus.PENDING)
    qs = Photo.objects.select_related("user", "reviewed_by").order_by("-created_at")
    if status in PhotoStatus.values:
        qs = qs.filter(status=status)
    return render(request, "ops/photos.html",
                  {"photos": qs[:120], "status": status, "skipped": 0})


@require_POST
@staff_required
def photo_review(request):
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
    q = request.GET.get("q", "").strip()
    results = []
    if q:
        results = (User.objects.filter(Q(phone=q) | Q(profile__nickname__icontains=q))
                   .select_related("profile").order_by("id")[:50])
    return render(request, "ops/users_search.html", {"q": q, "results": results})


@staff_required
def user_detail(request, user_id):
    user = get_object_or_404(User.objects.select_related("profile"), pk=user_id)
    return render(request, "ops/user_detail.html", _user_context(user))


def _user_context(user):
    """用户详情页上下文;Task 7 的封禁局部刷新也复用它。"""
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
    return (Post.objects.select_related("author__profile")
            .prefetch_related("images")
            .annotate(like_count=Count("likes", distinct=True),
                      comment_count=Count("comments", distinct=True))
            .order_by("-created_at", "-id")[:200])


@staff_required
def posts(request):
    return render(request, "ops/posts.html", {"posts": _posts_queryset()})


@require_POST
@staff_required
def post_delete(request, post_id):
    post = get_object_or_404(Post, pk=post_id)
    delete_post(post)
    return render(request, "ops/partials/posts_table.html", {"posts": _posts_queryset()})


def _post_reports_queryset(status):
    qs = (PostReport.objects.select_related("post__author__profile", "reporter", "handled_by")
          .order_by("-status", "-created_at"))
    if status in ReportStatus.values:
        qs = qs.filter(status=status)
    return qs[:200]


def _render_post_reports(request):
    status = (request.POST.get("status") or request.GET.get("status")
              or ReportStatus.PENDING)
    return render(request, "ops/partials/post_reports_table.html",
                  {"reports": _post_reports_queryset(status), "status": status})


@staff_required
def post_reports(request):
    status = request.GET.get("status", ReportStatus.PENDING)
    return render(request, "ops/post_reports.html", {
        "reports": _post_reports_queryset(status), "status": status,
        "types": ReportType.choices,
    })


@require_POST
@staff_required
def post_report_handle(request, report_id):
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
