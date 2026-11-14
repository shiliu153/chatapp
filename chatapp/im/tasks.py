"""IM 副作用任务:所有 IM 管理端调用统一走这里,响应路径禁止直接调用。

设计要点:
    1. ``im/client.py`` 的函数对外永不抛异常(失败返回 ``False`` 只记日志);
       这里把 ``False`` 转成异常,让 Celery 的重试策略真正生效;
    2. **任务参数一律是 ``user_id``,任务体内自己查库** —— 唯一的例外是
       ``delete_account``,原因见该函数的说明;
    3. 统一套用 ``RETRY_POLICY``(指数退避 + 抖动,最多 5 次);
    4. 多端在线后「踢谁」要分清:按端踢(同类互顶 / 登录)带 ``client_type``,
       踢全部端(封禁 / 注销 / 退出所有设备)不带它。

关联文档:
    - 踩坑记录:docs/pitfalls/im.md

文件信息:
    文件名称          im/tasks.py
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

    为什么键里必须带端:一个 App + 一个网页同时在线时,Web 登录只能踢 Web 的旧
    IM 会话。键不带端的话,两端共用一个标记,谁先来拉签名谁就把对方的在线会话踢了。

    参数说明:
        user_id: 账号 id。
        client_type: 端类型,取 ``app`` 或 ``web``,默认 ``app``。

    返回参数:
        Redis 键名 ``im:kick_pending:{user_id}:{client_type}``;登录时置位,
        ``im/views.user_sig`` 踢完本端旧会话后清除。

    使用示例:
        ``kick_pending_key(42, "app")``

    备注信息:
        置位方是登录路径(``im/views.py``,TTL 取 ``KICK_PENDING_TTL``),清除方是
        ``im/views.user_sig`` 与 ``kick_pending`` 自身;两端键互不影响。
    """
    return f"im:kick_pending:{user_id}:{client_type}"


def _require(ok: bool, what: str) -> None:
    """把 ``im/client.py`` 的 ``False`` 返回值转成异常,以触发 Celery 重试。

    参数说明:
        ok: 客户端调用结果,``True`` 表示成功。
        what: 调用名,用于异常信息。

    返回参数:
        无返回值。

    使用示例:
        ``_require(im_client.black_list_add(a.im_user_id, b.im_user_id), "black_list_add")``

    备注信息:
        ``ok`` 为 ``False`` 时抛 ``RuntimeError`` —— ``RETRY_POLICY`` 只对异常生效,
        客户端函数自身对外永不抛异常,这一层转换是重试能否发生的前提。
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
        ``_user(42)``

    备注信息:
        每次调用都查一次库,任务体内不缓存;返回 ``None`` 时各任务一律静默返回,
        不抛异常,因此不会进入重试。
    """
    return get_user_model().objects.filter(id=user_id).first()


def _notice_rate_limit():
    """notify 类任务的消费速率上限。

    为什么只限 notify:配对/评论/举报通知是突发流量的主要来源,而且可以等;
    ``critical`` 队列(封禁/踢人)不能限速,否则会把紧急操作排到通知后面。

    参数说明:
        无。

    返回参数:
        Celery 的 rate limit 字符串(如 ``50/s``);配置为 0 时返回 ``None``(不限速)。

    使用示例:
        ``_notice_rate_limit()``

    备注信息:
        在模块导入时(``@shared_task`` 装饰器求值阶段)调用,额度快照随之固定:
        改 ``settings.IM_NOTICE_RATE_PER_SEC`` 必须重启 Celery worker 才生效。
    """
    rate = int(getattr(settings, "IM_NOTICE_RATE_PER_SEC", 0) or 0)
    return f"{rate}/s" if rate > 0 else None


@shared_task(rate_limit=_notice_rate_limit(), **RETRY_POLICY)
def send_match_notice(user_a_id: int, user_b_id: int) -> None:
    """配对成功:给双方各发一条灰条消息。

    任一方账号已不存在则静默跳过(不重试)。

    参数说明:
        user_a_id: 配对中 id 较小的一方。
        user_b_id: 配对中 id 较大的一方。

    返回参数:
        无返回值。

    使用示例:
        ``send_match_notice.delay(12, 34)``

    备注信息:
        落 ``notify`` 队列(见 ``CELERY_TASK_ROUTES``),受 ``_notice_rate_limit()``
        限速;IM 侧失败抛 ``RuntimeError``,由 ``RETRY_POLICY`` 重试。
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
        ``blacklist_add.delay(12, 34)``

    备注信息:
        单向操作,只写 ``owner`` 侧黑名单;双方都收不到消息要靠 ``unmatch_blacklist``。
        落 ``critical`` 队列,不限速;任一方账号不存在时静默返回。
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
        ``blacklist_remove.delay(12, 34)``

    备注信息:
        与 ``blacklist_add`` 对称,只动 ``owner`` 侧;落 ``critical`` 队列,不限速。
        任一方账号不存在时静默返回。
    """
    owner, other = _user(owner_id), _user(other_id)
    if owner is None or other is None:
        return
    _require(im_client.black_list_delete(owner.im_user_id, other.im_user_id), "black_list_delete")


@shared_task(**RETRY_POLICY)
def unmatch_blacklist(user_a_id: int, user_b_id: int) -> None:
    """解除配对:双向拉黑,双方都收不到、也发不出消息。

    这是「解除配对 = 彻底断开」的唯一实现点:IM 侧只能由管理员侧
    REST 把对方加进黑名单,客户端只能拉黑自己这侧。

    参数说明:
        user_a_id: 配对一方(通常是发起解除的人)的账号 id。
        user_b_id: 另一方的账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``unmatch_blacklist.delay(12, 34)``

    备注信息:
        ``a`` 拉黑 ``b`` 与 ``b`` 拉黑 ``a`` 两次都成功后才算完成,任一方向失败即抛
        ``RuntimeError`` 交给 ``RETRY_POLICY`` 重试(黑名单写重复是幂等的)。落
        ``critical`` 队列,任一方账号不存在时静默返回。
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
        ``ban_notice.delay(42, "heavy", "发布违规内容")``

    备注信息:
        只有 ``level == "heavy"`` 才调 ``kick_user(block=True)``(同时写封禁键),轻度
        封禁只发通知;两步的顺序与串行性靠同一任务保证,拆成两个任务会被多 worker
        打乱。落 ``critical`` 队列,不限速。
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
        ``ban_lifted.delay(42)``

    备注信息:
        只发通知、不处理 IM 会话状态;落 ``critical`` 队列,账号不存在时静默返回。
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
        ``report_handled.delay(42)``

    备注信息:
        收件人必须传举报者 id,传被举报者等于把处理结果泄露给对方。落 ``notify``
        队列,受 ``_notice_rate_limit()`` 限速;账号不存在时静默返回。
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
        ``post_commented.delay(1024)``

    备注信息:
        参数是 ``comment_id`` 而非 ``user_id``(任务体内查库得到用户,仍符合「任务内
        不查 request」的口径);评论或动态已被删除、以及自己评论自己时直接返回。昵称
        缺失时降级成 ``u{author_id}``,正文只取前 50 字。落 ``notify`` 队列,受
        ``_notice_rate_limit()`` 限速。
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
        ``post_replied.delay(1024)``

    备注信息:
        参数同样是 ``comment_id``;``reply_to_id`` 为空(一级评论)或自己回复自己时
        直接返回,被回复的评论行已删除时任务内 ``reply_to`` 取不到也跟着跳过。落
        ``notify`` 队列,受 ``_notice_rate_limit()`` 限速。
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
        ``sync_profile.delay(42, "avatar")``

    备注信息:
        昵称为空、没有 ``APPROVED`` 照片、或没有资料行时静默返回(不重试);头像 URL
        由 ``MEDIA_BASE_URL`` 与 ``photo.file.url`` 拼成。``kind`` 不是 ``nick`` /
        ``avatar`` 时抛 ``ValueError``,该异常也会进 ``RETRY_POLICY``。落 ``bulk`` 队列。
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

    走 ``im_client.import_account`` 而非 ``ensure_account``:此处场景确定是新建账号,
    不需要先查状态。

    参数说明:
        user_id: 新用户的账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``import_account.delay(42)``

    备注信息:
        账号行已被删除(注册事务回滚)时静默返回;落 ``bulk`` 队列,导入失败抛
        ``RuntimeError`` 由 ``RETRY_POLICY`` 重试。
    """
    user = get_user_model().objects.filter(id=user_id).first()
    if user is None:
        return
    _require(im_client.import_account(user.im_user_id), "account_import")


@shared_task(**RETRY_POLICY)
def kick_pending(user_id: int, client_type: str = CLIENT_APP) -> None:
    """兜底:登录后 App 没来拉签名(标记仍在)时,补踢一次本端的旧 IM 会话。

    正常路径由 ``im/views.user_sig`` 在签发签名前同步踢掉并清标记(顺序保证
    踢的永远是新会话建立之前的旧会话);本任务只覆盖「App 从未登 IM」的情况。

    参数说明:
        user_id: 刚登录用户的账号 id。
        client_type: 刚登录的端(``app`` / ``web``);只踢这一端。

    返回参数:
        无返回值。

    使用示例:
        ``kick_pending.apply_async(args=[42, "web"], countdown=KICK_BACKSTOP_DELAY)``

    备注信息:
        标记不存在即返回(正常路径已由 ``user_sig`` 清掉);踢成功才清标记,踢失败保留
        标记并抛 ``RuntimeError`` 让重试仍能生效。落 ``critical`` 队列。
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
        ``kick_all_devices.delay(42)``

    备注信息:
        不传 ``client_type`` 才是踢全部端的语义,封禁与注销走这一条;按端踢必须改用
        ``kick_device``。未配置 ``CELERY_TASK_ROUTES``,落 default 队列;账号不存在时
        静默返回。
    """
    user = _user(user_id)
    if user is None:
        return
    _require(im_client.kick_user(user.im_user_id), "kick_user")


@shared_task(**RETRY_POLICY)
def kick_device(user_id: int, client_type: str) -> None:
    """把账号**某一端**的在线 IM 会话踢下线(登录设备页「下线该设备」,批次 M)。

    与 ``kick_all_devices`` 的区别只在踢的范围:这里带 ``client_type`` 只踢该端,
    另一端的 IM 连接必须留着 —— 用户点掉网页,手机上的 App 不能跟着掉线。

    参数说明:
        user_id: 账号 id(任务参数一律 user_id,任务内查库)。
        client_type: ``app`` / ``web``;只踢这一端。

    返回参数:
        无返回值。

    使用示例:
        ``kick_device.delay(42, "web")``

    备注信息:
        ``client_type`` 原样透传给 ``im_client.kick_user``,传 ``None`` 会退化成踢全部端,
        因此这里不给默认值。落 default 队列;账号不存在时静默返回。
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
        ``pair_add.delay(12, 34)``

    备注信息:
        ``im_pair`` 不落库等于两人发消息被 40302 拒绝,所以失败必须重试;落 ``critical``
        队列,任一方账号不存在时静默返回。
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
        ``pair_remove.delay(12, 34)``

    备注信息:
        与 ``pair_add`` 对称;未配置 ``CELERY_TASK_ROUTES``,落 default 队列,任一方账号
        不存在时静默返回。
    """
    a, b = _user(user_a_id), _user(user_b_id)
    if a is None or b is None:
        return
    _require(im_client.pair_remove(a.im_user_id, b.im_user_id), "pair_remove")


@shared_task(**RETRY_POLICY)
def sync_session_version(user_id: int) -> None:
    """把账号**两端**的会话版本同步给自建 IM(旧 token 随即失效,H3)。

    登录时先入队一次:即使新设备还没来拉签名,旧设备的 token 也会在任务完成后
    被 imserver 拒绝;``user_sig`` 里还有一次同步,保证签发前版本一定已落库。

    为什么循环两端而不是只同步登录那一端:登录只递增本端版本,另一端的在线会话
    必须继续有效,而它的 imserver 侧版本号也需要在「该端还没登过 IM」时补齐 ——
    否则 imserver 按 ``(uid, ct)`` 查不到行,无法判断新旧。

    参数说明:
        user_id: 刚登录用户的账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``sync_session_version.delay(42)``

    备注信息:
        逐端取 ``device_session.version_of``,取不到(该端从未登录过)就跳过该端,不算
        失败;任一端同步失败即抛 ``RuntimeError`` 重试。落 default 队列。
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

    注意:参数是 **im_user_id 字符串**,不是 ``user_id`` —— 这是全项目唯一一处
    「任务参数不是 user_id」的例外。本任务由注销流程在**用户行已删除之后**入队,
    任务内查库必然拿到 ``None``,沿用 ``_user()`` 兜底会静默跳过、删号永不发生。
    调用方在事务提交后传入注销前取好的 ``user.im_user_id``(即 ``f"u{user.id}"``)。

    踢失败不阻塞删号(删号才是目的);删号失败抛异常交给 ``RETRY_POLICY`` 重试。

    参数说明:
        im_user_id: 注销前取好的 IM 账号字符串,如 ``u12``。

    返回参数:
        无返回值。

    使用示例:
        ``delete_account.delay(user.im_user_id)``

    备注信息:
        ``kick_user`` 的返回值被忽略(不带 ``client_type``,即踢全部端);
        ``im_client.delete_account`` 返回 ``False`` 才抛 ``RuntimeError``。落 ``critical``
        队列,必须与注销事务的 ``on_commit`` 同批入队。
    """
    im_client.kick_user(im_user_id)
    _require(im_client.delete_account(im_user_id), "delete_account")
