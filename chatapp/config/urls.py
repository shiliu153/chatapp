"""项目根路由表:admin 后台、``/api/v1`` 接口、``/internal`` 内部事件、``/ops`` 审核台,
以及开发期的媒体文件。

注意事项:
    ``/api/v1`` 下的接口另见 ``config/api_urls.py``;``/ops`` 与 ``/internal`` 都不在
    ``/api/v1`` 下,因此不受 ``ApiDocsCoverageTests`` 的接口文档门禁约束
    (``/internal`` 走 HMAC 共享密钥,契约见 ``docs/ops/push.md``)。

文件信息:
    文件名称          config/urls.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

from .metrics import metrics_view

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/v1/", include("config.api_urls")),
    # imserver → Django 的内部事件(离线新消息推送),签名口径与 /api/v1 无关
    path("internal/", include("notifications.internal_urls")),
    path("ops/", include("ops.urls")),
    # Prometheus 抓取入口:不在 /api/v1 下(不纳入接口文档门禁),由 METRICS_TOKEN
    # 或回环来源限制;nginx 侧应显式拒绝公网访问(见 deploy/nginx)。
    path("metrics", metrics_view),
]

# 非 DRF 路径(中间件、模板视图)的 500 兜底:接口前缀返回 JSON 错误契约,
# 避免 DB 故障时客户端拿到 HTML 500 页(P2-4)。
handler500 = "config.exceptions.server_error"

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
