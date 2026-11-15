"""imserver → Django 的内部事件入口:离线新消息推送。

为什么要这一层:
    消息是 imserver 直接写进 ``chatapp_im`` 的,Django 根本不知道「有新消息」。
    imserver 在**消息落库之后、目标不在线时**用同一套 HMAC 内部签名回调这里,
    Django 只做三件事:验签 → 入队 → 立刻 202。**这里不做任何第三方调用**,
    真正发推送在 Celery 任务里(``notifications.tasks.send_message_push``)。

签名口径与 ``im/self_client.py``(Django → imserver 方向)完全一致,两边共用
``IM_SELF_INTERNAL_SECRET``::

    signing = f"{timestamp}\\nPOST\\n{path}\\n{body}"

    signature = hmac_sha256_hex(secret, signing)

头:``X-IM-Timestamp``(秒级时间戳)、``X-IM-Signature``。
时间戳偏移超过 ``PUSH_INTERNAL_MAX_SKEW`` 秒直接拒绝(重放窗口)。
幂等靠任务里按 ``msg_id`` 去重 —— 同一事件到两次只会响一次。

这个路径**不在 /api/v1 下**,所以不进 ``docs/api`` 与 OpenAPI 门禁,
契约写在这里与 ``docs/ops/push.md``。
"""

import hashlib
import hmac
import json
import logging
import time

from django.conf import settings
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from . import services

logger = logging.getLogger(__name__)

INTERNAL_PATH = "/internal/push/new-message"
MAX_NICKNAME = 64
MAX_PREVIEW = 200


def _error(status: int, message: str) -> JsonResponse:
    """按项目错误契约返回 ``{"code", "message"}``。

    参数说明:
        status: HTTP 状态码(同时作为 ``code``)。
        message: 中文说明。

    返回参数:
        JSON 响应。

    使用示例:
        ``return _error(401, f"内部签名校验失败:{reason}")``(见本文件 ``new_message``)

    备注信息:
        本路径是普通 Django 视图,不经过 DRF 的全局异常处理器,所以只给 ``code`` 与
        ``message`` 两个字段(不带 ``request_id``);状态码同时充当业务码。
    """
    return JsonResponse({"code": status, "message": message}, status=status)


def signature_for(timestamp: str, path: str, body: str, secret: str) -> str:
    """计算内部调用签名(与 imserver 的 ``hmac_sha256_hex`` 同口径)。

    参数说明:
        timestamp: 秒级时间戳字符串。
        path: 请求路径(不含域名与查询串)。
        body: 原始请求体字符串。
        secret: 共享密钥。

    返回参数:
        小写十六进制 HMAC-SHA256。

    使用示例:
        ``sig = signature_for(ts, path, body, secret)``(见 ``notifications/tests.py`` 的 ``InternalPushEndpointTests._post``)

    备注信息:
        签名串固定三段拼接 ``f"{timestamp}\\nPOST\\n{path}\\n{body}"``,顺序与分隔符
        必须与 imserver 逐字一致,改任意一侧都会 401。
    """
    signing = f"{timestamp}\nPOST\n{path}\n{body}".encode()
    return hmac.new(secret.encode(), signing, hashlib.sha256).hexdigest()


def _verify(request) -> tuple[bool, str]:
    """校验时间戳与签名。

    参数说明:
        request: Django 请求对象。

    返回参数:
        ``(是否通过, 失败原因)``。

    使用示例:
        ``ok, reason = _verify(request)``(见本文件 ``new_message``)

    备注信息:
        失败原因会拼进 401 的 ``message``(密钥未配置 / 缺少签名头 / 时间戳非法 /
        时间戳过期 / 签名不正确),日志里同一份原因也有一份 warning。
    """
    secret = getattr(settings, "IM_SELF_INTERNAL_SECRET", "")
    if not secret:
        return False, "内部密钥未配置"
    timestamp = request.headers.get("X-IM-Timestamp", "")
    signature = request.headers.get("X-IM-Signature", "")
    if not timestamp or not signature:
        return False, "缺少签名头"
    try:
        skew = abs(time.time() - int(timestamp))
    except ValueError:
        return False, "时间戳非法"
    if skew > int(getattr(settings, "PUSH_INTERNAL_MAX_SKEW", 300)):
        return False, "时间戳过期"
    body = request.body.decode("utf-8", errors="replace")
    expected = signature_for(timestamp, INTERNAL_PATH, body, secret)
    if not hmac.compare_digest(expected, signature):
        return False, "签名不正确"
    return True, ""


def _parse(body: str) -> tuple[dict | None, str]:
    """解析并校验事件字段。

    参数说明:
        body: 原始 JSON 字符串。

    返回参数:
        ``(事件字典, 失败原因)``;失败时字典为 ``None``。

    使用示例:
        ``payload, reason = _parse(request.body.decode("utf-8", errors="replace"))``(见本文件 ``new_message``)

    备注信息:
        除字段形状外还挡住三类语义错误:账号 id 非正整数(系统消息不推)、收发双方相同、
        ``msg_id`` 缺失;昵称与预览按 ``MAX_NICKNAME`` / ``MAX_PREVIEW`` 截断。
    """
    try:
        data = json.loads(body)
    except ValueError:
        return None, "请求体不是合法 JSON"
    if not isinstance(data, dict):
        return None, "请求体必须是对象"
    try:
        to_user_id = int(data["to_user_id"])
        from_user_id = int(data["from_user_id"])
    except (KeyError, TypeError, ValueError):
        return None, "to_user_id / from_user_id 缺失或不是整数"
    if to_user_id <= 0 or from_user_id <= 0:
        return None, "账号 id 必须为正整数(系统消息不推)"
    if to_user_id == from_user_id:
        return None, "收发双方相同"
    dedupe_key = data.get("msg_id")
    if dedupe_key in (None, ""):
        return None, "msg_id 缺失"
    return {
        "to_user_id": to_user_id,
        "from_user_id": from_user_id,
        "from_nickname": str(data.get("from_nickname", ""))[:MAX_NICKNAME],
        "preview": str(data.get("preview", ""))[:MAX_PREVIEW],
        "dedupe_key": str(dedupe_key)[:64],
    }, ""


@csrf_exempt
@require_POST
def new_message(request):
    """接收 imserver 的「离线新消息」事件并入队推送(POST /internal/push/new-message)。

    参数说明:
        request: Django 请求对象(JSON body 见 ``docs/ops/push.md``)。

    返回参数:
        202 表示已入队;401 验签失败;400 字段不合法;405 方法不对。

    使用示例:
        ``resp = self._post(body)``(见 ``notifications/tests.py`` 的 ``InternalPushEndpointTests._post``)

    备注信息:
        真实触发方是 imserver 的推送线程(``IM_PUSH_URL`` 指向本路径,空 = 关闭);
        这里只做验签 → 解析 → 入队三步,不做任何第三方调用,发推送在 Celery 任务
        ``notifications.tasks.send_message_push`` 里。幂等靠任务内按 ``msg_id`` 去重。
    """
    ok, reason = _verify(request)
    if not ok:
        logger.warning("内部推送事件被拒绝:%s", reason)
        return _error(401, f"内部签名校验失败:{reason}")
    payload, reason = _parse(request.body.decode("utf-8", errors="replace"))
    if payload is None:
        return _error(400, reason)
    services.enqueue_message_push(**payload)
    return JsonResponse({"ok": True}, status=202)
