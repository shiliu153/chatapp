"""IM 副作用任务:所有腾讯 REST 调用统一走这里,响应路径禁止直接调用。

设计要点:
    1. ``im/client.py`` 的函数对外永不抛异常(失败返回 ``False`` 只记日志);
       这里把 ``False`` 转成异常,让 Celery 的重试策略真正生效;
    2. **任务参数一律是 ``user_id``,任务体内自己查库** —— 唯一的例外是
       ``delete_account``,原因见该函数的说明;
    3. 统一套用 ``RETRY_POLICY``(指数退避 + 抖动,最多 5 次)。

关联文档:
    - 踩坑记录:docs/pitfalls/im.md
"""

import logging

from celery import shared_task
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache

from users.models import PhotoStatus

from . import client as im_client

logger = logging.getLogger(__name__)

RETRY_POLICY = dict(autoretry_for=(Exception,), retry_backoff=True,
                    retry_jitter=True, max_retries=5)

KICK_PENDING_TTL = 300        # 「待踢旧会话」标记有效期(秒)
KICK_BACKSTOP_DELAY = 20      # 兜底任务延迟(秒):App 一直不拉签名时才补踢


def kick_pending_key(user_id: int) -> str:
    """拼出「待踢旧会话」标记的缓存键。

    Args:
        user_id: 账号 id。

    Returns:
        Redis 键名;登录时置位,``im/views.user_sig`` 踢完旧会话后清除。
    """
    return f"im:kick_pending:{user_id}"


def _require(ok: bool, what: str) -> None:
    """把 ``im/client.py`` 的 ``False`` 返回值转成异常,以触发 Celery 重试。

    Args:
        ok: 客户端调用结果。
        what: 调用名,用于异常信息。

    Raises:
        RuntimeError: ``ok`` 为 ``False`` 时。
    """
    if not ok:
        raise RuntimeError(f"IM {what} 失败")


def _user(user_id: int):
    """按主键取用户。

    Args:
        user_id: 账号 id。

    Returns:
        用户实例;不存在时返回 ``None``(账号可能已被注销,属正常情况)。
    """
    return get_user_model().objects.filter(id=user_id).first()


@shared_task(**RETRY_POLICY)
def send_match_notice(user_a_id: int, user_b_id: int) -> None:
    """配对成功:给双方各发一条灰条消息。

    任一方账号已不存在则静默跳过(不重试)。

    Args:
        user_a_id: 配对中 id 较小的一方。
        user_b_id: 配对中 id 较大的一方。
    """
    a, b = _user(user_a_id), _user(user_b_id)
    if a is None or b is None:
        return
    _require(im_client.send_match_notice(a.im_user_id, b.im_user_id), "send_match_notice")


@shared_task(**RETRY_POLICY)
def blacklist_add(owner_id: int, other_id: int) -> None:
    """拉黑:把对方加进本人的 IM 黑名单。

    Args:
        owner_id: 拉黑发起方的账号 id。
        other_id: 被拉黑方的账号 id。
    """
    owner, other = _user(owner_id), _user(other_id)
    if owner is None or other is None:
        return
    _require(im_client.black_list_add(owner.im_user_id, other.im_user_id), "black_list_add")


@shared_task(**RETRY_POLICY)
def blacklist_remove(owner_id: int, other_id: int) -> None:
    """解除拉黑:把对方从本人的 IM 黑名单移除。

    Args:
        owner_id: 操作方的账号 id。
        other_id: 被解除拉黑方的账号 id。
    """
    owner, other = _user(owner_id), _user(other_id)
    if owner is None or other is None:
        return
    _require(im_client.black_list_delete(owner.im_user_id, other.im_user_id), "black_list_delete")


@shared_task(**RETRY_POLICY)
def unmatch_blacklist(user_a_id: int, user_b_id: int) -> None:
    """解除配对:双向拉黑,双方都收不到、也发不出消息。

    这是「解除配对 = 彻底断开」的唯一实现点:腾讯 IM 只能由管理员侧
    REST 把对方加进黑名单,客户端只能拉黑自己这侧。

    Args:
        user_a_id: 配对一方(通常是发起解除的人)的账号 id。
        user_b_id: 另一方的账号 id。

    Raises:
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

    Args:
        user_id: 被封禁用户的账号 id。
        level: ``heavy`` 为全域封禁,其余按轻度限制处理。
        reason: 封禁原因,可为空。
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

    Args:
        user_id: 被解封用户的账号 id。
    """
    user = _user(user_id)
    if user is None:
        return
    _require(im_client.send_ban_lifted(user.im_user_id), "ban_lifted")


@shared_task(**RETRY_POLICY)
def report_handled(reporter_id: int) -> None:
    """举报处理完成:告知举报者(收件人是举报者,不是被举报人)。

    Args:
        reporter_id: 举报者的账号 id。
    """
    user = _user(reporter_id)
    if user is None:
        return
    _require(im_client.send_report_handled(user.im_user_id), "report_handled")


@shared_task(**RETRY_POLICY)
def post_commented(comment_id: int) -> None:
    """动态被评论:告知动态作者(自己评自己不打扰;内容缺失静默)。

    Args:
        comment_id: 新评论的主键;任务内再查库取作者与内容。
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


@shared_task(**RETRY_POLICY)
def post_replied(comment_id: int) -> None:
    """回复通知:告知被回复者(自己回复自己不发;内容缺失静默)。

    Args:
        comment_id: 新回复的主键;任务内再查库取被回复者与作者昵称。
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

    Args:
        user_id: 目标用户账号 id。
        kind: ``nick`` 同步昵称,``avatar`` 同步第一张已过审照片。

    Raises:
        ValueError: ``kind`` 不是 ``nick`` / ``avatar``。
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

    Args:
        user_id: 新用户的账号 id。
    """
    user = get_user_model().objects.filter(id=user_id).first()
    if user is None:
        return
    _require(im_client.import_account(user.im_user_id), "account_import")


@shared_task(**RETRY_POLICY)
def kick_pending(user_id: int) -> None:
    """兜底:登录后 App 没来拉签名(标记仍在)时,补踢一次旧 IM 会话。

    正常路径由 ``im/views.user_sig`` 在签发签名前同步踢掉并清标记(顺序保证
    踢的永远是新会话建立之前的旧会话);本任务只覆盖「App 从未登 IM」的情况。

    Args:
        user_id: 刚登录用户的账号 id。

    Raises:
        RuntimeError: 踢下线失败,交给 ``RETRY_POLICY`` 重试。
    """
    key = kick_pending_key(user_id)
    if not cache.get(key):
        return
    user = get_user_model().objects.filter(id=user_id).first()
    if user is None:
        cache.delete(key)
        return
    if im_client.kick_user(user.im_user_id):
        cache.delete(key)
    else:
        raise RuntimeError("IM kick 失败")


@shared_task(**RETRY_POLICY)
def pair_add(user_a_id: int, user_b_id: int) -> None:
    """配对成功:建立两人的聊天权限(H4)。

    Args:
        user_a_id: 配对一方账号 id。
        user_b_id: 配对另一方账号 id。

    Raises:
        RuntimeError: 同步失败,交给 ``RETRY_POLICY`` 重试。
    """
    a, b = _user(user_a_id), _user(user_b_id)
    if a is None or b is None:
        return
    _require(im_client.pair_add(a.im_user_id, b.im_user_id), "pair_add")


@shared_task(**RETRY_POLICY)
def pair_remove(user_a_id: int, user_b_id: int) -> None:
    """解除配对/拉黑:移除两人的聊天权限(H4)。

    Args:
        user_a_id: 一方账号 id。
        user_b_id: 另一方账号 id。

    Raises:
        RuntimeError: 同步失败,交给 ``RETRY_POLICY`` 重试。
    """
    a, b = _user(user_a_id), _user(user_b_id)
    if a is None or b is None:
        return
    _require(im_client.pair_remove(a.im_user_id, b.im_user_id), "pair_remove")


@shared_task(**RETRY_POLICY)
def sync_session_version(user_id: int) -> None:
    """把账号当前会话版本同步给自建 IM(旧 token 随即失效,H3)。

    登录时先入队一次:即使新设备还没来拉签名,旧设备的 token 也会在任务完成后
    被 imserver 拒绝;``user_sig`` 里还有一次同步,保证签发前版本一定已落库。

    Args:
        user_id: 刚登录用户的账号 id。

    Raises:
        RuntimeError: 同步失败,交给 ``RETRY_POLICY`` 重试。
    """
    user = _user(user_id)
    if user is None:
        return
    _require(im_client.set_session_version(user.im_user_id, user.session_version),
             "set_session_version")


@shared_task(**RETRY_POLICY)
def delete_account(im_user_id: str) -> None:
    """注销账号:先踢下线,再删 IM 账号。

    注意:参数是 **im_user_id 字符串**,不是 ``user_id`` —— 这是全项目唯一一处
    「任务参数不是 user_id」的例外。本任务由注销流程在**用户行已删除之后**入队,
    任务内查库必然拿到 ``None``,沿用 ``_user()`` 兜底会静默跳过、删号永不发生。
    调用方在事务提交后传入注销前取好的 ``user.im_user_id``(即 ``f"u{user.id}"``)。

    踢失败不阻塞删号(删号才是目的);删号失败抛异常交给 ``RETRY_POLICY`` 重试。

    Args:
        im_user_id: 注销前取好的 IM 账号字符串,如 ``u12``。

    Raises:
        RuntimeError: 删号失败,交给 ``RETRY_POLICY`` 重试。
    """
    im_client.kick_user(im_user_id)
    _require(im_client.delete_account(im_user_id), "delete_account")
