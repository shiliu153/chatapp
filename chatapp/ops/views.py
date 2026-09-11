from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render

from moderation.models import BanLog, Report, ReportStatus, ReportType

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
