#!/usr/bin/env python
"""Django 命令行入口:把 ``manage.py <子命令>`` 转发给 Django 的管理命令框架。

文件信息:
    文件名称          manage.py
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
import sys


def main():
    """解析命令行并把控制权交给 Django。

    参数说明:
        无；子命令与选项从 ``sys.argv`` 读取。

    返回参数:
        无返回值；``execute_from_command_line`` 内部会按需 ``sys.exit``。

    使用示例:
        ``python manage.py migrate``

    备注信息:
        ``DJANGO_SETTINGS_MODULE`` 用 ``setdefault`` 设置，因此外部已指定时以外部为准
        （测试与 CI 会指向不同的 settings）。
    """
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
