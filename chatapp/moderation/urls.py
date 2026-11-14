"""举报与拉黑接口的路由。

本文件挂在 ``/api/v1/`` 根前缀下(见 ``config/api_urls.py``);
接口契约见 docs/api/moderation.md。

文件信息:
    文件名称          moderation/urls.py
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

from . import views

urlpatterns = [
    # 举报:只有 POST,幂等(同一被举报人已有待处理举报时返回 200 + 原记录)
    path("reports", views.create_report),
    # 黑名单:GET 读列表、POST 新增拉黑(同路径,限流只算 POST)
    path("blocks", views.blocks),
    # 解除拉黑:DELETE 幂等,没有该条记录也回 204
    path("blocks/<int:user_id>", views.unblock),
]
