"""审核台的模板上下文处理器:给导航栏提供待办数量角标。

设计要点:
    只对 ``is_staff`` 账号查库 —— 普通请求(含 App 接口)不会因此多出三条 COUNT,
    这是把它放在全局 context processor 里的前提。

文件信息:
    文件名称          ops/context_processors.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from feed.models import PostReport
from feedback.models import Feedback, FeedbackStatus
from moderation.models import Report, ReportStatus
from users.models import Photo, PhotoStatus


def ops_badges(request):
    """提供审核台导航栏的待办数量。

    参数说明:
        request: Django 请求对象。

    返回参数:
        含四类待办数量的字典(举报、照片、动态举报、意见反馈);非运营账号返回空字典。

    使用示例:
        ``ops_badges(request)``

    备注信息:
        只有「已登录且 ``is_staff``」才查库,其余情况直接返回空字典,模板里这些键
        因此不存在(取到即为空字符串),不会影响非运营页面的渲染;
        四个计数都是整表 COUNT,没有可复用的已取数据。
    """
    if not (request.user.is_authenticated and request.user.is_staff):
        return {}
    return {
        "pending_report_count": Report.objects.filter(status=ReportStatus.PENDING).count(),
        "pending_photo_count": Photo.objects.filter(status=PhotoStatus.PENDING).count(),
        "pending_post_report_count": PostReport.objects.filter(
            status=ReportStatus.PENDING).count(),
        "pending_feedback_count": Feedback.objects.filter(
            status=FeedbackStatus.PENDING).count(),
    }
