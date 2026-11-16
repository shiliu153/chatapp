"""语音转码的临时暂存区:异步转码前把原始音频落到 ``MEDIA_ROOT/tmp/voice/``。

抢不到转码槽的上传不再回 503,而是把原始文件先暂存、再入队交给 Celery worker
(第五轮审计 M-3)。本模块只做「暂存、读回、删除」三件事与失败原因的分装,转码本身
仍走 ``im.voice.normalize``。

设计要点:
    1. **临时路径写在行的 ``file`` 列上**:``pending`` 行没有正式文件,``file`` 存的是
       临时区相对路径;任务参数因此依旧只有行 id,任务体内从行上读路径(与
       ``im/tasks.py`` 的既有纪律一致:不传文件内容、不传对象);
    2. **文件名带 uuid**:``/media/tmp/`` 不在 nginx 的聊天媒体验签范围内,随机名是
       唯一防枚举手段 —— 聊天语音是私聊内容,不能被按序号试出来;
    3. **临时区不计入配额**:配额按库里的 ``bytes`` 求和,``pending`` 行 ``bytes=0``,
       正式落盘前才查配额(超限写 ``transcode_error=41301``);
    4. **谁写谁删**:成功与失败都由任务删掉临时文件;进程崩在中间留下的残骸由
       ``manage.py voice_transcode_cleanup`` 按 24 小时兜底清理。

注意事项:
    暂存的字节一律经 ``django.core.files.storage`` 读写,不拼 ``MEDIA_ROOT`` 绝对路径 ——
    以后换存储后端时这里不用跟着改。删文件失败只记 warning,不抛异常:临时文件残留是
    兜底命令的活,不能因此把「转码其实成功了」的请求变成失败。

关联文档:
    - 接口契约:docs/api/im.md(6.4 / 6.5)、docs/api/users.md(2.11 / 2.12)
    - 运维命令:docs/standards/dev-commands.md §2(``voice_transcode_cleanup``)

文件信息:
    文件名称          im/transcode_queue.py
    项目名称          chat_app / chatapp
    公司名称          个人项目（shiliu153）
    版本信息          查看 app/pubspec.yaml 内 version 字段 版本说明
    开发环境          Python 3.11 + Django 5.2 LTS
    适用平台          Linux x86_64 服务端
    仓库地址          https://github.com/shiliu153/chatapp
    修改记录
    2026-11-16        shiliu153          新建:语音异步转码的临时暂存区(第五轮审计 M-3)
"""

import logging
import uuid

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

from config import error_codes

from . import voice
from .models import TranscodeStatus

logger = logging.getLogger(__name__)

# 临时区在存储里的前缀(相对 ``MEDIA_ROOT``)。与 ``chat/``、``voices/`` 平级,
# 清理命令与兜底扫描都按它定位。
TMP_PREFIX = "tmp/voice"
# 兜底清理的默认阈值(小时):比「一次转码 15 秒」大三个数量级,不会误删正在跑的临时文件。
STALE_HOURS = 24

# 失败原因里出现业务码时,给客户端配一句可以直接展示的文案。
_CODE_MESSAGES = {
    str(error_codes.STORAGE_QUOTA_EXCEEDED): "存储空间已满,请先清理旧内容",
    str(error_codes.CHAT_VOICE_UNAVAILABLE): "转码服务暂不可用,请稍后重试",
}


def staged_name(content_type: str) -> str:
    """拼一个新临时文件的存储相对路径(``tmp/voice/<uuid>.<ext>``)。

    参数说明:
        content_type: 上传声明的 MIME(可带 ``;codecs=...`` 参数)。

    返回参数:
        形如 ``tmp/voice/3f2a....webm`` 的相对路径;MIME 不在白名单内时抛
        ``voice.VoiceError``(与同步路径同一套文案)。

    使用示例:
        ``name = transcode_queue.staged_name(upload.content_type)``(见 ``im/views.py`` 的
        ``upload_voice``)

    备注信息:
        扩展名由 ``voice.ALLOWED_CONTENT_TYPES`` 决定,不取上传文件名 —— 客户端给的名字
        不可信,worker 还要靠扩展名反推 MIME。
    """
    suffix = voice.ALLOWED_CONTENT_TYPES.get(voice.base_content_type(content_type))
    if suffix is None:
        raise voice.VoiceError("只支持 M4A/AAC/WebM/OGG 音频")
    return f"{TMP_PREFIX}/{uuid.uuid4().hex}{suffix}"


def stage(raw: bytes, name: str) -> str:
    """把原始字节写进临时区。

    参数说明:
        raw: 上传文件的原始字节。
        name: ``staged_name()`` 给出的存储相对路径。

    返回参数:
        实际写入的存储相对路径;存储层返回的路径与入参不一致时以返回值(库里的 ``file``
        列)为准,避免两者漂移。

    使用示例:
        ``name = transcode_queue.stage(upload.read(), name)``(见 ``im/views.py`` 的
        ``upload_voice``)

    备注信息:
        写失败(磁盘满等)直接抛 ``OSError``,由调用方回 500 —— 这种失败重试也没用,
        不能让客户端拿到一个「等着转码」但文件根本不存在的 202。
    """
    return default_storage.save(name, ContentFile(raw))


def read(name: str) -> bytes:
    """读回暂存的原始字节。

    参数说明:
        name: 行上 ``file`` 列的存储相对路径。

    返回参数:
        文件字节。

    使用示例:
        ``raw = transcode_queue.read(row.file.name)``(见 ``im/tasks.py`` 的
        ``transcode_chat_voice``)

    备注信息:
        文件不存在时抛存储层的 ``FileNotFoundError``(``OSError`` 子类),由任务转成
        ``failed`` —— 这通常意味着兜底清理已经收走过期行,重试没有意义。
    """
    with default_storage.open(name, "rb") as handle:
        return handle.read()


def discard(name: str) -> None:
    """删除一个临时文件(幂等)。

    参数说明:
        name: 存储相对路径;空串直接返回。

    返回参数:
        无返回值。

    使用示例:
        ``transcode_queue.discard(staged)``(见 ``im/tasks.py`` 的两个转码任务)

    备注信息:
        删失败只记 ``voice_tmp_delete_failed`` warning,不抛异常:残留由兜底命令处理。
    """
    if not name:
        return
    try:
        default_storage.delete(name)
    except Exception:  # noqa: BLE001  临时文件删不掉不该让转码结果变成失败
        logger.warning("voice_tmp_delete_failed", extra={"name": name})


def is_staged(name: str) -> bool:
    """判断一个 ``file`` 路径是不是临时区的(而不是正式媒体路径)。

    参数说明:
        name: 存储相对路径。

    返回参数:
        在 ``tmp/voice/`` 下返回 ``True``;空串或其他路径返回 ``False``。

    使用示例:
        ``if transcode_queue.is_staged(old_name): ...``(见 ``users/views.py`` 的
        ``my_voice``)

    备注信息:
        覆盖式上传要用它区分「旧的是正式文件(要删)」与「旧的是没跑完的临时文件
        (交给任务自己删)」。
    """
    return bool(name) and name.startswith(f"{TMP_PREFIX}/")


def error_payload(error: str) -> dict:
    """把 ``transcode_error`` 拆成轮询接口的 ``{code, message}``。

    参数说明:
        error: 行上的 ``transcode_error``:纯数字是业务码,其余是短文案。

    返回参数:
        ``{"code": 业务码字符串或 None, "message": 可直接展示的中文或 None}``;
        ``error`` 为空时两者都是 ``None``。

    使用示例:
        ``payload.update(transcode_queue.error_payload(row.transcode_error))``
        (见本模块 ``status_payload``)

    备注信息:
        业务码只允许纯数字(与 ``config/error_codes.py`` 同口径);没有已知业务码时
        ``code`` 为 ``None``,文案原样透出 —— 客户端按 ``status=failed`` 展示重试入口即可。
    """
    if not error:
        return {"code": None, "message": None}
    if error.isdigit():
        return {"code": error, "message": _CODE_MESSAGES.get(error, "语音转码失败,请重新录制")}
    return {"code": None, "message": error}


def status_payload(row, url: str | None) -> dict:
    """拼轮询接口的响应体(两个轮询接口同形状)。

    参数说明:
        row: ``im.ChatVoice`` 或 ``users.ProfileVoice`` 行 —— 两者字段同口径
            (``transcode_status`` / ``transcode_error`` / ``duration_ms`` / ``bytes``)。
        url: ``ready`` 时该行的对外地址;``pending`` / ``failed`` 传 ``None``。

    返回参数:
        ``{id, status, url, duration_ms, size, code, message}``;非 ``ready`` 时
        ``url`` / ``duration_ms`` / ``size`` 一律为 ``None``,失败原因落在
        ``code`` / ``message`` 上。

    使用示例:
        ``return Response(transcode_queue.status_payload(row, url))``
        (见 ``im/views.py`` 的 ``voice_status``)

    备注信息:
        三态的语义只在这里落地一次,聊天语音与资料语音因此不会各自解释一套。
        ``size`` 取库里的 ``bytes``(转码后字节数),不额外读磁盘。
    """
    ready = row.transcode_status == TranscodeStatus.READY
    payload = {
        "id": row.pk,
        "status": row.transcode_status,
        "url": url if ready else None,
        "duration_ms": row.duration_ms if ready else None,
        "size": row.bytes if ready else None,
    }
    payload.update(error_payload(row.transcode_error if not ready else ""))
    return payload

