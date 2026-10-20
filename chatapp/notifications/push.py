"""推送通道:极光 REST API 与开发期日志后端。

设计要点:
    1. 业务侧只认 ``get_push_client().send(...)``,换通道不动业务代码;
    2. ``send`` 对外永不抛异常(返回 False 由任务层决定重试),与 ``im/client.py`` 同约定;
    3. 没有配置 key 时自动落到日志后端,本地与 CI 不会误发真推送。
"""

import base64
import logging
from typing import Protocol

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

JPUSH_ENDPOINT = "https://api.jpush.cn/v3/push"
REQUEST_TIMEOUT_SECONDS = 5


class PushClient(Protocol):
    """推送通道接口。"""

    def send(self, registration_ids: list[str], *, title: str, alert: str,
             extras: dict) -> bool:
        """向一组设备发送一条通知。

        Args:
            registration_ids: 极光 registration_id 列表。
            title: 通知标题。
            alert: 通知正文。
            extras: 附加数据;``deeplink`` 用于客户端点击跳转。

        Returns:
            发送成功返回 ``True``;失败返回 ``False``,不抛异常。
        """
        ...


class LogPushClient:
    """开发 / 测试后端:只打日志,永不触网。"""

    def send(self, registration_ids: list[str], *, title: str, alert: str,
             extras: dict) -> bool:
        """把推送内容写进日志。

        Args:
            registration_ids: 设备列表(只记录数量)。
            title: 通知标题。
            alert: 通知正文。
            extras: 附加数据。

        Returns:
            恒为 ``True``。
        """
        logger.info("[推送-日志] devices=%s title=%s alert=%s extras=%s",
                    len(registration_ids), title, alert, extras)
        return True


class JPushClient:
    """极光 REST API v3 客户端(按 registration_id 投递)。"""

    def __init__(self, app_key: str, master_secret: str):
        """保存 Basic 认证串。

        Args:
            app_key: 极光应用的 AppKey。
            master_secret: 极光应用的 MasterSecret。
        """
        token = base64.b64encode(f"{app_key}:{master_secret}".encode()).decode()
        self._authorization = f"Basic {token}"

    def _payload(self, registration_ids: list[str], title: str, alert: str,
                 extras: dict) -> dict:
        """拼极光 v3 推送载荷。

        Args:
            registration_ids: 目标设备列表。
            title: 通知标题。
            alert: 通知正文。
            extras: 附加数据。

        Returns:
            可直接作为 JSON body 的字典。
        """
        return {
            "platform": "all",
            "audience": {"registration_id": registration_ids},
            "notification": {
                "android": {"title": title, "alert": alert, "extras": extras},
                "ios": {"title": title, "alert": alert, "sound": "default",
                        "badge": "+1", "extras": extras},
            },
            "options": {"apns_production": False, "time_to_live": 86400},
        }

    def send(self, registration_ids: list[str], *, title: str, alert: str,
             extras: dict) -> bool:
        """调用极光推送接口。

        Args:
            registration_ids: 目标设备列表;为空视为成功(无事可做)。
            title: 通知标题。
            alert: 通知正文。
            extras: 附加数据。

        Returns:
            2xx 返回 ``True``;网络错误或非 2xx 返回 ``False``。
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


def get_push_client() -> PushClient:
    """按配置返回推送客户端。

    Returns:
        配置齐全且开启时返回 ``JPushClient``,否则返回 ``LogPushClient``。
    """
    if settings.PUSH_ENABLED and settings.JPUSH_APP_KEY and settings.JPUSH_MASTER_SECRET:
        return JPushClient(settings.JPUSH_APP_KEY, settings.JPUSH_MASTER_SECRET)
    return LogPushClient()
