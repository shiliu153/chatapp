"""日志格式:开发用可读文本,生产用单行 JSON(便于 Loki/ES 按字段检索)。

为什么自己写而不是引 ``python-json-logger``:只有 40 行,字段完全可控,
也避免为一个 formatter 增加依赖与 lock 文件变更。

字段约定(JSON 模式):
    ``ts`` / ``level`` / ``logger`` / ``message`` / ``request_id`` 恒定存在;
    ``user_id`` / ``route`` / ``status`` / ``duration_ms`` / ``sql_count`` 由
    ``RequestIdMiddleware`` 通过 ``extra`` 传入,存在才输出;
    ``platform`` / ``app_version`` / ``user_agent`` / ``client_*`` 由客户端错误上报
    接口(``telemetry/views.py``)传入。

关联文档:
    - 观测部署:docs/ops/observability.md

文件信息:
    文件名称          config/logging.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import json
import logging
from datetime import datetime, timezone


class JsonFormatter(logging.Formatter):
    """把日志记录渲染成单行 JSON。

    设计要点:
        1. 只输出白名单字段,避免把任意 ``extra`` 泄进日志(可能有手机号);
        2. 异常用 ``exc`` 字段带完整堆栈,而不是拼进 message;
        3. 时间用 ISO8601 带时区,方便跨时区排查。

    参数说明:
        无(继承 ``logging.Formatter``,不自定义 ``__init__``;格式串由 ``LOGGING`` 配置传入)。

    返回参数:
        格式化器实例本身,交给 ``logging.config`` 挂到 handler 上。

    使用示例:
        ``"formatter": {"()": "config.logging.JsonFormatter"}``

    备注信息:
        要在 ``settings.LOGGING`` 的 ``formatters`` 里按 ``()`` 工厂形式引用才会被实例化;
        白名单字段见 ``EXTRA_FIELDS``,新增字段必须同时改类属性与模块头的字段约定。
    """

    #: 允许从 ``record`` 里透出的业务字段。
    #:
    #: ``platform`` / ``app_version`` / ``user_agent`` / ``client_*`` 来自
    #: ``POST /api/v1/client-errors``(前端未捕获异常);字段名刻意避开
    #: ``message`` / ``levelname`` 等 LogRecord 保留字。
    EXTRA_FIELDS = ("user_id", "route", "status", "duration_ms", "sql_count",
                    "platform", "app_version", "user_agent", "client_message",
                    "client_stack", "client_route", "client_request_id")

    def format(self, record: logging.LogRecord) -> str:
        """渲染一条日志。

        参数说明:
            record: 日志记录。

        返回参数:
            单行 JSON 字符串(不含换行,异常堆栈已转义)。

        使用示例:
            ``JsonFormatter().format(record)``

        备注信息:
            ``ts`` / ``level`` / ``logger`` / ``message`` / ``request_id`` 恒定输出,
            ``request_id`` 缺失时写 ``-``;``EXTRA_FIELDS`` 里值为 ``None`` 的字段不输出。
            ``ensure_ascii=False`` 让中文保持原样,便于直接检索。
        """
        payload = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        for field in self.EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)
