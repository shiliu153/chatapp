"""日志格式:开发用可读文本,生产用单行 JSON(便于 Loki/ES 按字段检索)。

为什么自己写而不是引 ``python-json-logger``:只有 40 行,字段完全可控,
也避免为一个 formatter 增加依赖与 lock 文件变更。

字段约定(JSON 模式):
    ``ts`` / ``level`` / ``logger`` / ``message`` / ``request_id`` 恒定存在;
    ``user_id`` / ``route`` / ``status`` / ``duration_ms`` / ``sql_count`` 由
    ``RequestIdMiddleware`` 通过 ``extra`` 传入,存在才输出。

关联文档:
    - 观测部署:docs/ops/observability.md
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
    """

    #: 允许从 ``record`` 里透出的业务字段。
    EXTRA_FIELDS = ("user_id", "route", "status", "duration_ms", "sql_count")

    def format(self, record: logging.LogRecord) -> str:
        """渲染一条日志。

        Args:
            record: 日志记录。

        Returns:
            单行 JSON 字符串(不含换行,异常堆栈已转义)。
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
