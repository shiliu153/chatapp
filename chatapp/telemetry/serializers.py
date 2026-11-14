"""客户端错误上报的入参校验。

字段全部有长度上限:这个接口匿名可调,不设上限等于给日志写入开了一个放大器
(一条 10MB 的堆栈就能把日志盘打满)。

文件信息:
    文件名称          telemetry/serializers.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from rest_framework import serializers

#: 平台取值。新增端(如小程序)时在这里加,前端同步改 ``platform`` 字段。
PLATFORMS = ("web", "app")


class ClientErrorSerializer(serializers.Serializer):
    """一条客户端错误上报。

    Attributes:
        platform: 端标识,``web`` 或 ``app``。
        message: 错误摘要(必填)。
        stack: 堆栈文本,按 4KB 截断足够定位问题。
        route: 出错的页面/路由,便于按页面聚合。
        app_version: 客户端版本号。
        request_id: 客户端最后收到的 ``X-Request-Id``,用来和服务端日志对账。
    """

    platform = serializers.ChoiceField(choices=PLATFORMS)
    message = serializers.CharField(max_length=500)
    stack = serializers.CharField(max_length=8000, required=False, allow_blank=True, default="")
    route = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    app_version = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    request_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
