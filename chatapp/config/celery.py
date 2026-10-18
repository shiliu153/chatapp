"""Celery 应用:broker 与全部配置从 Django settings 读取(``namespace="CELERY"``)。

设计要点:
    1. 配置来源统一走 Django settings,``.env`` 里对应的键**不能**带 ``CELERY_``
       前缀(原因见 ``config/settings.py`` 中 ``CELERY_BROKER_URL`` 的说明);
    2. 请求 ID 通过消息 header 跨进程传递:入队时注入、worker 取任务前绑定、
       任务结束后清理,使 worker 日志能与触发它的 HTTP 请求对上账。

注意事项:
    注册信号必须用 ``signal.connect(函数)`` 显式调用,不能用 ``@装饰器`` ——
    ``Signal.connect`` 返回的是 signal 自身,装饰器会把函数名绑定到 signal 上,
    函数就无法被单独调用与测试。
"""

import os

from celery import Celery
from celery.signals import before_task_publish, task_postrun, task_prerun

from .request_id import current_request_id, set_request_id

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

app = Celery("chatapp")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.task
def ping():
    """连通性探针。

    Returns:
        固定字符串 ``pong``,用于确认 worker 可达。
    """
    return "pong"


def _inject_request_id(headers=None, **kwargs):
    """入队时把当前请求 ID 带进消息 header(worker 侧日志可用同一 ID 对账)。"""
    request_id = current_request_id()
    if request_id and isinstance(headers, dict):
        headers.setdefault("request_id", request_id)


def _bind_request_id(task=None, **kwargs):
    """任务执行前,把消息 header 里的请求 ID 绑定到 worker 的上下文变量。

    Args:
        task: Celery 任务实例(由 ``task_prerun`` 信号传入)。
        **kwargs: 信号附带的其余参数,忽略。
    """
    headers = getattr(getattr(task, "request", None), "headers", None) or {}
    set_request_id(headers.get("request_id"))


def _clear_request_id(**kwargs):
    """任务结束后清理上下文变量,避免请求 ID 串到同 worker 的下一个任务。

    Args:
        **kwargs: 信号附带的参数,忽略。
    """
    set_request_id(None)


before_task_publish.connect(_inject_request_id)
task_prerun.connect(_bind_request_id)
task_postrun.connect(_clear_request_id)
