"""语音转码的全局并发闸:同一时刻只放一路 ffmpeg/ffprobe。

聊天语音与资料语音自我介绍共用同一条转码链路(``im/voice.py``)。转码是重 CPU 子进程
(``ffprobe`` + ``ffmpeg``),生产机器扛不住多路并发,所以全局只放一路:抢到槽的调用方
直接转码,**抢不到的不阻塞、也不失败**,而是改走异步 —— 视图把文件落进临时区并入队
(``im/transcode_queue.py`` + ``im/tasks.py``),worker 拿到任务后再来抢同一个槽。槽因此
保护的是「worker 并发」,不是 gunicorn 的请求线程(第五轮安全审计 M-3)。

设计要点:
    1. **单槽信号量,不是队列**:抢不到立刻返回 ``False``,不阻塞等待 —— 阻塞只是把排队
       从请求线程挪进 Redis,出口延迟一点也没改善;异步那条路自然形成了有界排队;
    2. 抢槽是 ``SET key value NX EX <ttl>``(``cache.add``)的原子操作,``ttl`` 取
       ``settings.TRANSCODE_GATE_TTL``(默认 60 秒),远大于子进程 15 秒上限:
       进程崩溃没来得及释放时靠过期自愈,不会把语音入口永久锁死;
    3. **fail-open**:Redis 不可用时放行并记一条 warning(与 ``config/cache_utils.py``、
       ``discovery/quota.py`` 同口径)。转码有超时与 rlimit 兜底,不能因为缓存抖动
       让整个语音入口不可用。

注意事项:
    只有 ``acquire()`` 返回 ``True`` 的调用方需要 ``release()``;``release()`` 无条件删键,
    误删别人正在用的槽会把并发上限临时放宽到 2 路。异常路径请用 ``slot()`` 上下文管理器,
    它用 ``try/finally`` 保证一定释放 —— 直接 ``acquire()`` 后忘了 ``release()`` 的调用方,
    下一次语音上传要等 TTL 到点才能进。
    抢不到槽的两种正确反应:视图把它当「改走异步」的信号(落临时区 + 入队,回 202);
    worker 里的任务把它当「过几秒再试」(``self.retry``,行保持 ``pending``)。

关联文档:
    - 接口契约:docs/api/im.md(6.4 / 6.5)、docs/api/users.md(2.11 / 2.12)
    - 踩坑记录:docs/pitfalls/im.md「语音上传 503 + 50302」

文件信息:
    文件名称          config/transcode_gate.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-16        shiliu153          新建:语音转码全局并发闸(第五轮审计 M-3)
    2026-11-16        shiliu153          槽的语义改为「保护 worker 并发」:抢不到不再回 503
"""

import logging
import uuid
from contextlib import contextmanager

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# 槽的键名。全局只有一个槽,与入口无关:聊天语音与资料语音抢的是同一个槽。
SLOT_KEY = "transcode:slot"
DEFAULT_TTL_SECONDS = 60
DEFAULT_RETRY_AFTER_SECONDS = 5


def gate_ttl() -> int:
    """槽的存活时间(秒),同时也是「进程崩溃后的自愈时间」。

    参数说明:
        无。

    返回参数:
        ``settings.TRANSCODE_GATE_TTL``;未配置或配成非正数时回落到 60 秒。

    使用示例:
        ``cache.add(SLOT_KEY, token, gate_ttl())``(见本模块 ``acquire``)

    备注信息:
        每次现读 ``settings``(``override_settings`` 可测),不做模块级缓存。
        下限必须远大于 ``im/voice.py::PROCESS_TIMEOUT_SECONDS``(15 秒),否则正常转码
        还没结束槽就过期了,并发上限等于失效。
    """
    value = int(getattr(settings, "TRANSCODE_GATE_TTL", DEFAULT_TTL_SECONDS) or 0)
    return value if value > 0 else DEFAULT_TTL_SECONDS


def retry_after() -> int:
    """异步路径 202 响应里的 ``retry_after``,以及 worker 抢不到槽时的重试间隔(秒)。

    参数说明:
        无。

    返回参数:
        ``settings.TRANSCODE_GATE_RETRY_AFTER``;未配置或配成非正数时回落到 5 秒。

    使用示例:
        ``return Response({"retry_after": transcode_gate.retry_after()}, status=202)``
        (见 ``im/views.py`` 的 ``upload_voice``)

    备注信息:
        一次转码通常 0.2–0.5 秒,5 秒足够覆盖抖动;客户端按它轮询转码状态,
        worker 抢不到槽时也按它 ``self.retry`` 退避。
    """
    value = int(getattr(settings, "TRANSCODE_GATE_RETRY_AFTER", DEFAULT_RETRY_AFTER_SECONDS) or 0)
    return value if value > 0 else DEFAULT_RETRY_AFTER_SECONDS


def acquire() -> bool:
    """尝试占用全局转码槽(不等待)。

    参数说明:
        无。

    返回参数:
        抢到槽返回 ``True``(调用方**必须**在转码结束后 ``release()``);
        槽已被别的调用方占着返回 ``False``(视图改走异步、worker 退避重试);
        Redis 不可用时 fail-open 返回 ``True``。

    使用示例:
        ``with transcode_gate.slot() as acquired: ...``(见 ``im/views.py`` 的 ``upload_voice``)

    备注信息:
        ``cache.add`` 一条命令完成 ``SET NX EX``,不做重试与自旋 —— 等待等于把排队
        问题从请求线程挪到 Redis。值里放一个随机 token,排查时能看出是哪一次请求占的槽。
        Redis 异常一律按 fail-open 放行,记 ``transcode_gate_unavailable`` warning。
    """
    try:
        return bool(cache.add(SLOT_KEY, uuid.uuid4().hex, gate_ttl()))
    except Exception:  # noqa: BLE001  Redis 抖动不能让语音入口整体不可用
        logger.warning("transcode_gate_unavailable", extra={"action": "acquire"})
        return True


def release() -> None:
    """释放全局转码槽。

    参数说明:
        无。

    返回参数:
        无返回值。

    使用示例:
        ``transcode_gate.release()``(见本模块 ``slot``)

    备注信息:
        无条件删键:只有 ``acquire()`` 返回 ``True`` 的调用方该调用它。删除失败只记一条
        warning,不抛异常 —— 槽会在 TTL 到点后自愈,释放失败不该把已经转码成功的请求变成 500。
    """
    try:
        cache.delete(SLOT_KEY)
    except Exception:  # noqa: BLE001
        logger.warning("transcode_gate_unavailable", extra={"action": "release"})


@contextmanager
def slot():
    """占用转码槽的上下文管理器(异常路径也释放)。

    参数说明:
        无。

    返回参数:
        ``with`` 语句的 ``as`` 值是一个布尔:是否抢到槽。``False`` 表示调用方要么改走异步
        (视图落临时区 + 入队,回 202),要么退避重试(worker 里的 ``self.retry``)。

    使用示例:
        ``with transcode_gate.slot() as acquired: ...``(见 ``users/views.py`` 的 ``my_voice``)

    备注信息:
        抢不到槽时不抛异常,只 yield ``False`` —— 后续动作由调用方决定(视图回 202、
        任务重试)。退出时(含异常)对抢到的槽调 ``release()``,保证 ``voice.normalize`` /
        ``voice.normalize_profile`` 抛错时槽不泄漏。
    """
    acquired = acquire()
    try:
        yield acquired
    finally:
        if acquired:
            release()
