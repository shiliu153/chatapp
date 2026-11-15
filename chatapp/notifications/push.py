"""推送通道:极光 REST API、开发期日志后端与「关闭」三态。

设计要点:
    1. 业务侧只认 ``get_push_client().send(...)``,换通道不动业务代码;
    2. ``send`` 对外永不抛异常(返回 False 由任务层决定重试),与 ``im/client.py`` 同约定;
    3. ``PUSH_PROVIDER`` 三态**显式**表达意图:``off``(默认,什么都不发)、
       ``log``(只打日志,联调与自测用)、``jpush``(真通道,缺 key 时启动即失败)。
       刻意不再用「有没有配 key」来猜通道 —— 猜的结果是「看着像推开着、其实只落日志」,
       这种状态在 C-1 里必须不可能出现(要发就得配齐,没配就只能是 off)。
"""

import base64
import logging
from typing import Protocol

import requests
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

logger = logging.getLogger(__name__)

JPUSH_ENDPOINT = "https://api.jpush.cn/v3/push"
REQUEST_TIMEOUT_SECONDS = 5

PROVIDER_OFF = "off"
PROVIDER_LOG = "log"
PROVIDER_JPUSH = "jpush"
PROVIDERS = (PROVIDER_OFF, PROVIDER_LOG, PROVIDER_JPUSH)


class PushClient(Protocol):
    """推送通道接口。"""

    def send(self, registration_ids: list[str], *, title: str, alert: str,
             extras: dict) -> bool:
        """向一组设备发送一条通知。

        参数说明:
            registration_ids: 极光 ``registration_id`` 列表。
            title: 通知标题。
            alert: 通知正文。
            extras: 附加数据;``deeplink`` 用于客户端点击跳转。

        返回参数:
            发送成功返回 ``True``;失败返回 ``False``,不抛异常。

        使用示例:
            ``ok = get_push_client().send(registration_ids, title=title, alert=alert, extras=extras)``(见 ``notifications/tasks.py`` 的 ``send_push``)

        备注信息:
            这是通道接口的约定,不是实现:实现侧一律吞掉异常改用 ``False`` 表达失败,
            由任务层决定是否重试(与 ``im/client.py`` 同约定)。
        """
        ...


class OffPushClient:
    """关闭态:不发、不联网,只留一行 debug 日志。"""

    def send(self, registration_ids: list[str], *, title: str, alert: str,
             extras: dict) -> bool:
        """什么都不做(``PUSH_PROVIDER=off``)。

        参数说明:
            registration_ids: 设备列表(未使用)。
            title: 通知标题(未使用)。
            alert: 通知正文(未使用)。
            extras: 附加数据(未使用)。

        返回参数:
            恒为 ``True``:关闭不是失败,否则任务会一直重试。

        使用示例:
            ``get_push_client().send(["rid-1"], title="t", alert="a", extras={})``(``PUSH_PROVIDER=off`` 时经 ``get_push_client`` 返回本类,见 ``notifications/tasks.py`` 的 ``send_push``)

        备注信息:
            只在 debug 日志里留一行设备数量,不联网、不落库。
        """
        logger.debug("[推送-关闭] devices=%s", len(registration_ids))
        return True


class LogPushClient:
    """开发 / 测试后端:只打日志,永不触网。"""

    def send(self, registration_ids: list[str], *, title: str, alert: str,
             extras: dict) -> bool:
        """把推送内容写进日志。

        参数说明:
            registration_ids: 设备列表(只记录数量)。
            title: 通知标题。
            alert: 通知正文。
            extras: 附加数据。

        返回参数:
            恒为 ``True``。

        使用示例:
            ``ok = LogPushClient().send(["rid-1"], title="t", alert="a", extras={})``(见 ``notifications/tests.py`` 的 ``PushClientTests.test_log_client_returns_true_and_logs``)

        备注信息:
            联调与自测用:永不触网,日志前缀固定 ``[推送-日志]``。
        """
        logger.info("[推送-日志] devices=%s title=%s alert=%s extras=%s",
                    len(registration_ids), title, alert, extras)
        return True


class JPushClient:
    """极光 REST API v3 客户端(按 registration_id 投递)。"""

    def __init__(self, app_key: str, master_secret: str):
        """保存 Basic 认证串。

        参数说明:
            app_key: 极光应用的 AppKey。
            master_secret: 极光应用的 MasterSecret。

        使用示例:
            ``client = JPushClient("key", "secret")``(见 ``notifications/tests.py`` 的 ``PushClientTests.test_jpush_client_posts_expected_payload``)

        备注信息:
            由 ``get_push_client`` 在 ``PUSH_PROVIDER=jpush`` 且两个 key 都配齐时构造;
            认证串只在内存里,不落日志。
        """
        token = base64.b64encode(f"{app_key}:{master_secret}".encode()).decode()
        self._authorization = f"Basic {token}"

    def _payload(self, registration_ids: list[str], title: str, alert: str,
                 extras: dict) -> dict:
        """拼极光 v3 推送载荷。

        参数说明:
            registration_ids: 目标设备列表。
            title: 通知标题。
            alert: 通知正文。
            extras: 附加数据。

        返回参数:
            可直接作为 JSON body 的字典。

        使用示例:
            ``json=self._payload(registration_ids, title, alert, extras)``(见本文件 ``JPushClient.send``)

        备注信息:
            安卓 / iOS 两个平台各写一段,``apns_production`` 取自
            ``settings.JPUSH_APNS_PRODUCTION``,``time_to_live`` 固定 86400。
        """
        return {
            "platform": "all",
            "audience": {"registration_id": registration_ids},
            "notification": {
                "android": {"title": title, "alert": alert, "extras": extras},
                "ios": {"title": title, "alert": alert, "sound": "default",
                        "badge": "+1", "extras": extras},
            },
            "options": {"apns_production": settings.JPUSH_APNS_PRODUCTION,
                        "time_to_live": 86400},
        }

    def send(self, registration_ids: list[str], *, title: str, alert: str,
             extras: dict) -> bool:
        """调用极光推送接口。

        参数说明:
            registration_ids: 目标设备列表;为空视为成功(无事可做)。
            title: 通知标题。
            alert: 通知正文。
            extras: 附加数据。

        返回参数:
            2xx 返回 ``True``;网络错误或非 2xx 返回 ``False``。

        使用示例:
            ``ok = JPushClient("key", "secret").send(["rid-1"], title="有人喜欢了你", alert="去看看是谁", extras={"deeplink": "/likes"})``(见 ``notifications/tests.py`` 的 ``PushClientTests``)

        备注信息:
            超时 ``REQUEST_TIMEOUT_SECONDS``(5 秒);``requests.RequestException`` 与
            非 2xx 都只记日志后返回 ``False``,不向上抛。
        """
        if not registration_ids:
            return True
        try:
            response = requests.post(
                JPUSH_ENDPOINT,
                json=self._payload(registration_ids, title, alert, extras),
                headers={"Authorization": self._authorization},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
        except requests.RequestException:
            logger.exception("极光推送请求失败")
            return False
        if response.status_code // 100 != 2:
            logger.warning("极光推送失败 status=%s body=%s",
                           response.status_code, response.text[:500])
            return False
        return True


def provider_name() -> str:
    """当前推送通道名(指标标签用)。

    返回参数:
        ``off`` / ``log`` / ``jpush`` 之一;配置非法时返回 ``off``。

    使用示例:
        ``metrics.push_sent(provider_name(), ok)``(见 ``notifications/tasks.py`` 的 ``send_push``)

    备注信息:
        只用于指标标签与启动提示;取通道实例请用 ``get_push_client``。
    """
    name = str(getattr(settings, "PUSH_PROVIDER", PROVIDER_OFF))
    return name if name in PROVIDERS else PROVIDER_OFF


def get_push_client() -> PushClient:
    """按配置返回推送客户端。

    返回参数:
        ``off`` → ``OffPushClient``;``log`` → ``LogPushClient``;
        ``jpush`` → ``JPushClient``。

    使用示例:
        ``ok = get_push_client().send(registration_ids, title=title, alert=alert, extras=extras)``(见 ``notifications/tasks.py`` 的 ``send_push``)

    备注信息:
        ``ImproperlyConfigured``: 通道写成 ``jpush`` 但 AppKey/MasterSecret 没配齐 ——
        宁可在启动自检/第一次发信时炸出来,也不要静默退化成「只打日志」。
        每次调用现构造实例,不缓存:测试里 ``override_settings`` 改通道能立即生效。
    """
    name = provider_name()
    if name == PROVIDER_JPUSH:
        app_key = getattr(settings, "JPUSH_APP_KEY", "")
        master_secret = getattr(settings, "JPUSH_MASTER_SECRET", "")
        if not app_key or not master_secret:
            raise ImproperlyConfigured(
                "PUSH_PROVIDER=jpush 但 JPUSH_APP_KEY / JPUSH_MASTER_SECRET 未配置")
        return JPushClient(app_key, master_secret)
    if name == PROVIDER_LOG:
        return LogPushClient()
    return OffPushClient()
