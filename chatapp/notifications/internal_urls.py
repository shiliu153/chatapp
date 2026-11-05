"""``/internal/`` 的路由表:只给 imserver 这类内部调用方用。

注意事项:
    这里的接口**不在 /api/v1 下**,因此不受 ``ApiDocsCoverageTests`` 的接口文档
    门禁约束,也不进 ``docs/api/openapi.yml``;契约写在 ``docs/ops/push.md``。
    访问控制靠共享密钥 HMAC(见 ``notifications/internal.py``),不靠登录态。
"""

from django.urls import path

from . import internal

urlpatterns = [
    path("push/new-message", internal.new_message),
]
