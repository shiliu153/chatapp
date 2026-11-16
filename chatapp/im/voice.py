"""聊天语音的校验与统一转码。

App 录 m4a(AAC),Web 的 ``MediaRecorder`` 输出因浏览器而异(webm/ogg/mp4)。
为了让 iOS 也能播放 Web 发来的语音,这里统一转成 **m4a/AAC 单声道 16kHz 32kbps**,
并用 ``ffprobe`` 校验真实时长(不信任客户端声明)。

设计要点:
    1. 只在本机起子进程,不访问网络 —— 符合「响应路径禁止第三方网络调用」纪律;
    2. 命令一律用参数数组,不经 shell;超时 15 秒,防止畸形文件拖死 worker;
    3. ffmpeg/ffprobe 缺失是部署问题,调用方回 503,而不是静默降级;
    4. **把上传文件当不可信输入**(M5):协议白名单 ``file,pipe`` 挡住 HLS/concat
       之类的 playlist 去访问网络或读任意本地文件;``-nostdin`` + ``stdin=DEVNULL``
       防交互;POSIX 下再用 ``setrlimit`` 限 CPU/内存/输出文件大小;子进程环境只留
       ``PATH``/``TMPDIR``,避免 ``FFREPORT`` 之类的环境变量被利用;
    5. **同步与异步两条调用路共用本模块**(第五轮审计 M-3):抢到槽时请求线程直接转码,
       抢不到时先暂存再交给 Celery worker;worker 手上只有临时文件,靠
       ``content_type_for`` 从扩展名还原 MIME,``normalize`` 的校验一条都不少。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.conf import settings

ALLOWED_CONTENT_TYPES = {
    "audio/mp4": ".m4a",
    "audio/m4a": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
}

# 反查表:异步路径(临时区)只留下了扩展名,worker 要据此还原 MIME 再交给 ``normalize``。
# 同一个扩展名可能对应多个 MIME(``audio/mp4`` / ``audio/m4a`` / ``audio/x-m4a``),
# 取第一个即可 —— ``normalize`` 只用它查回同一个扩展名。
CONTENT_TYPE_BY_SUFFIX = {
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
}

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"

# 只允许本地文件与管道:输入是刚写进临时目录的字节,输出是本机文件。
# 没有 http/tcp/rtmp 等协议,畸形 playlist(如 HLS/concat)就拉不到外部资源。
PROTOCOL_WHITELIST = "file,pipe"
PROCESS_TIMEOUT_SECONDS = 15
_CPU_LIMIT_SECONDS = 15
_ADDRESS_SPACE_LIMIT = 512 * 1024 * 1024
_FILE_SIZE_LIMIT = 16 * 1024 * 1024


class VoiceError(Exception):
    """语音不合法或无法处理;消息直接回给客户端。"""


class VoiceUnavailable(Exception):
    """服务器缺少 ffmpeg/ffprobe;调用方回 503。"""


def _child_env() -> dict[str, str]:
    """构造子进程的最小环境变量。

    参数说明:
        无。

    返回参数:
        只保留 ``PATH`` 与临时目录相关变量,避免继承 ``FFREPORT`` 等可被利用的配置。

    使用示例:
        ``env = _child_env()``(见本模块 ``_run``)

    备注信息:
        ``PATH`` 取不到时回落到 ``/usr/local/bin:/usr/bin:/bin``;``LC_ALL`` / ``LANG`` 固定为 ``C``。
    """
    env = {"PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
           "LC_ALL": "C", "LANG": "C"}
    for key in ("TMPDIR", "TEMP", "TMP"):
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def _apply_limits() -> None:
    """在子进程里设置资源上限(POSIX)。

    ``RLIMIT_CPU`` 兜住死循环,``RLIMIT_AS`` 兜住解码炸弹,``RLIMIT_FSIZE``
    兜住写出超大文件;Windows 没有 ``resource`` 模块,由超时兜底。
    """
    if os.name != "posix":
        return
    import resource  # 仅 POSIX 可用,放函数内避免 Windows 导入失败

    resource.setrlimit(resource.RLIMIT_CPU, (_CPU_LIMIT_SECONDS, _CPU_LIMIT_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (_ADDRESS_SPACE_LIMIT, _ADDRESS_SPACE_LIMIT))
    resource.setrlimit(resource.RLIMIT_FSIZE, (_FILE_SIZE_LIMIT, _FILE_SIZE_LIMIT))


def _run(args: list[str]) -> subprocess.CompletedProcess:
    """以最小权限执行 ffmpeg/ffprobe。

    参数说明:
        args: 完整参数数组(含可执行文件名),不经 shell。

    返回参数:
        子进程结果;退出码由调用方判定。

    使用示例:
        ``result = _run([FFPROBE, "-v", "error", "-protocol_whitelist", PROTOCOL_WHITELIST])``(见本模块 ``_probe_ms``)

    备注信息:
        ``stdin`` 接 ``DEVNULL``,超时 ``PROCESS_TIMEOUT_SECONDS`` 秒,POSIX 下用
        ``preexec_fn`` 挂 ``_apply_limits``;环境变量只留 ``_child_env()`` 给出的几项。
        处理超过 ``PROCESS_TIMEOUT_SECONDS`` 时抛 ``subprocess.TimeoutExpired``,
        由调用方转成 ``VoiceError``。
    """
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=PROCESS_TIMEOUT_SECONDS,
        check=False,
        stdin=subprocess.DEVNULL,
        env=_child_env(),
        preexec_fn=_apply_limits if os.name == "posix" else None,
    )


def base_content_type(value: str) -> str:
    """取 MIME 的主类型(去掉 ``;codecs=...`` 参数并小写)。

    Web 的 ``MediaRecorder`` 给出的是 ``audio/webm;codecs=opus``,浏览器
    ``Blob.type`` 会原样带上参数;精确匹配会把正常录音挡在门外。

    参数说明:
        value: 上传声明的 MIME 原值。

    返回参数:
        形如 ``audio/webm`` 的主类型;空值返回空串。

    使用示例:
        ``base_content_type(value.content_type)``(见 ``im/serializers.py`` 的 ``ChatVoiceUploadSerializer.validate_file``)

    备注信息:
        纯字符串处理,不判定 MIME 是否在白名单内 —— 白名单比对由调用方负责。
    """
    return (value or "").split(";", 1)[0].strip().lower()


def content_type_for(name: str) -> str:
    """从暂存文件的路径反推 MIME(异步转码路径用)。

    参数说明:
        name: 存储相对路径,形如 ``tmp/voice/<uuid>.webm``。

    返回参数:
        与扩展名对应的 MIME,如 ``audio/webm``。

    使用示例:
        ``voice.normalize(raw, voice.content_type_for(row.file.name), row.duration_ms)``
        (见 ``im/tasks.py`` 的 ``transcode_chat_voice``)

    备注信息:
        只在 worker 侧用:上传时做过 MIME 白名单校验,暂存文件名又由
        ``transcode_queue.staged_name`` 按同一张表生成,所以扩展名可信。
        取不到扩展名或扩展名不在表里时抛 ``VoiceError``(与同步路径同一套文案)。
    """
    suffix = Path(name or "").suffix.lower()
    content_type = CONTENT_TYPE_BY_SUFFIX.get(suffix)
    if content_type is None:
        raise VoiceError("只支持 M4A/AAC/WebM/OGG 音频")
    return content_type


def ffmpeg_available() -> bool:
    """检查转码依赖是否齐全。

    参数说明:
        无。

    返回参数:
        两者都在 PATH 中时为 ``True``。

    使用示例:
        ``if not ffmpeg_available():``(见本模块 ``normalize`` / ``normalize_profile``)

    备注信息:
        只查 ``PATH``,不实际执行 ffmpeg/ffprobe;缺失属部署问题,调用方回 503。
    """
    return shutil.which(FFMPEG) is not None and shutil.which(FFPROBE) is not None


def _probe_ms(path: Path) -> int:
    """用 ffprobe 读真实时长。

    参数说明:
        path: 本地音频文件。

    返回参数:
        时长(毫秒)。

    使用示例:
        ``duration = voice._probe_ms(Path("a.m4a"))``(见 ``im/tests.py`` 的 ``VoiceCommandHardeningTests.test_probe_uses_protocol_whitelist``)

    备注信息:
        ``ffprobe`` 读不出时长(不是音频 / 文件损坏)或超时时抛 ``VoiceError``。
        返回值不小于 0,单位是毫秒。
    """
    try:
        result = _run(
            [FFPROBE, "-v", "error", "-protocol_whitelist", PROTOCOL_WHITELIST,
             "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)])
    except subprocess.TimeoutExpired:
        raise VoiceError("音频无法解码,请重新录制") from None
    try:
        return max(0, int(round(float(result.stdout.strip()) * 1000)))
    except (TypeError, ValueError):
        raise VoiceError("音频无法解码,请重新录制") from None


def _transcode(src: Path, dst: Path) -> None:
    """把任意输入转成 m4a/AAC 单声道。

    参数说明:
        src: 输入文件。
        dst: 输出文件(扩展名 ``.m4a``)。

    返回参数:
        无返回值。

    使用示例:
        ``voice._transcode(src, Path(workdir) / "out.m4a")``(见 ``im/tests.py`` 的 ``VoiceCommandHardeningTests.test_transcode_args_are_hardened``)

    备注信息:
        统一转 AAC 单声道,采样率与码率取 ``CHAT_VOICE_SAMPLE_RATE`` / ``CHAT_VOICE_BITRATE``,
        并去掉元数据、字幕与数据流。``ffmpeg`` 非零退出或超时抛 ``VoiceError``。
    """
    try:
        result = _run(
            [FFMPEG, "-nostdin", "-y", "-hide_banner", "-loglevel", "error",
             "-protocol_whitelist", PROTOCOL_WHITELIST,
             "-i", str(src), "-map_metadata", "-1", "-sn", "-dn", "-threads", "1",
             "-vn", "-ac", "1", "-ar", str(settings.CHAT_VOICE_SAMPLE_RATE),
             "-c:a", "aac", "-b:a", settings.CHAT_VOICE_BITRATE, "-f", "mp4", str(dst)])
    except subprocess.TimeoutExpired:
        raise VoiceError("音频无法解码,请重新录制") from None
    if result.returncode != 0:
        raise VoiceError("音频无法解码,请重新录制")


def normalize(raw: bytes, content_type: str, declared_ms: int) -> tuple[bytes, int]:
    """校验并转码一段上传的语音。

    参数说明:
        raw: 原始文件字节。
        content_type: 上传声明的 MIME。
        declared_ms: 客户端声明的时长(毫秒)。

    返回参数:
        ``(m4a 字节, 实测毫秒)``。

    使用示例:
        ``data, duration_ms = voice.normalize(upload.read(), upload.content_type, serializer.validated_data["duration_ms"])``
        (见 ``im/views.py`` 的 ``upload_voice``)

    备注信息:
        时长以 ``ffprobe`` 实测值为准,不信任客户端声明;声明值与实测值相差超过
        ``CHAT_VOICE_DURATION_TOLERANCE_MS`` 时按不合法处理。
        服务器缺 ffmpeg/ffprobe 抛 ``VoiceUnavailable``;格式、时长、大小或解码不合法抛 ``VoiceError``。
    """
    suffix = ALLOWED_CONTENT_TYPES.get(base_content_type(content_type))
    if suffix is None:
        raise VoiceError("只支持 M4A/AAC/WebM/OGG 音频")
    if not ffmpeg_available():
        raise VoiceUnavailable()
    with tempfile.TemporaryDirectory() as workdir:
        src = Path(workdir) / f"in{suffix}"
        src.write_bytes(raw)
        duration = _probe_ms(src)
        if not (settings.CHAT_VOICE_MIN_MS <= duration <= settings.CHAT_VOICE_MAX_MS):
            raise VoiceError("语音时长需在 1–60 秒之间")
        if abs(duration - declared_ms) > settings.CHAT_VOICE_DURATION_TOLERANCE_MS:
            raise VoiceError("语音时长不合法")
        dst = Path(workdir) / "out.m4a"
        _transcode(src, dst)
        data = dst.read_bytes()
    if not data:
        raise VoiceError("音频无法解码,请重新录制")
    if len(data) > settings.CHAT_VOICE_MAX_OUT_BYTES:
        raise VoiceError("语音文件过大")
    return data, duration


def normalize_profile(raw: bytes, content_type: str) -> tuple[bytes, int]:
    """校验并转码一段资料语音自我介绍(≤30 秒)。

    参数说明:
        raw: 上传文件的原始字节。
        content_type: 上传声明的 MIME(可带 ``;codecs=...`` 参数)。

    返回参数:
        ``(m4a 字节, 实测毫秒)``。

    使用示例:
        ``data, duration_ms = voice.normalize_profile(upload.read(), upload.content_type)``
        (见 ``users/views.py`` 的 ``my_voice``)

    备注信息:
        转码完全复用本模块的 ``normalize``(ffprobe 校验 → ffmpeg 转 m4a/AAC),这里不重写
        任何 ffmpeg 调用;先用 ``ffprobe`` 探真实时长再作为 ``declared_ms`` 传进去,等价于
        「不信任客户端声明」。
        服务器缺 ffmpeg/ffprobe 抛 ``VoiceUnavailable``(调用方回 503 + ``50302``);
        格式/大小/解码不合法或时长超过 ``settings.PROFILE_VOICE_MAX_MS`` 抛 ``VoiceError``。
        同步与异步两条路都调本函数:资料语音不接收客户端声明时长,异步路径也不需要额外
        参数,任务参数因此仍然只有行 id。
    """
    suffix = ALLOWED_CONTENT_TYPES.get(base_content_type(content_type))
    if suffix is None:
        raise VoiceError("只支持 M4A/AAC/WebM/OGG 音频")
    if not ffmpeg_available():
        raise VoiceUnavailable()
    with tempfile.TemporaryDirectory() as workdir:
        probe_path = Path(workdir) / f"probe{suffix}"
        probe_path.write_bytes(raw)
        declared_ms = _probe_ms(probe_path)
    data, duration_ms = normalize(raw, content_type, declared_ms)
    if duration_ms > settings.PROFILE_VOICE_MAX_MS:
        raise VoiceError(
            f"语音自我介绍不能超过 {settings.PROFILE_VOICE_MAX_MS // 1000} 秒")
    return data, duration_ms
