from moderation.models import Report, ReportStatus
from users.models import Photo, PhotoStatus


def ops_badges(request):
    if not (request.user.is_authenticated and request.user.is_staff):
        return {}
    return {
        "pending_report_count": Report.objects.filter(status=ReportStatus.PENDING).count(),
        "pending_photo_count": Photo.objects.filter(status=PhotoStatus.PENDING).count(),
    }
