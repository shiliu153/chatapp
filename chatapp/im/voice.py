"""聊天语音的校验与统一转码。

App 录 m4a(AAC),Web 的 ``MediaRecorder`` 输出因浏览器而异(webm/ogg/mp4)。
为了让 iOS 也能播放 Web 发来的语音,这里统一转成 **m4a/AAC 单声道 16kHz 32kbps**,
并用 ``ffprobe`` 校验真实时长(不信任客户端声明)。

设计要点:
    1. 只在本机起子进程,不访问网络 —— 符合「响应路径禁止第三方网络调用」纪律;
    2. 命令一律用参数数组,不经 shell;超时 15 秒,防止畸形文件拖死 worker;
    3. ffmpeg/ffprobe 缺失是部署问题,调用方回 503,而不是静默降级。
"""

from __future__ import annotations

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

FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"


class VoiceError(Exception):
    """语音不合法或无法处理;消息直接回给客户端。"""


class VoiceUnavailable(Exception):
    """服务器缺少 ffmpeg/ffprobe;调用方回 503。"""


def base_content_type(value: str) -> str:
    """取 MIME 的主类型(去掉 ``;codecs=...`` 参数并小写)。

    Web 的 ``MediaRecorder`` 给出的是 ``audio/webm;codecs=opus``,浏览器
    ``Blob.type`` 会原样带上参数;精确匹配会把正常录音挡在门外。

    Args:
        value: 上传声明的 MIME 原值。

    Returns:
        形如 ``audio/webm`` 的主类型;空值返回空串。
    """
    return (value or "").split(";", 1)[0].strip().lower()


def ffmpeg_available() -> bool:
    """检查转码依赖是否齐全。

    Returns:
        两者都在 PATH 中时为 ``True``。
    """
    return shutil.which(FFMPEG) is not None and shutil.which(FFPROBE) is not None


def _probe_ms(path: Path) -> int:
    """用 ffprobe 读真实时长。

    Args:
        path: 本地音频文件。

    Returns:
        时长(毫秒)。

    Raises:
        VoiceError: ffprobe 读不出时长(不是音频 / 文件损坏)。
    """
    result = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "format=duration",
         "-of", "default=nw=1:nk=1", str(path)],
        capture_output=True, text=True, timeout=15, check=False)
    try:
        return max(0, int(round(float(result.stdout.strip()) * 1000)))
    except (TypeError, ValueError):
        raise VoiceError("音频无法解码,请重新录制") from None


def _transcode(src: Path, dst: Path) -> None:
    """把任意输入转成 m4a/AAC 单声道。

    Args:
        src: 输入文件。
        dst: 输出文件(扩展名 ``.m4a``)。

    Raises:
        VoiceError: ffmpeg 非零退出或超时。
    """
    try:
        subprocess.run(
            [FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-i", str(src),
             "-vn", "-ac", "1", "-ar", str(settings.CHAT_VOICE_SAMPLE_RATE),
             "-c:a", "aac", "-b:a", settings.CHAT_VOICE_BITRATE, "-f", "mp4", str(dst)],
            capture_output=True, timeout=15, check=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        raise VoiceError("音频无法解码,请重新录制") from None


def normalize(raw: bytes, content_type: str, declared_ms: int) -> tuple[bytes, int]:
    """校验并转码一段上传的语音。

    Args:
        raw: 原始文件字节。
        content_type: 上传声明的 MIME。
        declared_ms: 客户端声明的时长(毫秒)。

    Returns:
        ``(m4a 字节, 实测毫秒)``。

    Raises:
        VoiceUnavailable: 服务器缺 ffmpeg/ffprobe。
        VoiceError: 格式、时长、大小或解码不合法。
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
