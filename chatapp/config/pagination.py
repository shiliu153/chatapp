"""列表接口统一分页约定:LimitOffset(参数 limit/offset,响应 count/next/previous/results)。"""

from rest_framework.pagination import LimitOffsetPagination


class DefaultLimitOffsetPagination(LimitOffsetPagination):
    default_limit = 20
    max_limit = 100
