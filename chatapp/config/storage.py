"""用户媒体存储配额(M7):用量统计与上传前校验。

设计要点:
    1. **用量按库里记的字节数求和,不遍历磁盘**:``Photo`` / ``PostImage`` 在上传时
       写入 ``bytes``,聊天图/语音本来就有 ``bytes``;四条聚合都走外键索引,
       单次上传多花 4 条轻查询,换来「不扫目录」的稳定耗时;
    2. **只拦新增**:删除、审核、清理都不经过这里 —— 已超限的老用户仍能删图自救,
       否则会出现「配额满了又删不掉」的死锁;
    3. ``USER_STORAGE_QUOTA_BYTES <= 0`` 表示关闭配额(本地手测可关);
    4. 超限抛 :class:`StorageQuotaExceeded`(HTTP 413 + 业务码 41301),由
       ``config.exceptions.api_exception_handler`` 统一格式化成
       ``{code, message, request_id}`` 信封。

关联文档:
    - 安全审计:docs/security/2026-10-27-api-security-audit.md M7
    - 接口契约:docs/api/users.md、docs/api/feed.md、docs/api/im.md
"""

from django.conf import settings
from django.db.models import Sum
from rest_framework.exceptions import APIException

from . import error_codes

MEGABYTE = 1024 * 1024


class StorageQuotaExceeded(APIException):
    """单账号媒体存储超过配额(413 / ``41301``)。

    Attributes:
        status_code: HTTP 413,与「请求体过大」语义一致,客户端按「空间不足」提示。
        detail_code: 业务码 41301,前端可据此区分普通 400。
    """

    status_code = 413
    default_detail = "存储空间已满"
    default_code = "storage_quota_exceeded"
    detail_code = error_codes.STORAGE_QUOTA_EXCEEDED


def quota_limit_bytes() -> int:
    """读取单账号配额(字节)。

    Returns:
        配额字节数;``<= 0`` 表示未启用配额。
    """
    return int(getattr(settings, "USER_STORAGE_QUOTA_BYTES", 0) or 0)


def usage_bytes(user_id: int) -> int:
    """统计一个账号已占用的媒体字节数。

    口径与上传入口一致:资料图 + 广场图 + 未过期的聊天图 + 未过期的聊天语音。
    已删除/已过期清理的行不计入(文件已经不在磁盘上)。

    Args:
        user_id: 账号 id。

    Returns:
        已用字节数;没有任何媒体时为 0。
    """
    # 局部导入:本模块被多个 app 的 views 引用,模块级导入模型容易形成循环依赖
    from feed.models import PostImage
    from im.models import ChatImage, ChatImageStatus, ChatVoice, ChatVoiceStatus
    from users.models import Photo

    total = 0
    total += Photo.objects.filter(user_id=user_id).aggregate(
        value=Sum("bytes"))["value"] or 0
    total += PostImage.objects.filter(post__author_id=user_id).aggregate(
        value=Sum("bytes"))["value"] or 0
    total += ChatImage.objects.filter(
        owner_id=user_id, status=ChatImageStatus.VISIBLE).aggregate(
        value=Sum("bytes"))["value"] or 0
    total += ChatVoice.objects.filter(
        owner_id=user_id, status=ChatVoiceStatus.VISIBLE).aggregate(
        value=Sum("bytes"))["value"] or 0
    return total


def ensure_quota(user, incoming_bytes: int) -> None:
    """在上传落盘前校验「已用 + 本次」是否超过配额。

    Args:
        user: 当前登录用户。
        incoming_bytes: 本次将要写入磁盘的字节数(图片含缩略图)。

    Raises:
        StorageQuotaExceeded: 超过配额;异常消息里带已用/上限,便于客户端提示。
    """
    limit = quota_limit_bytes()
    if limit <= 0:
        return
    used = usage_bytes(user.id)
    if used + max(incoming_bytes, 0) <= limit:
        return
    raise StorageQuotaExceeded(
        f"存储空间已满(已用 {used // MEGABYTE}MB / 上限 {limit // MEGABYTE}MB),"
        "请先删除部分照片,或等待聊天图片过期")
