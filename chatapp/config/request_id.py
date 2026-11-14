"""请求追踪 ID:HTTP 中间件写入,日志 Filter 读取,Celery 任务随消息 header 传递。

文件信息:
    文件名称          config/request_id.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

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
        ``set_request_id(value)``

    备注信息:
        写入的是 ``ContextVar``,作用域限于当前线程或协程;
        跨线程/跨任务沿用必须显式把值带过去,不会自动传播。
    """
    _request_id.set(value)


def current_request_id() -> str | None:
    """读取当前上下文的请求 ID。

    参数说明:
        无。

    返回参数:
        当前请求 ID;不在请求上下文中时返回 ``None``。

    使用示例:
        ``rid = current_request_id()``

    备注信息:
        只读取不生成:没有中间件写入时恒为 ``None``,需要非空值的地方自行兜底成 ``-``。
    """
    return _request_id.get()


class RequestIdFilter(logging.Filter):
    """把当前请求 ID 塞进每条日志记录(没有则 '-');日志格式里用 %(request_id)s 引用。

    参数说明:
        无(继承 ``logging.Filter``,不自定义 ``__init__``)。

    返回参数:
        过滤器实例本身,交给 ``logging.config`` 挂到 handler 或 logger 上。

    使用示例:
        ``logging.getLogger("chatapp").addFilter(RequestIdFilter())``

    备注信息:
        格式串里只要出现 ``%(request_id)s`` 就必须挂上它,否则该条日志会因
        缺少字段而格式化失败;没有请求上下文时写 ``-``。
    """

    def filter(self, record):
        """给日志记录补上 ``request_id`` 字段。

        参数说明:
            record: 待输出的日志记录。

        返回参数:
            恒为 ``True``,即不拦截任何日志。

        使用示例:
            ``RequestIdFilter().filter(record)``

        备注信息:
            必须返回真值:返回 ``False`` 会让这条记录被丢弃;
            字段值来自 ``current_request_id()``,取不到时写 ``-``。
        """
        record.request_id = current_request_id() or "-"
        return True
