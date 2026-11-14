"""推送通道:极光 REST API、开发期日志后端与「关闭」三态。

设计要点:
    1. 业务侧只认 ``get_push_client().send(...)``,换通道不动业务代码;
    2. ``send`` 对外永不抛异常(返回 False 由任务层决定重试),与 ``im/client.py`` 同约定;
    3. ``PUSH_PROVIDER`` 三态**显式**表达意图:``off``(默认,什么都不发)、
       ``log``(只打日志,联调与自测用)、``jpush``(真通道,缺 key 时启动即失败)。
       刻意不再用「有没有配 key」来猜通道 —— 猜的结果是「看着像推开着、其实只落日志」,
       这种状态在 C-1 里必须不可能出现(要发就得配齐,没配就只能是 off)。

文件信息:
    文件名称          notifications/push.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
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
    """推送通道接口。

    参数说明:
        无构造参数;实现类由 ``get_push_client`` 按 ``PUSH_PROVIDER`` 选定。

    返回参数:
        满足本协议的对象,供 ``notifications.tasks`` 调用 ``send``。

    使用示例:
        ``get_push_client().send(["reg-id"], title="标题", alert="正文", extras={})``

    备注信息:
        协议只有 ``send`` 一个方法,签名固定为「一组 registration_id + 标题 + 正文 +
        extras」;实现方一律**不抛异常**,失败返回 ``False``,由任务层决定是否重试。
    """

    def send(self, registration_ids: list[str], *, title: str, alert: str,
             extras: dict) -> bool:
        """向一组设备发送一条通知。

        参数说明:
            registration_ids: 极光 registration_id 列表。
            title: 通知标题。
            alert: 通知正文。
            extras: 附加数据;``deeplink`` 用于客户端点击跳转。

        返回参数:
            发送成功返回 ``True``;失败返回 ``False``,不抛异常。

        使用示例:
            ``client.send(["reg-id"], title="配对成功", alert="快去打招呼",
            extras={"deeplink": "/chat/7"})``

        备注信息:
            协议方法只声明形状,``...`` 是方法体;具体语义由三个实现类给出
            (``off`` / ``log`` / ``jpush``),调用方不应假设哪种实现。
        """
        ...


class OffPushClient:
    """关闭态:不发、不联网,只留一行 debug 日志。

    参数说明:
        无构造参数。

    返回参数:
        可调用的推送客户端实例。

    使用示例:
        ``PROVIDER_OFF`` 时由 ``get_push_client()`` 返回本类实例。

    备注信息:
        默认态。``PUSH_PROVIDER=off`` 的含义是「这条链路明确关掉」,不是「配错了」;
        任务层看到 ``off`` 会直接计 ``push_skipped_total{provider_off}`` 并返回。
    """

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
            ``OffPushClient().send([], title="t", alert="a", extras={})``

        备注信息:
            只有 ``logger.debug`` 一条,连设备数量都不落 info 级 —— 关闭态下不该有噪声。
        """
        logger.debug("[推送-关闭] devices=%s", len(registration_ids))
        return True


class LogPushClient:
    """开发 / 测试后端:只打日志,永不触网。

    参数说明:
        无构造参数。

    返回参数:
        可调用的推送客户端实例。

    使用示例:
        ``PUSH_PROVIDER=log`` 时由 ``get_push_client()`` 返回本类实例。

    备注信息:
        ``log`` 与 ``off`` 的区别只在可见性:``log`` 把标题、正文与 extras 写成 info
        日志,便于联调与自测核对文案;两者都**不会**真的送到手机。
    """

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
            ``LogPushClient().send(["reg-id"], title="t", alert="a", extras={})``

        备注信息:
            日志前缀固定为 ``[推送-日志]``;只打设备数量不打 id,避免日志里出现设备标识。
        """
        logger.info("[推送-日志] devices=%s title=%s alert=%s extras=%s",
                    len(registration_ids), title, alert, extras)
        return True


class JPushClient:
    """极光 REST API v3 客户端(按 registration_id 投递)。

    参数说明:
        app_key: 极光应用的 AppKey,与 ``master_secret`` 一起拼 Basic 认证串。
        master_secret: 极光应用的 MasterSecret。

    返回参数:
        可调用的推送客户端实例。

    使用示例:
        ``JPushClient(settings.JPUSH_APP_KEY, settings.JPUSH_MASTER_SECRET)``

    备注信息:
        只在 ``PUSH_PROVIDER=jpush`` 时由 ``get_push_client()`` 构造;key 缺失由调用方
        提前拦成 ``ImproperlyConfigured``,本类不做兜底。
    """

    def __init__(self, app_key: str, master_secret: str):
        """保存 Basic 认证串。

        参数说明:
            app_key: 极光应用的 AppKey。
            master_secret: 极光应用的 MasterSecret。

        返回参数:
            无返回值。

        使用示例:
            ``JPushClient("key", "secret")``

        备注信息:
        构造时一次性算好 ``Basic base64(app_key:master_secret)``,不保存原始密钥;
        极光 v3 的鉴权就是这个头,没有 token 交换流程。
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
            ``client._payload(["reg-id"], "标题", "正文", {"deeplink": "/likes"})``

        备注信息:
        ``platform`` 固定 ``all``(Android 与 iOS 载荷各一份);iOS 侧带
        ``sound=default`` 与 ``badge=+1``;``apns_production`` 读
        ``settings.JPUSH_APNS_PRODUCTION``,线上必须是 ``True`` 才会投到 APNs 正式环境;
        ``time_to_live`` 固定 86400 秒。
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
            ``JPushClient("key", "secret").send(["reg-id"], title="标题", alert="正文",
            extras={"deeplink": "/likes"})``

        备注信息:
        超时固定 ``REQUEST_TIMEOUT_SECONDS=5`` 秒;``requests.RequestException`` 走
        exception 日志,非 2xx 走 warning 日志(响应体只截前 500 字);
        本方法只回报结果,重试与指标由 ``notifications.tasks`` 负责。
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

    参数说明:
        无。

    返回参数:
        ``off`` / ``log`` / ``jpush`` 之一;配置非法时返回 ``off``。

    使用示例:
        ``metrics.push_sent(provider_name(), ok)``

    备注信息:
        非法值与缺省一律折算成 ``off``,保证指标标签基数固定为三档;
        本函数只读配置不做校验,``jpush`` 缺 key 的报错在 ``get_push_client`` 里抛。
    """
    name = str(getattr(settings, "PUSH_PROVIDER", PROVIDER_OFF))
    return name if name in PROVIDERS else PROVIDER_OFF


def get_push_client() -> PushClient:
    """按配置返回推送客户端。

    参数说明:
        无。

    返回参数:
        ``off`` → ``OffPushClient``;``log`` → ``LogPushClient``;
        ``jpush`` → ``JPushClient``。

    使用示例:
        ``get_push_client().send(ids, title="标题", alert="正文", extras={})``

    备注信息:
        通道写成 ``jpush`` 但 ``JPUSH_APP_KEY`` / ``JPUSH_MASTER_SECRET`` 没配齐时抛
        ``ImproperlyConfigured`` —— 宁可在启动自检或第一次发信时炸出来,也不要静默
        退化成「只打日志」。未识别的配置名按 ``off`` 处理(见 ``provider_name``)。
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
