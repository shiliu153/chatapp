"""``/internal/`` 的路由表:只给 imserver 这类内部调用方用。

注意事项:
    这里的接口**不在 /api/v1 下**,因此不受 ``ApiDocsCoverageTests`` 的接口文档
    门禁约束,也不进 ``docs/api/openapi.yml``;契约写在 ``docs/ops/push.md``。
    访问控制靠共享密钥 HMAC(见 ``notifications/internal.py``),不靠登录态。

文件信息:
    文件名称          notifications/internal_urls.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.urls import path

from . import internal

urlpatterns = [
    path("push/new-message", internal.new_message),
]
