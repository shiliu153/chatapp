"""站内通知中心读接口的按用户限流:通知列表与未读数。

设计要点:
    通知列表每页要跑一次 ``COUNT(*)`` 并预取 ``actor__profile`` / ``actor__photos``,
    未读数一次聚合 + ``COUNT``;两者都是「单请求多次查询」的形态,按用户限流可以
    压住刷列表/刷角标的成本。额度在 ``settings.DEFAULT_THROTTLE_RATES`` 里配置
    (``notifications`` / ``notifications_unread``),超限一律 429 + ``Retry-After``。
    标记已读是写接口,不在此列。
"""

from config.throttling import UserScopedThrottle


class NotificationsThrottle(UserScopedThrottle):
    """按用户限流通知列表;额度见 ``settings.DEFAULT_THROTTLE_RATES["notifications"]``。"""

    scope = "notifications"


class NotificationsUnreadThrottle(UserScopedThrottle):
    """按用户限流未读数;额度见 ``settings.DEFAULT_THROTTLE_RATES["notifications_unread"]``。

    未读数是角标接口,调用频率天然比列表高,因此额度单独放宽一档。
    """

    scope = "notifications_unread"
