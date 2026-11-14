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

文件信息:
    文件名称          config/celery.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
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

    参数说明:
        无。

    返回参数:
        固定字符串 ``pong``,用于确认 worker 可达。

    使用示例:
        ``ping.delay().get(timeout=5)``

    备注信息:
        不查库、不碰 broker 之外的外部依赖,只用来区分「worker 没起」与「任务本身有 bug」。
    """
    return "pong"


def _inject_request_id(headers=None, **kwargs):
    """入队时把当前请求 ID 带进消息 header(worker 侧日志可用同一 ID 对账)。

    备注信息:
        用 ``setdefault`` 写入,调用方已显式指定 ``request_id`` 时不覆盖;
        当前上下文里没有 ID(如定时任务自己入队)则什么都不做。
    """
    request_id = current_request_id()
    if request_id and isinstance(headers, dict):
        headers.setdefault("request_id", request_id)


def _bind_request_id(task=None, **kwargs):
    """任务执行前,把消息 header 里的请求 ID 绑定到 worker 的上下文变量。

    备注信息:
        header 缺失或不是字符串时绑定 ``None``,任务日志因此没有 ``request_id`` 字段,
        但不会报错;结束时的清理由 ``task_postrun`` 负责。
    """
    headers = getattr(getattr(task, "request", None), "headers", None) or {}
    set_request_id(headers.get("request_id"))


def _clear_request_id(**kwargs):
    """任务结束后清理上下文变量,避免请求 ID 串到同 worker 的下一个任务。

    备注信息:
        无条件置 ``None``;无论任务成功还是抛异常,``task_postrun`` 都会触发,
        所以不需要额外兜底。
    """
    set_request_id(None)


before_task_publish.connect(_inject_request_id)
task_prerun.connect(_bind_request_id)
task_postrun.connect(_clear_request_id)
