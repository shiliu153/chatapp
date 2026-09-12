"""请求追踪 ID:HTTP 中间件写入,日志 Filter 读取,Celery 任务随消息 header 传递。"""

import contextvars
import logging

_request_id = contextvars.ContextVar("request_id", default=None)


def set_request_id(value: str | None) -> None:
    _request_id.set(value)


def current_request_id() -> str | None:
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """把当前请求 ID 塞进每条日志记录(没有则 '-');日志格式里用 %(request_id)s 引用。"""

    def filter(self, record):
        record.request_id = current_request_id() or "-"
        return True
