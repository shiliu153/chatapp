import threading

from django.utils import timezone

from im import client as im_client

from .models import Preference, Profile


def get_profile(user):
    """取当前用户资料;没有就建空 Profile + 空 Preference(资料是懒创建的)。"""
    profile, _ = Profile.objects.get_or_create(user=user)
    Preference.objects.get_or_create(profile=profile)
    return profile


def review_photos(queryset, status, operator=None) -> int:
    """通过/驳回照片:落审核审计 + 重算相关用户的资料完善状态。admin 与 ops 共用。"""
    user_ids = set(queryset.values_list("user_id", flat=True))
    count = queryset.update(status=status, reviewed_by=operator, reviewed_at=timezone.now())
    # 照片数量变化会影响「资料完善」判定(掉回未完善 = 失去候选资格),必须重算
    for profile in Profile.objects.filter(user_id__in=user_ids):
        profile.refresh_status()
    return count


def sync_im_nickname(user) -> None:
    """昵称变更后同步到 IM 资料(后台线程;失败只记日志,不影响业务)。"""
    nickname = getattr(getattr(user, "profile", None), "nickname", "")
    if not nickname:
        return
    _dispatch_async(im_client.set_profile_nick, user.im_user_id, nickname)


def _dispatch_async(fn, *args) -> None:
    """IM 调用丢后台线程,接口响应不等腾讯 REST(同 moderation.services._dispatch_async)。"""
    threading.Thread(target=fn, args=args, daemon=True).start()
