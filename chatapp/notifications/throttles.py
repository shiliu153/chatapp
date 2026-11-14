"""站内通知中心读接口的按用户限流:通知列表与未读数。

设计要点:
    通知列表每页要跑一次 ``COUNT(*)`` 并预取 ``actor__profile`` / ``actor__photos``,
    未读数一次聚合 + ``COUNT``;两者都是「单请求多次查询」的形态,按用户限流可以
    压住刷列表/刷角标的成本。额度在 ``settings.DEFAULT_THROTTLE_RATES`` 里配置
    (``notifications`` / ``notifications_unread``),超限一律 429 + ``Retry-After``。
    标记已读是写接口,不在此列。

文件信息:
    文件名称          notifications/throttles.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from config.throttling import UserScopedThrottle


class NotificationsThrottle(UserScopedThrottle):
    """按用户限流通知列表;额度见 ``settings.DEFAULT_THROTTLE_RATES["notifications"]``。

    参数说明:
        DRF 按 ``Throttle()`` 无参构造,额度从缓存/设置里按 ``scope`` 读取。

    返回参数:
        供 ``@throttle_classes`` 使用的限流实例。

    使用示例:
        ``@throttle_classes([NotificationsThrottle])``

    备注信息:
        只挂在 ``notifications.views.notification_list`` 上;超限由 DRF 统一回 429 并带
        ``Retry-After``,错误体沿用项目统一契约。列表接口每页都会 ``COUNT`` 并预取
        触发者资料与照片,限流的主要目的就是压住这部分成本。
    """

    scope = "notifications"


class NotificationsUnreadThrottle(UserScopedThrottle):
    """按用户限流未读数;额度见 ``settings.DEFAULT_THROTTLE_RATES["notifications_unread"]``。

    未读数是角标接口,调用频率天然比列表高,因此额度单独放宽一档。

    参数说明:
        DRF 按 ``Throttle()`` 无参构造,额度从缓存/设置里按 ``scope`` 读取。

    返回参数:
        供 ``@throttle_classes`` 使用的限流实例。

    使用示例:
        ``@throttle_classes([NotificationsUnreadThrottle])``

    备注信息:
        只挂在 ``notifications.views.notification_unread_count`` 上;与列表共用一个
        用户维度的计数口径,但 ``scope`` 不同,两个额度互不影响。
    """

    scope = "notifications_unread"
