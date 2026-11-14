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

文件信息:
    文件名称          notifications/internal.py
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
        ``_error(401, "内部签名校验失败")``

    备注信息:
        只在内部路径使用,因此不带 ``request_id``:调用方是 imserver,不产生用户侧
        请求上下文,排障靠同一条 warning 日志。
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
        ``signature_for("1700000000", "/internal/push/new-message", body, secret)``

    备注信息:
        待签串固定为 ``timestamp\\nPOST\\npath\\nbody``(方法写死 ``POST``),改任何一段
        都要与 imserver 侧同时改;``path`` 必须与 ``INTERNAL_PATH`` 一致,查询串不参与。
    """
    signing = f"{timestamp}\nPOST\n{path}\n{body}".encode()
    return hmac.new(secret.encode(), signing, hashlib.sha256).hexdigest()


def _verify(request) -> tuple[bool, str]:
    """校验时间戳与签名。

    参数说明:
        request: Django 请求对象。

    返回参数:
        ``(是否通过, 失败原因)``;通过时失败原因为空串。

    使用示例:
        ``ok, reason = _verify(request)``

    备注信息:
        判定顺序是「密钥未配 → 缺头 → 时间戳非法 → 时间戳过期 → 签名不符」,
        失败即短路;比较用 ``hmac.compare_digest`` 做定时安全比较;
        重放窗口取 ``settings.PUSH_INTERNAL_MAX_SKEW``(默认 300 秒)。
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
        ``payload, reason = _parse(request.body.decode())``

    备注信息:
        必填 ``to_user_id`` / ``from_user_id``(正整数)与 ``msg_id``;收发双方相同、
        账号 id 非正数(系统消息)一律拒;``from_nickname`` 截到 ``MAX_NICKNAME``、
        ``preview`` 截到 ``MAX_PREVIEW``、``msg_id`` 截到 64 字符,多余部分丢弃不报错。
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
        ``curl -X POST http://127.0.0.1:8000/internal/push/new-message -H
        "X-IM-Timestamp: ..." -H "X-IM-Signature: ..." -d '{...}'``

    备注信息:
        走 ``csrf_exempt``(调用方是服务器,没有 Cookie)与 ``require_POST``(其他方法
        由 Django 直接 405);本视图**不做任何第三方网络调用**,只验签 + 入队,
        真正的发送与偏好过滤在 ``notifications.tasks.send_message_push`` 里。
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
