"""自建 IM 的灰度判定。"""

from django.conf import settings

SYSTEM_NOTICE_IDENTIFIER = "system_notice"


def _gray_uids():
    """解析灰度名单。

    Returns:
        ``None`` 表示全量;否则返回用户 id 集合。
    """
    gray = getattr(settings, "IM_SELF_GRAYLIST", "").strip()
    if gray == "all":
        return None
    return {int(item) for item in gray.split(",") if item.strip().isdigit()}


def use_self_im(user) -> bool:
    """登录时该用户是否走自建 IM。

    Args:
        user: 已登录用户。

    Returns:
        ``IM_BACKEND=self`` 且命中灰度名单时为 ``True``。
    """
    if getattr(settings, "IM_BACKEND", "tencent") != "self":
        return False
    gray = _gray_uids()
    return gray is None or user.id in gray


def self_enabled_for(identifier: str) -> bool:
    """某个 IM 账号的副作用是否走自建后端。

    Args:
        identifier: IM 账号,如 ``u9``;系统通知传收件人账号。

    Returns:
        ``IM_BACKEND=self`` 且该账号命中灰度名单时为 ``True``。
    """
    if getattr(settings, "IM_BACKEND", "tencent") != "self":
        return False
    gray = _gray_uids()
    if gray is None:
        return True
    uid = 0 if identifier == SYSTEM_NOTICE_IDENTIFIER else int(identifier.removeprefix("u"))
    return uid in gray
