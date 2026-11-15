"""请求追踪 ID:HTTP 中间件写入,日志 Filter 读取,Celery 任务随消息 header 传递。"""

import contextvars
import logging

_request_id = contextvars.ContextVar("request_id", default=None)


def set_request_id(value: str | None) -> None:
    """设置当前上下文的请求 ID。

    参数说明:
        value: 请求 ID;传 ``None`` 表示清理。

    返回参数:
        无返回值。

    使用示例:
        ``set_request_id(request_id)``(见 ``config/middleware.py::RequestIdMiddleware``);
        任务结束清理写 ``set_request_id(None)``。

    备注信息:
        值存在 ``contextvars`` 里,只对当前线程 / 协程可见,不会泄漏到其它请求。
    """
    _request_id.set(value)


def current_request_id() -> str | None:
    """读取当前上下文的请求 ID。

    返回参数:
        当前请求 ID;不在请求上下文中时返回 ``None``。

    使用示例:
        ``request_id = current_request_id()``(见 ``config/celery.py::_inject_request_id``)

    备注信息:
        异步任务、后台脚本里没有请求上下文,拿到的是 ``None``;调用方需兜底成 ``-``。
    """
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """把当前请求 ID 塞进每条日志记录(没有则 '-');日志格式里用 %(request_id)s 引用。"""

    def filter(self, record):
        """给日志记录补上 ``request_id`` 字段。

        参数说明:
            record: 待输出的日志记录。

        返回参数:
            恒为 ``True``,即不拦截任何日志。

        使用示例:
            ``"filters": {"request_id": {"()": "config.request_id.RequestIdFilter"}}``
            (见 ``config/settings.py`` 的 ``LOGGING``)

        备注信息:
            没有请求上下文时写入 ``-``,日志格式 ``%(request_id)s`` 因此不会 KeyError。
        """
        record.request_id = current_request_id() or "-"
        return True
