"""端会话:客户端类型判定与「按端」的会话版本读写。

设计要点:
    1. **判端只看请求头,鉴权只看令牌** —— 签发时用 ``X-Client`` 决定写哪一端,
       之后一律用令牌里的 ``ct`` claim 回查,避免某个请求漏带头就把另一端顶掉;
    2. 缺省一律 ``app``:线上 1.0.10 及更早的 APK 不带 ``X-Client``,不能因此掉线;
    3. 版本递增用 ``F()`` 在数据库内自增,并发登录不会两个请求都拿到同一个旧版本;
    4. 本模块是鉴权 / 登录 / 刷新 / IM 签发 / 登录设备列表五处**唯一**的读写入口,
       别在别处直接读写 ``DeviceSession`` 或 ``User.session_version``;
    5. **下线是打标记(``logged_out_at``),不是删行**:行留着版本号才单调递增,
       旧令牌不会因为版本回到默认值而复活;列表只列 ``logged_out_at IS NULL`` 的端。

注意事项:
    「在线」是**账号级**的(``users.presence``,120 秒窗口),本模块的
    ``last_active_at`` 只记录「这一端最近一次登录或刷新的时间」,两者不可互推:
    一端挂着心跳不打请求 ≠ 在线,反之亦然。

文件信息:
    文件名称          accounts/device_session.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
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

    参数说明:
        request: DRF 请求对象，读取请求头 ``X-Client``。

    返回参数:
        ``"web"`` 或 ``"app"``；头缺失、为空或取值未知时返回 ``"app"``。

    使用示例:
        ``client_type = client_type_of(request)``

    备注信息:
        只在**签发**令牌时使用；鉴权一律看令牌里的 ``ct``，不看请求头。
        取值先 ``strip().lower()``，因此 ``Web`` / `` web `` 都能识别；除 ``web``
        之外的任何取值都按 ``app`` 处理——线上 1.0.10 及更早的 APK 不带
        ``X-Client``，不能因此掉线。
    """
    value = (request.headers.get("X-Client") or "").strip().lower()
    return CLIENT_WEB if value == CLIENT_WEB else CLIENT_APP


def bump(user, client_type: str) -> int:
    """把账号在某一端上的会话版本 +1(该端旧令牌随即失效)。

    参数说明:
        user: 目标账号。
        client_type: ``"app"`` 或 ``"web"``，决定递增哪一端的版本。

    返回参数:
        递增后的新版本号；该端首次登录时建行并返回 2(初始行版本 1 再加一)。

    使用示例:
        ``version = bump(user, "web")``

    备注信息:
        ``DeviceSession`` 上 ``(user, client_type)`` 唯一，一个账号每端只有一行，
        因此这里只影响被指定的那一端，另一端在线的设备不受影响。
        自增走 ``F("version") + 1`` 在数据库内完成，并发登录不会两个请求都拿到
        同一个旧版本。不碰 ``logged_out_at`` 与 ``last_active_at``，这两列由
        :func:`login` / :func:`logout` 负责。
    """
    session, _ = DeviceSession.objects.get_or_create(
        user=user, client_type=client_type)
    DeviceSession.objects.filter(pk=session.pk).update(version=F("version") + 1)
    session.refresh_from_db(fields=["version"])
    return session.version


def login(user, client_type: str) -> int:
    """登录这一端:版本 +1、清空下线标记、刷新最后活跃时间。

    参数说明:
        user: 目标账号。
        client_type: ``"app"`` 或 ``"web"``，本次登录的端。

    返回参数:
        递增后的新版本号(**继续单调递增**:下线过的那一端再次登录不会复用旧版本,
        因此下线前签发的旧令牌依然对不上、依然 401)。

    使用示例:
        ``version = login(user, "app")``

    备注信息:
        三件事必须一次做完:版本 +1 顶掉同端旧设备;清空 ``logged_out_at`` 让这一端
        **重新出现在**登录设备列表里(否则被下线过的端再登录也看不见自己);
        ``last_active_at`` 是列表里的「最近活跃」。
        同类端互顶——只 +1 本端版本，另一端的令牌保持有效（一个 App + 一个网页）。
    """
    version = bump(user, client_type)
    DeviceSession.objects.filter(user_id=user.id, client_type=client_type).update(
        logged_out_at=None, last_active_at=timezone.now())
    return version


def logout(user, client_type: str) -> None:
    """把这一端下线:版本 +1(旧令牌失效)**并**打上下线标记(不再出现在列表里)。

    参数说明:
        user: 目标账号。
        client_type: ``"app"`` 或 ``"web"``，要下线的端。

    返回参数:
        无返回值。IM 侧的踢人由调用方经 Celery 入队，不在本函数里。

    使用示例:
        ``logout(user, "web")``

    备注信息:
        **打标记而不是删行**:删行会让该端版本号回到默认值,被下线设备手里的旧令牌
        反而又对得上 —— 那是安全问题。行留着按端唯一,版本照常单调递增,列表只看
        ``logged_out_at``。
        幂等:重复调用只会把 ``logged_out_at`` 刷成最新时间,版本继续 +1(无害,
        只会让更早的令牌更失效);该端从没登录过时也会建一行并标记为已下线,于是
        「踢一个从没登录过的端」不会让它凭空出现在列表里。
    """
    bump(user, client_type)
    DeviceSession.objects.filter(user_id=user.id, client_type=client_type).update(
        logged_out_at=timezone.now())


def touch(user, client_type: str) -> None:
    """把账号在某一端上的「最后活跃时间」刷成当前时间。

    参数说明:
        user: 目标账号(需要 ``id``)。
        client_type: ``"app"`` 或 ``"web"``。

    返回参数:
        无返回值。该端还没有会话行时静默跳过(登录路径先 ``login`` 建行,正常不会走到)。

    使用示例:
        ``touch(user, "app")``

    备注信息:
        只在 ``/auth/token/refresh`` 成功时单独调用(登录路径已由 ``login`` 一并落库):
        这两处才是「这一端确实在被使用」的证据。鉴权路径不调它 —— 每个请求都写一次库
        会把读接口拖成写接口,而「在线」另有账号级的 presence 通道。
    """
    DeviceSession.objects.filter(user_id=user.id, client_type=client_type).update(
        last_active_at=timezone.now())


def sessions_of(user):
    """列出账号**当前在用**的那几端(登录设备列表的数据源)。

    参数说明:
        user: 目标账号(需要 ``id``)。

    返回参数:
        ``DeviceSession`` 查询集,按 ``client_type`` 排序(``app`` 在前);
        **从没登录过、或已下线的端不会出现在结果里**(最多两行)。

    使用示例:
        ``sessions = sessions_of(request.user)``

    备注信息:
        已经被下线(``logged_out_at`` 有值)的端不返回 —— 「下线」对用户的可观察语义
        就是「从列表里消失」;那一端的会话行仍然留着,版本号继续单调递增,好让它的旧
        令牌保持失效。返回的是惰性查询集，遍历时才落库。
    """
    return (DeviceSession.objects
            .filter(user_id=user.id, logged_out_at__isnull=True)
            .order_by("client_type"))


def label_of(client_type: str) -> str:
    """取端类型的展示名(给客户端的 ``client_label``)。

    参数说明:
        client_type: ``"app"`` 或 ``"web"``。

    返回参数:
        中文展示名(如 ``App`` / ``网页端``);未知取值原样返回,不抛异常。

    使用示例:
        ``label = label_of("web")``

    备注信息:
        文案取自 ``CLIENT_LABELS``(由模型 ``CLIENT_TYPE_CHOICES`` 派生)，与模型
        choices 同源，改文案只需改模型那一处。
    """
    return CLIENT_LABELS.get(client_type, client_type)


def version_of(user_id: int, client_type: str):
    """取账号在某一端上的当前会话版本。

    参数说明:
        user_id: 账号 id。
        client_type: ``"app"`` 或 ``"web"``。

    返回参数:
        当前版本号;该端从未登录过(没有行)返回 ``None``。

    使用示例:
        ``version = version_of(42, "app")``

    备注信息:
        纯读，不做兜底。需要「没有行就按历史列取值」的语义时用
        :func:`current_version`；需要「没有行就补建」时用 :func:`ensure_version`。
    """
    return (DeviceSession.objects
            .filter(user_id=user_id, client_type=client_type)
            .values_list("version", flat=True)
            .first())


def current_version(user, client_type: str) -> int:
    """取账号在某一端上的「有效」会话版本,供签发与鉴权比对。

    参数说明:
        user: 账号实例(需要 ``id`` 与 ``session_version``)。
        client_type: ``"app"`` 或 ``"web"``。

    返回参数:
        该端的当前版本号；该端没有会话行时返回 ``User.session_version``(历史列)的值。

    使用示例:
        ``version = current_version(user, "web")``

    备注信息:
        为什么要有这一层兜底:端会话行是登录时建的,而 ``User.session_version`` 里留着
        迁移桥接前的历史值。**没有行**说明该端从未走过登录(例如造数脚本、压测账号,
        以及升级前的老账号在另一个端上),此时按历史列取值 —— 与升级前的行为完全一致,
        也是 ``0006`` 桥接迁移写进两行端会话的那个值。等 ``User.session_version`` 列
        删除时,这条兜底一并去掉(见设计文档 §10)。
        本函数**只读**，不会建行；签发令牌时调用它，不改库。
    """
    version = version_of(user.id, client_type)
    return user.session_version if version is None else version


def ensure_version(user, client_type: str) -> int:
    """确保该端有会话行(**不递增**),返回它的版本。

    参数说明:
        user: 账号实例。
        client_type: ``"app"`` 或 ``"web"``。

    返回参数:
        该端当前版本号；新建行时返回写入的 ``user.session_version``。

    使用示例:
        ``version = ensure_version(user, "app")``

    备注信息:
        用途:签发 IM 凭证前必须先有一个 imserver 见过的版本。存量账号、造数账号、
        压测账号可能从未在该端登录过(没有行),此时按历史列 ``User.session_version``
        补建一行 —— 与 ``0006`` 桥接迁移写入的值同源,因此不会把在线会话顶掉。
        行已存在时原样返回它的版本，**不递增**，不会导致已有设备掉线。
    """
    session, _ = DeviceSession.objects.get_or_create(
        user=user, client_type=client_type,
        defaults={"version": user.session_version})
    return session.version


def legacy_token_version(claims) -> int:
    """取令牌里带的会话版本,缺 claim 的历史令牌按初值处理。

    参数说明:
        claims: 已解码的 JWT payload(``dict`` 形态的令牌对象)。

    返回参数:
        令牌声称的版本号；缺 ``session_version`` claim 时返回 ``SESSION_VERSION_DEFAULT``。

    使用示例:
        ``version = legacy_token_version(token.payload)``

    备注信息:
        只解析不校验——比对由调用方拿它与 ``current_version`` 的结果做。
        缺 claim 的一条死路兜底是历史令牌(硬化前签发)的兼容口径。
    """
    return claims.get("session_version", SESSION_VERSION_DEFAULT)


def client_type_of_token(claims) -> str:
    """取令牌里带的端类型,缺 ``ct`` claim 的历史令牌按 ``app`` 兜底。

    参数说明:
        claims: 已解码的 JWT payload(``dict`` 形态的令牌对象)。

    返回参数:
        ``"app"`` 或 ``"web"``；缺 ``ct`` claim 时返回 ``CLIENT_APP``。

    使用示例:
        ``client_type = client_type_of_token(token.payload)``

    备注信息:
        鉴权与刷新都按它回查该端的会话版本，**不看请求头**——请求头只在签发时决定
        写哪一端，回查一律以令牌里的 ``ct`` 为准，否则漏带头就能顶掉另一端。
    """
    return claims.get("ct", CLIENT_APP)
