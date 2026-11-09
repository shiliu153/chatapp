"""端会话:客户端类型判定与「按端」的会话版本读写。

设计要点:
    1. **判端只看请求头,鉴权只看令牌** —— 签发时用 ``X-Client`` 决定写哪一端,
       之后一律用令牌里的 ``ct`` claim 回查,避免某个请求漏带头就把另一端顶掉;
    2. 缺省一律 ``app``:线上 1.0.10 及更早的 APK 不带 ``X-Client``,不能因此掉线;
    3. 版本递增用 ``F()`` 在数据库内自增,并发登录不会两个请求都拿到同一个旧版本;
    4. 本模块是鉴权 / 登录 / 刷新 / IM 签发 / 登录设备列表五处**唯一**的读写入口,
       别在别处直接读写 ``DeviceSession`` 或 ``User.session_version``。

注意事项:
    「在线」是**账号级**的(``users.presence``,120 秒窗口),本模块的
    ``last_active_at`` 只记录「这一端最近一次登录或刷新的时间」,两者不可互推:
    一端挂着心跳不打请求 ≠ 在线,反之亦然。
"""

from django.db.models import F
from django.utils import timezone

from .models import CLIENT_TYPE_CHOICES, SESSION_VERSION_DEFAULT, DeviceSession

CLIENT_APP = "app"
CLIENT_WEB = "web"
CLIENT_TYPES = (CLIENT_APP, CLIENT_WEB)
# 端类型的展示名(登录设备列表的 ``client_label``);文案与模型 choices 同源
CLIENT_LABELS = dict(CLIENT_TYPE_CHOICES)


def client_type_of(request) -> str:
    """按请求头判定客户端类型。

    Args:
        request: DRF 请求对象。

    Returns:
        ``"web"`` 或 ``"app"``;头缺失、为空或取值未知时返回 ``"app"``。
    """
    value = (request.headers.get("X-Client") or "").strip().lower()
    return CLIENT_WEB if value == CLIENT_WEB else CLIENT_APP


def bump(user, client_type: str) -> int:
    """把账号在某一端上的会话版本 +1(该端旧令牌随即失效)。

    Args:
        user: 目标账号。
        client_type: ``"app"`` 或 ``"web"``。

    Returns:
        递增后的新版本号;该端首次登录时建行并返回 2(初始行版本 1 再加一)。
    """
    session, _ = DeviceSession.objects.get_or_create(
        user=user, client_type=client_type)
    DeviceSession.objects.filter(pk=session.pk).update(version=F("version") + 1)
    session.refresh_from_db(fields=["version"])
    return session.version


def touch(user, client_type: str) -> None:
    """把账号在某一端上的「最后活跃时间」刷成当前时间。

    只在**登录签发令牌**与 ``/auth/token/refresh`` 成功时调用:这两处才是「这一端
    确实在被使用」的证据。鉴权路径不调它 —— 每个请求都写一次库会把读接口拖成写接口,
    而「在线」另有账号级的 presence 通道。

    Args:
        user: 目标账号(需要 ``id``)。
        client_type: ``"app"`` 或 ``"web"``。

    Returns:
        ``None``。该端还没有会话行时静默跳过(登录路径先 ``bump`` 建行,正常不会走到)。
    """
    DeviceSession.objects.filter(user_id=user.id, client_type=client_type).update(
        last_active_at=timezone.now())


def sessions_of(user):
    """列出账号已经有会话行的那几端(登录设备列表的数据源)。

    Args:
        user: 目标账号(需要 ``id``)。

    Returns:
        ``DeviceSession`` 查询集,按 ``client_type`` 排序(``app`` 在前);
        **从没登录过的端没有行,因此不会出现在结果里**(最多两行)。
    """
    return DeviceSession.objects.filter(user_id=user.id).order_by("client_type")


def label_of(client_type: str) -> str:
    """取端类型的展示名(给客户端的 ``client_label``)。

    Args:
        client_type: ``"app"`` 或 ``"web"``。

    Returns:
        中文展示名(如 ``App`` / ``网页端``);未知取值原样返回,不抛异常。
    """
    return CLIENT_LABELS.get(client_type, client_type)


def version_of(user_id: int, client_type: str):
    """取账号在某一端上的当前会话版本。

    Args:
        user_id: 账号 id。
        client_type: ``"app"`` 或 ``"web"``。

    Returns:
        当前版本号;该端从未登录过(没有行)返回 ``None``。
    """
    return (DeviceSession.objects
            .filter(user_id=user_id, client_type=client_type)
            .values_list("version", flat=True)
            .first())


def current_version(user, client_type: str) -> int:
    """取账号在某一端上的「有效」会话版本,供签发与鉴权比对。

    为什么要有这一层兜底:端会话行是登录时建的,而 ``User.session_version`` 里留着
    迁移桥接前的历史值。**没有行**说明该端从未走过登录(例如造数脚本、压测账号,
    以及升级前的老账号在另一个端上),此时按历史列取值 —— 与升级前的行为完全一致,
    也是 ``0006`` 桥接迁移写进两行端会话的那个值。等 ``User.session_version`` 列
    删除时,这条兜底一并去掉(见设计文档 §10)。

    Args:
        user: 账号实例(需要 ``id`` 与 ``session_version``)。
        client_type: ``"app"`` 或 ``"web"``。

    Returns:
        该端的当前版本号。
    """
    version = version_of(user.id, client_type)
    return user.session_version if version is None else version


def ensure_version(user, client_type: str) -> int:
    """确保该端有会话行(**不递增**),返回它的版本。

    用途:签发 IM 凭证前必须先有一个 imserver 见过的版本。存量账号、造数账号、
    压测账号可能从未在该端登录过(没有行),此时按历史列 ``User.session_version``
    补建一行 —— 与 ``0006`` 桥接迁移写入的值同源,因此不会把在线会话顶掉。

    Args:
        user: 账号实例。
        client_type: ``"app"`` 或 ``"web"``。

    Returns:
        该端当前版本号。
    """
    session, _ = DeviceSession.objects.get_or_create(
        user=user, client_type=client_type,
        defaults={"version": user.session_version})
    return session.version


def legacy_token_version(claims) -> int:
    """取令牌里带的会话版本,缺 claim 的历史令牌按初值处理。

    Args:
        claims: 已解码的 JWT payload(``dict`` 形态的令牌对象)。

    Returns:
        令牌声称的版本号。
    """
    return claims.get("session_version", SESSION_VERSION_DEFAULT)


def client_type_of_token(claims) -> str:
    """取令牌里带的端类型,缺 ``ct`` claim 的历史令牌按 ``app`` 兜底。

    Args:
        claims: 已解码的 JWT payload(``dict`` 形态的令牌对象)。

    Returns:
        ``"app"`` 或 ``"web"``。
    """
    return claims.get("ct", CLIENT_APP)
