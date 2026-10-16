"""项目根路由表:admin 后台、``/api/v1`` 接口、``/ops`` 审核台,以及开发期的媒体文件。

注意事项:
    ``/api/v1`` 下的接口另见 ``config/api_urls.py``;``/ops`` 不在 ``/api/v1`` 下,
    因此不受 ``ApiDocsCoverageTests`` 的接口文档门禁约束。
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("config.api_urls")),
    path("ops/", include("ops.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
