"""请求追踪 ID:HTTP 中间件写入,日志 Filter 读取,Celery 任务随消息 header 传递。"""

import contextvars
import logging

_request_id = contextvars.ContextVar("request_id", default=None)


def set_request_id(value: str | None) -> None:
    """设置当前上下文的请求 ID。

    Args:
        value: 请求 ID;传 ``None`` 表示清理。
    """
    _request_id.set(value)


def current_request_id() -> str | None:
    """读取当前上下文的请求 ID。

    Returns:
        当前请求 ID;不在请求上下文中时返回 ``None``。
    """
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """把当前请求 ID 塞进每条日志记录(没有则 '-');日志格式里用 %(request_id)s 引用。"""

    def filter(self, record):
        """给日志记录补上 ``request_id`` 字段。

        Args:
            record: 待输出的日志记录。

        Returns:
            恒为 ``True``,即不拦截任何日志。
        """
        record.request_id = current_request_id() or "-"
        return True
