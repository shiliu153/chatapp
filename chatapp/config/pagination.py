"""列表接口统一分页约定:LimitOffset(参数 limit/offset,响应 count/next/previous/results)。"""

from rest_framework.pagination import LimitOffsetPagination


class DefaultLimitOffsetPagination(LimitOffsetPagination):
    """列表接口的默认分页:默认每页 20 条,单页上限 100 条。"""

    default_limit = 20
    max_limit = 100
