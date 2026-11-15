"""IM 副作用任务:所有 IM 管理端调用统一走这里,响应路径禁止直接调用。

设计要点:
    1. ``im/client.py`` 的函数对外永不抛异常(失败返回 ``False`` 只记日志);
       这里把 ``False`` 转成异常,让 Celery 的重试策略真正生效;
    2. **任务参数是任务相关的 id,任务体内自己查库** —— 不传对象、不传 request。
       多数任务是账号 id,命名随语义变而含义相同(``user_id`` / ``reporter_id`` /
       ``owner_id`` / ``other_id`` / ``user_a_id`` / ``user_b_id``);``post_commented``
       与 ``post_replied`` 传的是评论主键 ``comment_id``,由任务体查出动态作者与被回复者。
       唯一**不查库**的例外是 ``delete_account``:参数是 ``im_user_id`` 字符串,因为它由
       注销流程在用户行已删除之后入队,原因见该函数的说明;
    3. 统一套用 ``RETRY_POLICY``(指数退避 + 抖动,最多 5 次);
    4. 多端在线后「踢谁」要分清:按端踢(同类互顶 / 登录)带 ``client_type``,
       踢全部端(封禁 / 注销 / 退出所有设备)不带它。

关联文档:
    - 踩坑记录:docs/pitfalls/im.md
"""

import logging

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache

from accounts import device_session
from accounts.device_session import CLIENT_APP, CLIENT_TYPES
from users.models import PhotoStatus

from . import client as im_client

logger = logging.getLogger(__name__)

RETRY_POLICY = dict(autoretry_for=(Exception,), retry_backoff=True,
                    retry_jitter=True, max_retries=5)

KICK_PENDING_TTL = 300        # 「待踢旧会话」标记有效期(秒)
KICK_BACKSTOP_DELAY = 20      # 兜底任务延迟(秒):App 一直不拉签名时才补踢


def kick_pending_key(user_id: int, client_type: str = CLIENT_APP) -> str:
    """拼出「待踢旧会话」标记的缓存键(**按端**)。

    参数说明:
        user_id: 账号 id。
        client_type: 端的类型,``app`` 或 ``web``。

    返回参数:
        Redis 键名,形如 ``im:kick_pending:{user_id}:{client_type}``。

    使用示例:
        ``kick_flag = kick_pending_key(user.id, client_type)``(见 ``im/views.py`` 的 ``user_sig``)

    备注信息:
        为什么键里必须带端:一个 App + 一个网页同时在线时,Web 登录只能踢 Web 的旧
        IM 会话。键不带端的话,两端共用一个标记,谁先来拉签名谁就把对方的在线会话踢了。
        登录时按本端置位(``KICK_PENDING_TTL`` 秒),``im/views.user_sig`` 踢完本端
        旧会话后清除;注销流程两端都清。
    """
    return f"im:kick_pending:{user_id}:{client_type}"


def _require(ok: bool, what: str) -> None:
    """把 ``im/client.py`` 的 ``False`` 返回值转成异常,以触发 Celery 重试。

    参数说明:
        ok: 客户端调用结果。
        what: 调用名,用于异常信息。

    返回参数:
        无返回值;``ok`` 为真时直接返回。

    使用示例:
        ``_require(im_client.kick_user(user.im_user_id), "kick_user")``(见本模块 ``kick_all_devices``)

    备注信息:
        RuntimeError: ``ok`` 为 ``False`` 时抛出中文异常信息,由 ``RETRY_POLICY`` 接手重试。
    """
    if not ok:
        raise RuntimeError(f"IM {what} 失败")


def _user(user_id: int):
    """按主键取用户。

    参数说明:
        user_id: 账号 id。

    返回参数:
        用户实例;不存在时返回 ``None``(账号可能已被注销,属正常情况)。

    使用示例:
        ``a, b = _user(user_a_id), _user(user_b_id)``(见本模块 ``pair_add``)

    备注信息:
        用 ``filter(...).first()`` 而不是 ``get``:账号可能已被注销,调用方必须自己判
        ``None`` 后静默返回,这一层不抛异常。
    """
    return get_user_model().objects.filter(id=user_id).first()


def _notice_rate_limit():
    """notify 类任务的消费速率上限。

    参数说明:
        无。

    返回参数:
        Celery 的 rate limit 字符串(如 ``50/s``);配置为 0 时返回 ``None``(不限速)。

    使用示例:
        ``@shared_task(rate_limit=_notice_rate_limit(), **RETRY_POLICY)``(见本模块 ``post_commented``)

    备注信息:
        为什么只限 notify:配对/评论/举报通知是突发流量的主要来源,而且可以等;
        ``critical`` 队列(封禁/踢人)不能限速,否则会把紧急操作排到通知后面。
        只在模块导入时求值一次,读 ``settings.IM_NOTICE_RATE_PER_SEC``(缺省 0)。
    """
    rate = int(getattr(settings, "IM_NOTICE_RATE_PER_SEC", 0) or 0)
    return f"{rate}/s" if rate > 0 else None


@shared_task(rate_limit=_notice_rate_limit(), **RETRY_POLICY)
def send_match_notice(user_a_id: int, user_b_id: int) -> None:
    """配对成功:给双方各发一条灰条消息。

    参数说明:
        user_a_id: 配对中 id 较小的一方。
        user_b_id: 配对中 id 较大的一方。

    返回参数:
        无返回值。

    使用示例:
        ``send_match_notice.delay(a_id, b_id)``(见 ``discovery/services.py`` 的 ``notify_match``)

    备注信息:
        任一方账号已不存在则静默跳过(不重试)。任务参数是任务相关的 id,任务体内
        自己查库;入队方负责 ``transaction.on_commit``,配对真正落库后才发灰条。
        限速由 ``_notice_rate_limit()`` 决定,发送失败按 ``RETRY_POLICY`` 重试。
    """
    a, b = _user(user_a_id), _user(user_b_id)
    if a is None or b is None:
        return
    _require(im_client.send_match_notice(a.im_user_id, b.im_user_id), "send_match_notice")


@shared_task(**RETRY_POLICY)
def blacklist_add(owner_id: int, other_id: int) -> None:
    """拉黑:把对方加进本人的 IM 黑名单。

    参数说明:
        owner_id: 拉黑发起方的账号 id。
        other_id: 被拉黑方的账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``blacklist_add.delay(blocker.id, blocked.id)``
        (见 ``moderation/services.py`` 的 ``sync_im_blacklist``)

    备注信息:
        任一方账号已不存在则静默跳过(不重试)。任务参数是任务相关的 id,任务体内
        自己查库;本任务只处理一个方向,双向拉黑见 ``unmatch_blacklist``。
        失败抛 ``RuntimeError``,交给 ``RETRY_POLICY`` 重试。
    """
    owner, other = _user(owner_id), _user(other_id)
    if owner is None or other is None:
        return
    _require(im_client.black_list_add(owner.im_user_id, other.im_user_id), "black_list_add")


@shared_task(**RETRY_POLICY)
def blacklist_remove(owner_id: int, other_id: int) -> None:
    """解除拉黑:把对方从本人的 IM 黑名单移除。

    参数说明:
        owner_id: 操作方的账号 id。
        other_id: 被解除拉黑方的账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``blacklist_remove.delay(blocker.id, blocked.id)``
        (见 ``moderation/services.py`` 的 ``sync_im_blacklist`` 的 ``add=False`` 分支)

    备注信息:
        任一方账号已不存在则静默跳过(不重试)。任务参数是任务相关的 id,任务体内
        自己查库;失败抛 ``RuntimeError``,交给 ``RETRY_POLICY`` 重试。
    """
    owner, other = _user(owner_id), _user(other_id)
    if owner is None or other is None:
        return
    _require(im_client.black_list_delete(owner.im_user_id, other.im_user_id), "black_list_delete")


@shared_task(**RETRY_POLICY)
def unmatch_blacklist(user_a_id: int, user_b_id: int) -> None:
    """解除配对:双向拉黑,双方都收不到、也发不出消息。

    参数说明:
        user_a_id: 配对一方(通常是发起解除的人)的账号 id。
        user_b_id: 另一方的账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``unmatch_blacklist.delay(me.id, other.id)``(见 ``discovery/views.py`` 的 ``unmatch``)

    备注信息:
        这是「解除配对 = 彻底断开」的唯一实现点:IM 侧只能由管理员侧 REST 把对方加进
        黑名单,客户端只能拉黑自己这侧。任一方账号已不存在则静默跳过。
        RuntimeError: 任一方向拉黑失败,交给 ``RETRY_POLICY`` 重试。
    """
    a, b = _user(user_a_id), _user(user_b_id)
    if a is None or b is None:
        return
    ok_ab = im_client.black_list_add(a.im_user_id, b.im_user_id)
    ok_ba = im_client.black_list_add(b.im_user_id, a.im_user_id)
    _require(ok_ab and ok_ba, "unmatch_blacklist")


@shared_task(**RETRY_POLICY)
def ban_notice(user_id: int, level: str, reason: str = "") -> None:
    """封禁说明;heavy 先发消息再踢下线(同一任务内串行,顺序不被多 worker 打乱)。

    参数说明:
        user_id: 被封禁用户的账号 id。
        level: ``heavy`` 为全域封禁,其余按轻度限制处理。
        reason: 封禁原因,可为空。

    返回参数:
        无返回值。

    使用示例:
        ``ban_notice.delay(user.id, "light", reason or "")``
        (见 ``moderation/services.py`` 的 ``log_ban_change``)

    备注信息:
        先发系统通知再踢下线,两步都在本任务内串行,顺序不被多 worker 打乱;只有
        ``heavy`` 才踢全部端。用户不存在则静默跳过。
        RuntimeError: 发送或踢下线失败,交给 ``RETRY_POLICY`` 重试。
    """
    user = _user(user_id)
    if user is None:
        return
    sent = im_client.send_ban_notice(user.im_user_id, level, reason)
    kicked = True
    if level == "heavy":
        kicked = im_client.kick_user(user.im_user_id, block=True)
    _require(sent and kicked, "ban_notice")


@shared_task(**RETRY_POLICY)
def ban_lifted(user_id: int) -> None:
    """解封:以系统通知身份告知用户限制已解除。

    参数说明:
        user_id: 被解封用户的账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``ban_lifted.delay(user.id)``(见 ``moderation/services.py`` 的 ``log_ban_change``)

    备注信息:
        用户不存在则静默跳过(不重试)。
        RuntimeError: 发送失败,交给 ``RETRY_POLICY`` 重试。
    """
    user = _user(user_id)
    if user is None:
        return
    _require(im_client.send_ban_lifted(user.im_user_id), "ban_lifted")


@shared_task(rate_limit=_notice_rate_limit(), **RETRY_POLICY)
def report_handled(reporter_id: int) -> None:
    """举报处理完成:告知举报者(收件人是举报者,不是被举报人)。

    参数说明:
        reporter_id: 举报者的账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``report_handled.delay(report.reporter_id)``
        (见 ``moderation/services.py`` 的 ``notify_report_handled``)

    备注信息:
        只在举报首次标记为「已处理」时入队,重复处理会重复打扰举报者;用户不存在则
        静默跳过。限速由 ``_notice_rate_limit()`` 决定。
        RuntimeError: 发送失败,交给 ``RETRY_POLICY`` 重试。
    """
    user = _user(reporter_id)
    if user is None:
        return
    _require(im_client.send_report_handled(user.im_user_id), "report_handled")


@shared_task(rate_limit=_notice_rate_limit(), **RETRY_POLICY)
def post_commented(comment_id: int) -> None:
    """动态被评论:告知动态作者(自己评自己不打扰;内容缺失静默)。

    参数说明:
        comment_id: 新评论的主键;任务内再查库取作者与内容。

    返回参数:
        无返回值。

    使用示例:
        ``post_commented.delay(comment.id)``(见 ``feed/services.py`` 的 ``notify_comment_created``)

    备注信息:
        任务参数是评论主键而非账号 id,任务体内自己查出动态作者与被回复者。评论或
        动态已删除、自己评自己时静默返回;内容摘要截前 50 字。
        RuntimeError: 发送失败,交给 ``RETRY_POLICY`` 重试。
    """
    from feed.models import PostComment   # 延迟导入,避免 app 加载顺序问题

    comment = (PostComment.objects.filter(id=comment_id)
               .select_related("post__author__profile", "author__profile").first())
    if comment is None or comment.post is None:
        return
    author = comment.post.author
    if author.id == comment.author_id:
        return
    profile = getattr(comment.author, "profile", None)
    nickname = (profile.nickname if profile else "") or f"u{comment.author_id}"
    _require(im_client.send_post_commented(author.im_user_id, nickname, comment.text[:50]),
             "post_commented")


@shared_task(rate_limit=_notice_rate_limit(), **RETRY_POLICY)
def post_replied(comment_id: int) -> None:
    """回复通知:告知被回复者(自己回复自己不发;内容缺失静默)。

    参数说明:
        comment_id: 新回复的主键;任务内再查库取被回复者与作者昵称。

    返回参数:
        无返回值。

    使用示例:
        ``post_replied.delay(comment.id)``(见 ``feed/services.py`` 的 ``notify_comment_created``)

    备注信息:
        任务参数是评论主键而非账号 id,任务体内自己查出动态作者与被回复者。不是回复、
        评论已删、自己回复自己时静默返回;内容摘要截前 50 字。
        RuntimeError: 发送失败,交给 ``RETRY_POLICY`` 重试。
    """
    from feed.models import PostComment   # 延迟导入,避免 app 加载顺序问题

    comment = (PostComment.objects.filter(id=comment_id)
               .select_related("author__profile", "reply_to__profile").first())
    if comment is None or comment.reply_to_id is None:
        return
    if comment.reply_to_id == comment.author_id:
        return
    profile = getattr(comment.author, "profile", None)
    nickname = (profile.nickname if profile else "") or f"u{comment.author_id}"
    _require(im_client.send_post_replied(comment.reply_to.im_user_id, nickname,
                                         comment.text[:50]), "post_replied")


@shared_task(**RETRY_POLICY)
def sync_profile(user_id: int, kind: str) -> None:
    """把资料同步到 IM(kind: nick|avatar);没有可同步的值时静默跳过。

    参数说明:
        user_id: 目标用户账号 id。
        kind: ``nick`` 同步昵称,``avatar`` 同步第一张已过审照片。

    返回参数:
        无返回值。

    使用示例:
        ``sync_profile.delay(user.id, "nick")``(见 ``users/services.py`` 的 ``sync_im_nickname``)

    备注信息:
        昵称为空、没有已过审照片、用户或资料不存在时都静默返回。任务参数是任务相关
        的 id,任务体内自己查库。
        ValueError: ``kind`` 不是 ``nick`` / ``avatar`` 时抛出。
    """
    user = _user(user_id)
    if user is None:
        return
    profile = getattr(user, "profile", None)
    if profile is None:
        return
    if kind == "nick":
        if not profile.nickname:
            return
        _require(im_client.set_profile_nick(user.im_user_id, profile.nickname), "sync_profile:nick")
    elif kind == "avatar":
        photo = user.photos.filter(status=PhotoStatus.APPROVED).first()
        if photo is None:
            return
        url = f"{settings.MEDIA_BASE_URL.rstrip('/')}{photo.file.url}"
        _require(im_client.set_profile_avatar(user.im_user_id, url), "sync_profile:avatar")
    else:
        raise ValueError(f"未知的资料同步类型 kind={kind}")


@shared_task(**RETRY_POLICY)
def import_account(user_id: int) -> None:
    """新用户注册后导入 IM 账号。

    参数说明:
        user_id: 新用户的账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``import_account.delay(user.id)``(见 ``accounts/views.py`` 的 ``sms_verify._after_commit``)

    备注信息:
        走 ``im_client.import_account`` 而非 ``ensure_account``:此处场景确定是新建账号,
        不需要先查状态。用户不存在则静默跳过。
        RuntimeError: 建号失败,交给 ``RETRY_POLICY`` 重试。
    """
    user = get_user_model().objects.filter(id=user_id).first()
    if user is None:
        return
    _require(im_client.import_account(user.im_user_id), "account_import")


@shared_task(**RETRY_POLICY)
def kick_pending(user_id: int, client_type: str = CLIENT_APP) -> None:
    """兜底:登录后 App 没来拉签名(标记仍在)时,补踢一次本端的旧 IM 会话。

    参数说明:
        user_id: 刚登录用户的账号 id。
        client_type: 刚登录的端(``app`` / ``web``);只踢这一端。

    返回参数:
        无返回值。

    使用示例:
        ``kick_pending.apply_async(args=[user.id, client_type], countdown=im_tasks.KICK_BACKSTOP_DELAY)``
        (见 ``accounts/views.py`` 的 ``sms_verify._after_commit``)

    备注信息:
        正常路径由 ``im/views.user_sig`` 在签发签名前同步踢掉并清标记(顺序保证踢的
        永远是新会话建立之前的旧会话);本任务只覆盖「App 从未登 IM」的情况,因此唯一
        入队点带 ``KICK_BACKSTOP_DELAY`` 秒延迟,不用 ``delay``。标记不存在时直接返回,
        踢成功即清标记。
        RuntimeError: 踢下线失败,交给 ``RETRY_POLICY`` 重试(标记保留,下次再踢)。
    """
    key = kick_pending_key(user_id, client_type)
    if not cache.get(key):
        return
    user = get_user_model().objects.filter(id=user_id).first()
    if user is None:
        cache.delete(key)
        return
    if im_client.kick_user(user.im_user_id, client_type=client_type):
        cache.delete(key)
    else:
        raise RuntimeError("IM kick 失败")


@shared_task(**RETRY_POLICY)
def kick_all_devices(user_id: int) -> None:
    """把账号**所有端**的在线 IM 会话踢下线(退出所有设备 / 重封禁兜底)。

    参数说明:
        user_id: 账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``kick_all_devices.delay(user.id)``(见 ``accounts/views.py`` 的 ``logout_all``)

    备注信息:
        不带 ``client_type``,语义是踢全部端(封禁 / 注销 / 退出所有设备);按端踢用
        ``kick_device``。账号不存在则静默跳过。
        RuntimeError: 踢下线失败,交给 ``RETRY_POLICY`` 重试。
    """
    user = _user(user_id)
    if user is None:
        return
    _require(im_client.kick_user(user.im_user_id), "kick_user")


@shared_task(**RETRY_POLICY)
def kick_device(user_id: int, client_type: str) -> None:
    """把账号**某一端**的在线 IM 会话踢下线(登录设备页「下线该设备」,批次 M)。

    参数说明:
        user_id: 账号 id(任务参数是任务相关的 id,任务内自己查库)。
        client_type: ``app`` / ``web``;只踢这一端。

    返回参数:
        无返回值。

    使用示例:
        ``kick_device.delay(request.user.id, client_type)``(见 ``accounts/views.py`` 的 ``device_logout``)

    备注信息:
        与 ``kick_all_devices`` 的区别只在踢的范围:这里带 ``client_type`` 只踢该端,
        另一端的 IM 连接必须留着 —— 用户点掉网页,手机上的 App 不能跟着掉线。
        账号不存在则静默跳过。
        RuntimeError: 踢下线失败,交给 ``RETRY_POLICY`` 重试。
    """
    user = _user(user_id)
    if user is None:
        return
    _require(im_client.kick_user(user.im_user_id, client_type=client_type), "kick_device")


@shared_task(**RETRY_POLICY)
def pair_add(user_a_id: int, user_b_id: int) -> None:
    """配对成功:建立两人的聊天权限(H4)。

    参数说明:
        user_a_id: 配对一方账号 id。
        user_b_id: 配对另一方账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``pair_add.delay(a_id, b_id)``(见 ``discovery/services.py`` 的 ``notify_match``)

    备注信息:
        任一方账号已不存在则静默跳过。任务参数是任务相关的 id,任务体内自己查库。
        RuntimeError: 同步失败,交给 ``RETRY_POLICY`` 重试。
    """
    a, b = _user(user_a_id), _user(user_b_id)
    if a is None or b is None:
        return
    _require(im_client.pair_add(a.im_user_id, b.im_user_id), "pair_add")


@shared_task(**RETRY_POLICY)
def pair_remove(user_a_id: int, user_b_id: int) -> None:
    """解除配对/拉黑:移除两人的聊天权限(H4)。

    参数说明:
        user_a_id: 一方账号 id。
        user_b_id: 另一方账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``pair_remove.delay(me.id, other.id)``(见 ``discovery/views.py`` 的 ``unmatch``)

    备注信息:
        任一方账号已不存在则静默跳过。
        RuntimeError: 同步失败,交给 ``RETRY_POLICY`` 重试。
    """
    a, b = _user(user_a_id), _user(user_b_id)
    if a is None or b is None:
        return
    _require(im_client.pair_remove(a.im_user_id, b.im_user_id), "pair_remove")


@shared_task(**RETRY_POLICY)
def sync_session_version(user_id: int) -> None:
    """把账号**两端**的会话版本同步给自建 IM(旧 token 随即失效,H3)。

    参数说明:
        user_id: 刚登录用户的账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``sync_session_version.delay(user.id)``
        (见 ``accounts/views.py`` 的 ``sms_verify._after_commit``)

    备注信息:
        登录时先入队一次:即使新设备还没来拉签名,旧设备的 token 也会在任务完成后
        被 imserver 拒绝;``user_sig`` 里还有一次同步,保证签发前版本一定已落库。
        循环两端而不是只同步登录那一端:登录只递增本端版本,另一端的在线会话必须继续
        有效,而它的 imserver 侧版本号也需要在「该端还没登过 IM」时补齐 —— 否则
        imserver 按 ``(uid, ct)`` 查不到行,无法判断新旧。某端没有会话版本时跳过该端。
        RuntimeError: 同步失败,交给 ``RETRY_POLICY`` 重试。
    """
    user = _user(user_id)
    if user is None:
        return
    for client_type in CLIENT_TYPES:
        version = device_session.version_of(user.id, client_type)
        if version is None:
            continue
        _require(im_client.set_session_version(user.im_user_id, version,
                                               client_type=client_type),
                 "set_session_version")


@shared_task(**RETRY_POLICY)
def delete_account(im_user_id: str) -> None:
    """注销账号:先踢下线,再删 IM 账号。

    参数说明:
        im_user_id: 注销前取好的 IM 账号字符串,如 ``u12``。

    返回参数:
        无返回值。

    使用示例:
        ``delete_account.delay(im_user_id)``(见 ``users/services.py`` 的 ``delete_account``)

    备注信息:
        注意:参数是 **im_user_id 字符串**,不是 ``user_id`` —— 这是全项目唯一**不查库**的
        例外(其余任务的参数都是任务相关的 id,由任务体自己查库)。本任务由注销流程在
        **用户行已删除之后**入队,任务内查库必然拿到 ``None``,沿用 ``_user()`` 兜底会
        静默跳过、删号永不发生。调用方在事务提交后传入注销前取好的 ``user.im_user_id``
        (即 ``f"u{user.id}"``)。踢失败不阻塞删号(删号才是目的)。
        RuntimeError: 删号失败,交给 ``RETRY_POLICY`` 重试。
    """
    im_client.kick_user(im_user_id)
    _require(im_client.delete_account(im_user_id), "delete_account")
