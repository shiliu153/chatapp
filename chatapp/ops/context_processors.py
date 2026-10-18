"""审核台的模板上下文处理器:给导航栏提供待办数量角标。

设计要点:
    只对 ``is_staff`` 账号查库 —— 普通请求(含 App 接口)不会因此多出三条 COUNT,
    这是把它放在全局 context processor 里的前提。
"""

from feed.models import PostReport
from moderation.models import Report, ReportStatus
from users.models import Photo, PhotoStatus


def ops_badges(request):
    """提供审核台导航栏的待办数量。

    Args:
        request: Django 请求对象。

    Returns:
        含三类待办数量的字典;非运营账号返回空字典(模板里取不到即为空)。
    """
    if not (request.user.is_authenticated and request.user.is_staff):
        return {}
    return {
        "pending_report_count": Report.objects.filter(status=ReportStatus.PENDING).count(),
        "pending_photo_count": Photo.objects.filter(status=PhotoStatus.PENDING).count(),
        "pending_post_report_count": PostReport.objects.filter(
            status=ReportStatus.PENDING).count(),
    }
