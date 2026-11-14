"""推送设备与通知偏好接口,以及站内通知中心接口。

设计要点:
    1. 上报设备即「单设备」:同一账号只保留最新一台,旧设备记录直接删除
       (与「单设备登录」一致);
    2. 解绑只删自己的设备,且不区分「不存在」与「不是你的」—— 一律 204,
       避免泄漏他人设备是否存在;
    3. 偏好读取时按需创建,默认全开;
    4. 站内通知**只返回 90 天内、只返回自己的**:查询侧截断,物理删除交给
       ``notifications_prune`` 命令(不接 cron,取舍见计划 §2.3);
    5. 已读接口只影响自己的通知:别人的 id 混进来会被 user 条件过滤掉,仍然 204
       (不泄漏「这条通知是否存在」);
    6. 设备易主(同一 ``registration_id`` 被另一个账号上报)**保留易主语义**——
       换成 409 拒绝会破坏「换账号登录后收不到推送」的体验 —— 但必须留痕:写一条
       warning 日志 + 给原账号写一条系统站内通知。否则原账号只会「推送悄悄没了」,
       分不清是自己换了设备还是有人在抢(安全审计 R4-E1 / M-5)。

关联文档:
    - 接口契约:docs/api/push.md(推送设备与偏好)、docs/api/notifications.md(站内通知)

文件信息:
    文件名称          notifications/views.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, throttle_classes
from rest_framework.response import Response

from config.cursor import paginated_response
from config.schema_helpers import cursor_page, cursor_params

from .models import (InAppNotification, NotificationKind, NotificationPreference,
                     NotificationTarget, PushDevice)
from .serializers import (DeviceResponseSerializer, DeviceSerializer, NotificationItemSerializer,
                          NotificationReadSerializer, PushPreferenceSerializer,
                          UnreadCountSerializer, notification_payload)
from .services import notify_on_commit
from .throttles import NotificationsThrottle, NotificationsUnreadThrottle

logger = logging.getLogger(__name__)

# 通知中心只展示最近 90 天:更早的记录仍留在库里,由 ``notifications_prune`` 回收。
NOTIFICATION_WINDOW_DAYS = 90

# 设备易主时发给原账号的站内通知文案(由服务端生成,双端直接显示)。
DEVICE_TRANSFER_TEXT = "你的设备已在另一账号登录,推送已切换"


@extend_schema(request=DeviceSerializer, responses={200: DeviceResponseSerializer})
@api_view(["POST"])
def register_device(request):
    """上报推送设备(POST /api/v1/push/devices)。

    幂等:同一 registration_id 重复上报只更新归属与版本;同账号的其他设备被删除。
    设备**易主**(这个 registration_id 原本挂在别的账号下)照旧允许,但会写一条
    ``push_device_transfer`` warning 日志,并在事务提交后给原账号写一条系统站内通知
    ——知道别人 registration_id 的人仍然能把设备抢走,但原账号至少看得见这件事。

    参数说明:
        request: DRF 请求对象,body 需带 ``registration_id`` 与 ``platform``。

    返回参数:
        ``{"registration_id": str, "platform": str}``。

    使用示例:
        ``POST /api/v1/push/devices {"registration_id": "reg-id", "platform": "android"}``

    备注信息:
        整个写入包在 ``transaction.atomic()`` 里:先判易主并挂 ``notify_on_commit``
        (回滚就不该留下脏通知),再 ``update_or_create``,最后删掉同账号的其他设备;
        日志走 ``%s`` 占位而非 ``extra={}``,因为 ``config/logging.py`` 的 JsonFormatter
        只透出白名单字段。
    """
    serializer = DeviceSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    data = serializer.validated_data
    me = request.user
    with transaction.atomic():
        previous = PushDevice.objects.filter(
            registration_id=data["registration_id"]).first()
        if previous is not None and previous.user_id != me.id:
            # 日志走 %s 占位而不是 extra={}:JsonFormatter 只透出白名单字段,
            # 自定义 extra 会被静默丢掉(见 config/logging.py)。
            logger.warning("push_device_transfer registration_id=%s from_user=%s to_user=%s",
                           data["registration_id"], previous.user_id, me.id)
            # 通知挂在 on_commit 上:回滚了就不该留下「设备被切走了」的脏通知。
            # 传 id 而非实例:回调在提交后执行,期间原账号可能已被注销。
            notify_on_commit(previous.user_id, NotificationKind.SYSTEM,
                             target_kind=NotificationTarget.NONE,
                             text=DEVICE_TRANSFER_TEXT)
        PushDevice.objects.update_or_create(
            registration_id=data["registration_id"],
            defaults={
                "user": me,
                "platform": data["platform"],
                "app_version": data.get("app_version", ""),
            },
        )
        PushDevice.objects.filter(user=me).exclude(
            registration_id=data["registration_id"]).delete()
    return Response({"registration_id": data["registration_id"],
                     "platform": data["platform"]})


@extend_schema(request=None, responses={204: None})
@api_view(["DELETE"])
def unregister_device(request, registration_id):
    """解绑推送设备(DELETE /api/v1/push/devices/{registration_id})。

    幂等:设备不存在、或属于别人,一律 204(不泄漏他人设备信息)。

    参数说明:
        request: DRF 请求对象。
        registration_id: 极光 registration_id。

    返回参数:
        204 空响应。

    使用示例:
        ``DELETE /api/v1/push/devices/reg-id``

    备注信息:
        过滤条件同时带 ``user=request.user``,所以别人的设备不会被删,也不会回 404 ——
        「不存在」与「不是你的」在响应上完全一致。
    """
    PushDevice.objects.filter(user=request.user, registration_id=registration_id).delete()
    return Response(status=204)


@extend_schema(methods=["GET"], responses={200: PushPreferenceSerializer})
@extend_schema(methods=["PATCH"], request=PushPreferenceSerializer,
               responses={200: PushPreferenceSerializer})
@api_view(["GET", "PATCH"])
def preferences(request):
    """读取或修改通知偏好(GET/PATCH /api/v1/push/preferences)。

    PATCH 为局部更新:只改传入的字段,未传的保持不变。

    参数说明:
        request: DRF 请求对象;PATCH 时 body 可带
            ``likes`` / ``matches`` / ``messages`` / ``system`` / ``social``。

    返回参数:
        ``{"likes": bool, "matches": bool, "messages": bool, "system": bool, "social": bool}``。

    使用示例:
        ``PATCH /api/v1/push/preferences {"social": false}``

    备注信息:
        偏好是懒创建的:GET 也会经 ``NotificationPreference.for_user`` 写库(默认全开);
        PATCH 走 ``partial=True``,因此只改传入字段,响应统一回显完整五个开关。
    """
    preference = NotificationPreference.for_user(request.user)
    if request.method == "PATCH":
        serializer = PushPreferenceSerializer(preference, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
    return Response(PushPreferenceSerializer(preference).data)


def _visible_notifications(user):
    """当前用户 90 天内可见的通知查询集(列表与未读数共用同一口径)。

    参数说明:
        user: 当前用户。

    返回参数:
        已按 ``-created_at, -id`` 排序、并预取触发者资料与照片的查询集
        (预取是为了列表序列化时不产生 N+1)。

    使用示例:
        ``_visible_notifications(request.user).filter(is_read=False).count()``

    备注信息:
        窗口由 ``NOTIFICATION_WINDOW_DAYS`` 决定,只做查询侧截断,不删库;
        列表、未读数、标已读三个接口都必须用本函数,任一处单独改窗口都会口径不一致。
    """
    cutoff = timezone.now() - timedelta(days=NOTIFICATION_WINDOW_DAYS)
    return (InAppNotification.objects
            .filter(user=user, created_at__gte=cutoff)
            .select_related("actor__profile")
            .prefetch_related("actor__photos"))


@extend_schema(methods=["GET"], parameters=cursor_params(),
               responses={200: cursor_page("NotificationPage", NotificationItemSerializer)})
@api_view(["GET"])
@throttle_classes([NotificationsThrottle])
def notification_list(request):
    """站内通知列表(GET /api/v1/notifications)。

    只返回自己的、90 天内的通知,按时间倒序;默认走复合游标分页
    (``{count, next_cursor, has_more, results}``),带 ``offset`` 的老客户端
    仍走 offset 兼容路径。

    参数说明:
        request: DRF 请求对象,提供 ``limit`` / ``before``(或兼容的 ``offset``)。

    返回参数:
        分页后的通知列表;``results[]`` 每项含触发者摘要与跳转目标。

    使用示例:
        ``GET /api/v1/notifications?limit=20``

    备注信息:
        按用户限流(``NotificationsThrottle``,超限 429 + ``Retry-After``);
        分页统一交给 ``config.cursor.paginated_response``,游标键是 ``created_at``,
        次级键靠模型 ``Meta.ordering`` 的 ``-id`` 保证稳定。
    """
    return paginated_response(
        request, _visible_notifications(request.user),
        lambda rows: NotificationItemSerializer(
            [notification_payload(row, request) for row in rows], many=True).data,
        field="created_at")


@extend_schema(methods=["GET"], responses={200: UnreadCountSerializer})
@api_view(["GET"])
@throttle_classes([NotificationsUnreadThrottle])
def notification_unread_count(request):
    """未读通知数(GET /api/v1/notifications/unread_count)。

    口径与列表完全一致(自己的、90 天内),供消息页铃铛角标使用。

    参数说明:
        request: DRF 请求对象。

    返回参数:
        ``{"unread": n}``。

    使用示例:
        ``GET /api/v1/notifications/unread_count``

    备注信息:
        只做一次 ``COUNT`` 聚合,不返回任何通知内容;限流额度比列表宽松一档
        (``NotificationsUnreadThrottle``),因为角标接口调用频率天然更高。
    """
    unread = _visible_notifications(request.user).filter(is_read=False).count()
    return Response({"unread": unread})


@extend_schema(methods=["POST"], request=NotificationReadSerializer, responses={204: None})
@api_view(["POST"])
def notification_read(request):
    """标记已读(POST /api/v1/notifications/read)。

    两种用法:``{"ids": [...]}`` 只标指定几条,``{"all": true}`` 标全部未读。
    只影响自己的通知,幂等 204;别人的 id 混进来会被静默过滤。

    参数说明:
        request: DRF 请求对象;body 需带 ``ids`` 或 ``all=true``。

    返回参数:
        204 空响应。

    使用示例:
        ``POST /api/v1/notifications/read {"ids": [12, 13]}``

    备注信息:
        ``ids`` 与 ``all`` 都不给时由 ``NotificationReadSerializer.validate`` 拦成 400;
        查询集先经 ``_visible_notifications`` 再 ``filter(is_read=False)``,所以重复标记
        与越权 id 都不会报错,也不泄漏「这条通知是否存在」;写接口不挂限流。
    """
    serializer = NotificationReadSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    queryset = _visible_notifications(request.user).filter(is_read=False)
    if serializer.validated_data.get("all"):
        queryset.update(is_read=True)
    else:
        queryset.filter(pk__in=serializer.validated_data["ids"]).update(is_read=True)
    return Response(status=204)
