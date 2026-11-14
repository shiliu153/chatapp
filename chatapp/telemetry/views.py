"""客户端错误上报接口。

关联文档:
    - 接口契约:docs/api/telemetry.md

设计要点:
    1. **本 logger 不参与告警。** ``chatapp.client_error`` 只作为 Loki 的检索入口,
       任何 Alertmanager 规则都不许挂在它上面 —— 前端报错量与后端健康度不是一回事,
       同一行错误在渲染循环里一秒能刷几十条,接进告警只会制造噪音。
       要告警看 ``client_errors_total{platform}`` 的突增。
    2. **日志按 platform + message 采样**:同一行错误 60 秒内只落一条,
       避免「渲染循环抛异常」把磁盘与 Loki 的查询窗口一起打爆。
    3. **采样失败 fail-open**:Redis 不可用时照常写日志 —— 宁可多写,
       也不能在故障期间把最有价值的白屏 / 崩溃信号丢掉。

文件信息:
    文件名称          telemetry/views.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import hashlib
import logging

from django.core.cache import cache
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from config import metrics

from .serializers import ClientErrorSerializer
from .throttles import ClientErrorThrottle

logger = logging.getLogger("chatapp.client_error")

# 同一 platform + message 的日志采样窗口(秒):窗口内只落一条。
CLIENT_ERROR_SAMPLE_SECONDS = 60


def _should_log(platform: str, message: str) -> bool:
    """判断本次上报是否该落日志(同一 platform + message 在窗口内只落一条)。

    参数说明:
        platform: 上报端,``web`` 或 ``app``。
        message: 错误摘要;与 platform 一起构成采样键。

    返回参数:
        True 表示这次该写日志。``cache.add`` 抛异常时**返回 True**(fail-open)。

    使用示例:
        ``if _should_log("web", "TypeError: ..."):``

    备注信息:
        采样只影响日志:``metrics.CLIENT_ERRORS`` 仍然每次请求都累加 —— 计数器要反映
        真实上报量,否则突增告警会随采样率一起失真。
        Redis 挂了不能让错误日志跟着一起消失,因此异常时 fail-open 照常落日志。
    """
    # 用 \x00 分隔:platform 与 message 都可能含空格/换行,裸拼接会让 ("a b","c") 与
    # ("a","b c") 撞成同一个采样键。
    digest = hashlib.sha256(f"{platform}\x00{message}".encode()).hexdigest()[:32]
    try:
        return bool(cache.add(f"clienterr:sample:{digest}", 1, CLIENT_ERROR_SAMPLE_SECONDS))
    except Exception:
        logger.debug("客户端错误采样失败,本次照常落日志", exc_info=True)
        return True


@extend_schema(request=ClientErrorSerializer, responses={204: None})
@api_view(["POST"])
@permission_classes([AllowAny])
@throttle_classes([ClientErrorThrottle])
def report_client_error(request):
    """接收一条前端未捕获异常(POST /api/v1/client-errors)。

    参数说明:
        request: DRF 请求对象,body 见 ``ClientErrorSerializer``。

    返回参数:
        204 空响应(上报是 fire-and-forget,不回业务数据)。

    使用示例:
        ``POST /api/v1/client-errors`` body ``{"platform": "web", "message": "TypeError: ..."}``

    备注信息:
        允许匿名:登录页白屏、启动即崩这类最有价值的错误发生时,客户端还没有令牌。
        日志字段名避开了 ``message`` / ``levelname`` 等 LogRecord 保留字,否则 logging 会抛异常;
        级别用 warning 是因为本 logger 不参与告警(见模块 docstring),仅为在 Loki 里好筛。
        字段非法回 400;日志按 platform + message 采样,指标 ``CLIENT_ERRORS`` 每次照常累加。
    """
    serializer = ClientErrorSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data

    # 字段名不能叫 message / levelname 这类 LogRecord 保留字,否则 logging 会抛异常。
    # 用 warning 而非 error:本 logger 不参与告警(见模块 docstring),级别只为在 Loki 里好筛。
    if _should_log(data["platform"], data["message"]):
        logger.warning(
            "client_error",
            extra={
                "platform": data["platform"],
                "client_message": data["message"],
                "client_stack": data["stack"] or "-",
                "client_route": data["route"] or "-",
                "app_version": data["app_version"] or "-",
                "client_request_id": data["request_id"] or "-",
                "user_agent": (request.META.get("HTTP_USER_AGENT") or "-")[:300],
                "user_id": request.user.id if request.user.is_authenticated else None,
            },
        )
    metrics.CLIENT_ERRORS.labels(platform=data["platform"]).inc()
    return Response(status=204)
