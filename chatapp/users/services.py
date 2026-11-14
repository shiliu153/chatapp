"""资料相关的领域服务:资料懒创建、照片审核、IM 资料同步、账号注销。

设计要点:
    1. **资料是懒创建的**:第一次访问时才建空 ``Profile`` 与空 ``Preference``,
       避免注册路径上多做两次写库;
    2. **IM 副作用一律走 Celery 且挂在 ``transaction.on_commit`` 上**:响应路径不做
       外部调用,入队也必须晚于提交,否则事务回滚了 IM 侧却已经改了;
    3. **账号注销的顺序不可调换**,详见 ``delete_account`` 的说明。

关联文档:
    - 踩坑记录:docs/pitfalls/backend.md「账号注销」

文件信息:
    文件名称          users/services.py
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
import time

from django.conf import settings
from django.core.cache import cache
from django.core.files.storage import default_storage
from django.db import IntegrityError, transaction
from django.utils import timezone

from accounts.device_session import CLIENT_TYPES
from im import tasks as im_tasks

from . import presence
from .models import (Photo, PhotoStatus, Preference, Profile, ProfileStatus, ProfileVisit,
                     ProfileVoice)

logger = logging.getLogger(__name__)

# 浏览计数按「自然小时」分桶,key 存活 1 小时即可覆盖整个窗口。
PROFILE_VIEW_TTL_SECONDS = 3600

# 访客记录:同一对 (viewer, owner) 30 分钟内只写一次,避免下拉刷新造成写放大。
PROFILE_VISIT_TTL_SECONDS = 1800
# 访客记录保留期:超过这个天数的行由 purge_profile_visits 清理。
PROFILE_VISIT_RETENTION_DAYS = 90


def record_profile_view(viewer_id: int, target_id: int) -> None:
    """记录一次「看了谁的资料」:落库访客记录,并按小时统计不同目标数(超阈值告警)。

    同一小时内重复看同一个人只算一次(``cache.add`` 返回 False 即已记过),
    这样阈值衡量的是**抓取广度**而不是刷新次数。

    参数说明:
        viewer_id: 浏览者账号 id。
        target_id: 被浏览者账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``record_profile_view(request.user.id, target.id)``

    备注信息:
        Redis / 数据库异常时只写 debug 日志,**绝不影响资料接口**;
        访客记录与抓取监控是两套独立窗口(30 分钟 vs 1 小时),不能共用一次 early return。
    """
    bucket = int(time.time()) // PROFILE_VIEW_TTL_SECONDS
    try:
        first_time = cache.add(f"profile_view:{viewer_id}:{target_id}:{bucket}", 1,
                               timeout=PROFILE_VIEW_TTL_SECONDS)
        if first_time:
            count_key = f"profile_view_count:{viewer_id}:{bucket}"
            try:
                count = cache.incr(count_key)
            except ValueError:      # key 不存在时 incr 抛 ValueError,补一次 set
                cache.set(count_key, 1, timeout=PROFILE_VIEW_TTL_SECONDS)
                count = 1
            if count == settings.PROFILE_SCRAPE_ALERT_PER_HOUR + 1:
                logger.warning("疑似资料抓取: viewer=%s 一小时内浏览了 %s 个不同用户",
                               viewer_id, count)
    except Exception:
        logger.debug("资料浏览计数失败(不影响响应)", exc_info=True)
    # 访客记录与上面的抓取监控是两套独立窗口(30 分钟 vs 1 小时),不能共用 early return。
    try:
        _record_visit(viewer_id, target_id)
    except Exception:
        logger.debug("访客记录失败(不影响响应)", exc_info=True)


def _record_visit(viewer_id: int, target_id: int) -> None:
    """把一次资料页访问写进 ``ProfileVisit``(每人一行,30 分钟窗口内只写一次)。

    隐身判断取 ``Profile.visits_hidden``:资料是懒创建的,取不到 profile 视为「未隐身」。
    写库放在内层 ``atomic()`` 里,失败只回滚到保存点,不会毒化外层事务
    (``GET /users/{id}`` 本身没有外层事务,但测试与嵌套调用有)。

    **只记录「会展示在访客列表里的人」**(M-2):访客列表只展示资料完善且有过审照片的
    人,所以资料未完善的访问者即使落库也不会被看到 —— 批量造号可以拿它把表写爆。
    判断口径与 ``discovery.services.visits_received_queryset`` 保持一致。

    参数说明:
        viewer_id: 浏览者账号 id。
        target_id: 被浏览者账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``_record_visit(viewer_id, target_id)``

    备注信息:
        自己被自己看、开启隐身、资料未完善、没有过审照片、30 分钟内已记过一次,
        这五种情况都直接返回;并发插入撞唯一约束时退化成一次 ``update(last_at=...)``。
    """
    if viewer_id == target_id:      # 自己看自己不算
        return
    viewer = (Profile.objects.filter(user_id=viewer_id)
              .values("visits_hidden", "status").first())
    if viewer is None or viewer["visits_hidden"]:
        return
    if viewer["status"] != ProfileStatus.COMPLETE:
        return
    if not Photo.objects.filter(user_id=viewer_id, status=PhotoStatus.APPROVED).exists():
        return
    if not cache.add(f"visit:{viewer_id}:{target_id}", 1, timeout=PROFILE_VISIT_TTL_SECONDS):
        return
    now = timezone.now()
    try:
        with transaction.atomic():
            ProfileVisit.objects.update_or_create(
                viewer_id=viewer_id, owner_id=target_id, defaults={"last_at": now})
            _trim_owner_visits(target_id)
    except IntegrityError:      # 并发插入撞唯一约束:退化成一次更新
        ProfileVisit.objects.filter(viewer_id=viewer_id, owner_id=target_id).update(last_at=now)


def _trim_owner_visits(owner_id: int) -> None:
    """每个 owner 只保留最近 N 条访客记录(M-2 的第二道闸)。

    ``N`` 取 ``settings.PROFILE_VISIT_MAX_PER_OWNER``(默认 500);``<=0`` 表示关闭。
    先 ``COUNT`` 再决定是否淘汰:超过上限的账号极少,正常写入只多一条索引计数。

    参数说明:
        owner_id: 被访问者账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``_trim_owner_visits(target_id)``

    备注信息:
        由 ``_record_visit`` 在写入事务内调用;淘汰按 ``last_at`` 倒序保留前 N 条,
        被删掉的行对应的人下次访问时会重新插入。
    """
    limit = settings.PROFILE_VISIT_MAX_PER_OWNER
    if limit <= 0:
        return
    visits = ProfileVisit.objects.filter(owner_id=owner_id)
    if visits.count() <= limit:
        return
    stale = list(visits.order_by("-last_at").values_list("id", flat=True)[limit:])
    if stale:
        ProfileVisit.objects.filter(id__in=stale).delete()



def get_profile(user):
    """取当前用户资料;没有就建空 Profile + 空 Preference(资料是懒创建的)。

    结果挂在 ``user`` 实例上做**请求内记忆**:一次请求里视图、权限类、序列化器
    会各调一次,不记忆就是每处两次 ``get_or_create``(2026-11-03 实测候选接口
    因此多打 6 条 SQL)。同一请求内 ``profile.save()`` 改的就是这个实例,不会读到旧值。

    参数说明:
        user: 当前用户。

    返回参数:
        该用户的 ``Profile`` 实例。

    使用示例:
        ``profile = get_profile(request.user)``

    备注信息:
        会顺带建空 ``Preference`` 并挂到 ``profile.preference`` 反向缓存上;
        记忆缓存在 ``user._profile_cache``,跨请求不可复用(请求结束后实例即弃)。
    """
    cached = getattr(user, "_profile_cache", None)
    if cached is not None:
        return cached
    profile, _ = Profile.objects.get_or_create(user=user)
    preference, _ = Preference.objects.get_or_create(profile=profile)
    # 把 preference 挂到反向一对一缓存上:否则随后的 ``profile.preference``
    # 还要再查一次(候选接口实测多打 1 条 SQL)。
    profile.preference = preference
    user._profile_cache = profile
    return profile


def review_photos(queryset, status, operator=None) -> int:
    """通过/驳回照片:落审核审计 + 重算资料完善状态;过审时把头像同步到 IM。admin 与 ops 共用。

    参数说明:
        queryset: 待审核照片的查询集。
        status: 目标审核状态(``PhotoStatus`` 取值)。
        operator: 执行审核的运营账号,可为 ``None``。

    返回参数:
        实际更新的照片条数。

    使用示例:
        ``review_photos(Photo.objects.filter(status=PhotoStatus.PENDING), PhotoStatus.APPROVED, request.user)``

    备注信息:
        照片数量变化会影响「资料完善」判定(掉回未完善 = 失去候选资格),所以每个受影响
        用户都要 ``refresh_status()``;``status=APPROVED`` 时逐人入队 IM 头像同步。
    """
    user_ids = set(queryset.values_list("user_id", flat=True))
    count = queryset.update(status=status, reviewed_by=operator, reviewed_at=timezone.now())
    # 照片数量变化会影响「资料完善」判定(掉回未完善 = 失去候选资格),必须重算
    for profile in Profile.objects.filter(user_id__in=user_ids):
        profile.refresh_status()
    if status == PhotoStatus.APPROVED:
        for user_id in user_ids:
            sync_im_avatar(user_id)
    return count


def sync_im_nickname(user) -> None:
    """昵称变更后同步到 IM 资料(经任务队列;失败可重试,不影响业务)。

    参数说明:
        user: 昵称已变更的用户。

    返回参数:
        无返回值。

    使用示例:
        ``sync_im_nickname(profile.user)``

    备注信息:
        昵称为空时直接返回(IM 侧没有可同步的内容);入队挂在 ``transaction.on_commit``
        上并带 ``robust=True``,事务回滚或提交后异常都不会影响主流程。
    """
    nickname = getattr(getattr(user, "profile", None), "nickname", "")
    if not nickname:
        return
    transaction.on_commit(lambda: im_tasks.sync_profile.delay(user.id, "nick"), robust=True)


def sync_im_avatar(user_id: int) -> None:
    """照片过审后把头像同步到 IM(任务内部取第一张过审照片的绝对 URL)。

    参数说明:
        user_id: 目标用户账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``sync_im_avatar(request.user.id)``

    备注信息:
        只入队、不查询:任务参数一律 user_id,真正的资料在任务内查库;
        入队同样挂在 ``transaction.on_commit`` 上。
    """
    transaction.on_commit(lambda: im_tasks.sync_profile.delay(user_id, "avatar"), robust=True)


def delete_account(user) -> None:
    """注销账号:删除该用户的全部数据,并清理磁盘文件 / 缓存 / IM 账号。

    顺序有讲究:
      1. 事务内先**收集**待删文件路径与 im_user_id(删行之后就取不到了,
         且 `user.delete()` 会把实例主键置为 None);
      2. 事务内删 User 行(CASCADE 清掉全部关联数据);
      3. 事务提交后(on_commit)删磁盘文件、清 Redis、入队 IM 删号 ——
         响应路径禁止外部调用,且入队必须晚于提交(否则事务回滚了 IM 号却没了)。

    参数说明:
        user: 待注销的用户实例。

    返回参数:
        无返回值。

    使用示例:
        ``delete_account(request.user)``

    备注信息:
        不可恢复:硬删除全部数据并释放手机号,同号可重新注册为全新账号;
        ``feed.models`` / ``im.models`` 延迟导入是为了避开 app 加载顺序问题。
    """
    from feed.models import PostImage   # 延迟导入,避免 app 加载顺序问题(同 im/tasks.py)
    from im.models import ChatImage, ChatVoice

    file_names = list(user.photos.values_list("file", flat=True))
    file_names += list(PostImage.objects.filter(post__author=user).values_list("file", flat=True))
    file_names += list(ChatImage.objects.filter(owner=user).values_list("file", flat=True))
    file_names += list(ChatImage.objects.filter(owner=user).values_list("thumb", flat=True))
    file_names += list(ChatVoice.objects.filter(owner=user).values_list("file", flat=True))
    file_names += list(ProfileVoice.objects.filter(profile__user=user)
                       .values_list("file", flat=True))
    user_id = user.id
    im_user_id = user.im_user_id

    user.delete()

    def _cleanup():
        for name in file_names:
            try:
                default_storage.delete(name)
            except Exception:
                logger.warning("注销删文件失败 name=%s", name, exc_info=True)
        presence.clear(user_id)
        # 「待踢旧会话」标记是按端的(多端在线),两端都要清
        for client_type in CLIENT_TYPES:
            cache.delete(im_tasks.kick_pending_key(user_id, client_type))
        im_tasks.delete_account.delay(im_user_id)

    transaction.on_commit(_cleanup, robust=True)
