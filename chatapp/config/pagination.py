"""列表接口统一分页约定:LimitOffset(参数 limit/offset,响应 count/next/previous/results)。

文件信息:
    文件名称          config/pagination.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from rest_framework.pagination import LimitOffsetPagination


class DefaultLimitOffsetPagination(LimitOffsetPagination):
    """列表接口的默认分页:默认每页 20 条,单页上限 100 条。"""

    default_limit = 20
    max_limit = 100
