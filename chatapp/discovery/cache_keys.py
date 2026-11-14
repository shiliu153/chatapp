"""候选池缓存的版本键与失效入口。

为什么单独一个模块:``moderation``、``ops``、``users`` 都要让候选池失效,但它们
不能反向依赖 ``discovery.services``(services 依赖 ``moderation.services``,会成环)。
这里只依赖 ``config.cache_utils``,谁都能安全导入。

版本语义:
    - ``disc:ver:{uid}``:只影响这个用户自己的候选池(滑卡、改偏好);
    - ``disc:ver:global``:影响所有人的候选池(照片过审、资料字段变更、封禁)。

文件信息:
    文件名称          discovery/cache_keys.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-14        shiliu153          补齐文件头与函数注释
"""

from config import cache_utils

POOL_VERSION_KEY = "disc:ver:global"


def user_version_key(user_id: int) -> str:
    """单个用户的候选池版本键。

    参数说明:
        user_id: 账号 id。

    返回参数:
        Redis 键名。

    使用示例:
        ``user_version_key(42)``

    备注信息:
        键名格式必须与 ``discovery.services`` 拼缓存键时用的一致,两侧各写一份就会读到旧池。
    """
    return f"disc:ver:{user_id}"


def invalidate_candidates(user_id: int) -> None:
    """让某个用户的候选池缓存失效(滑卡、改偏好)。

    参数说明:
        user_id: 账号 id。

    返回参数:
        无返回值。

    使用示例:
        ``invalidate_candidates(request.user.id)``

    备注信息:
        走版本号自增而不是删键:旧键自然过期,不需要枚举这个用户派生出的全部缓存键。
    """
    cache_utils.bump_version(user_version_key(user_id))


def invalidate_pool_globally() -> None:
    """让所有人的候选池缓存失效(照片过审、资料变更、封禁)。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``invalidate_pool_globally()``

    备注信息:
        影响全站候选池,只在跨用户可见的数据变化时调用;照片过审批量回调里逐张调用会让版本号狂涨。
    """
    cache_utils.bump_version(POOL_VERSION_KEY)
