"""Django admin 中的滑卡与配对记录管理。

两个模型都只做只读性质的查看:滑卡与配对由业务写入,
后台不提供编辑入口,避免手工改数据破坏唯一约束与幂等语义。

文件信息:
    文件名称          discovery/admin.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from django.contrib import admin

from .models import Match, Swipe


@admin.register(Swipe)
class SwipeAdmin(admin.ModelAdmin):
    """滑卡记录的后台管理。"""

    list_display = ("id", "swiper", "target", "action", "created_at")
    list_filter = ("action",)


@admin.register(Match)
class MatchAdmin(admin.ModelAdmin):
    """配对记录的后台管理。"""

    list_display = ("id", "user_a", "user_b", "created_at")
