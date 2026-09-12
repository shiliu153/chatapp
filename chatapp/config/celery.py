"""Celery 应用:broker/配置全部从 Django settings(namespace=CELERY)读。"""

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
    return "pong"


# ⚠️ 用 signal.connect(函数) 显式注册,别用 @装饰器:Celery 的 Signal.connect
# 返回 signal 本身,装饰器会把函数名绑到 signal 上,函数就没法单独调用/测试了。


def _inject_request_id(headers=None, **kwargs):
    """入队时把当前请求 ID 带进消息 header(worker 侧日志可用同一 ID 对账)。"""
    request_id = current_request_id()
    if request_id and isinstance(headers, dict):
        headers.setdefault("request_id", request_id)


def _bind_request_id(task=None, **kwargs):
    headers = getattr(getattr(task, "request", None), "headers", None) or {}
    set_request_id(headers.get("request_id"))


def _clear_request_id(**kwargs):
    set_request_id(None)


before_task_publish.connect(_inject_request_id)
task_prerun.connect(_bind_request_id)
task_postrun.connect(_clear_request_id)
