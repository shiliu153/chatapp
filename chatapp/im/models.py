"""IM 应用的数据模型占位:本应用目前没有本地表。

消息与 IM 账号都存在腾讯云侧,Django 这边只有跨栈约定 ``u{user_id}``
(见 ``accounts.models.User.im_user_id``)与 ``im/tasks.py`` 的副作用任务。
"""

from django.db import models
