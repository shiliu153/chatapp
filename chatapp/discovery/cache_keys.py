"""候选池缓存的版本键与失效入口。

为什么单独一个模块:``moderation``、``ops``、``users`` 都要让候选池失效,但它们
不能反向依赖 ``discovery.services``(services 依赖 ``moderation.services``,会成环)。
这里只依赖 ``config.cache_utils``,谁都能安全导入。

版本语义:
    - ``disc:ver:{uid}``:只影响这个用户自己的候选池(滑卡、改偏好);
    - ``disc:ver:global``:影响所有人的候选池(照片过审、资料字段变更、封禁)。
"""

from config import cache_utils

POOL_VERSION_KEY = "disc:ver:global"


def user_version_key(user_id: int) -> str:
    """单个用户的候选池版本键。

    Args:
        user_id: 账号 id。

    Returns:
        Redis 键名。
    """
    return f"disc:ver:{user_id}"


def invalidate_candidates(user_id: int) -> None:
    """让某个用户的候选池缓存失效(滑卡、改偏好)。

    Args:
        user_id: 账号 id。
    """
    cache_utils.bump_version(user_version_key(user_id))


def invalidate_pool_globally() -> None:
    """让所有人的候选池缓存失效(照片过审、资料变更、封禁)。"""
    cache_utils.bump_version(POOL_VERSION_KEY)
