"""项目包入口:安装 PyMySQL 驱动,并保证 Celery 应用在 Django 启动时被导入。

设计要点:
    1. ``pymysql.install_as_MySQLdb()`` 把纯 Python 的 PyMySQL 注册成 MySQLdb,
       从而不依赖需要编译的 mysqlclient;
    2. 导入 ``celery_app`` 是 Celery 官方要求的写法:只有 Django 启动时就导入应用,
       ``@shared_task`` 才会绑定到本项目实例,而不是绑定到 Celery 的默认应用。
"""

import pymysql

pymysql.install_as_MySQLdb()

from .celery import app as celery_app

__all__ = ("celery_app",)
