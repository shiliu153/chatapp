/**
 * 聊天语音的浏览器侧处理:录音 + 上传到 Django。
 *
 * 浏览器录出来的容器因引擎而异(Chrome/Firefox 是 webm/ogg,Safari 可出 mp4),
 * 统一交给服务端 ffmpeg 转 m4a —— 这样 iOS 也能播放 Web 发来的语音。
 */

import { http } from '@/api/http'

export interface UploadedVoice {
  id: number
  url: string
  duration_ms: number
  size: number
}

const MIME_CANDIDATES = ['audio/webm;codecs=opus', 'audio/ogg;codecs=opus', 'audio/mp4']

/** 选一个当前浏览器能录的 MIME;都不支持返回 null。 */
export function pickMimeType(
  isSupported: (type: string) => boolean = (type) => MediaRecorder.isTypeSupported(type),
): string | null {
  return MIME_CANDIDATES.find((type) => isSupported(type)) ?? null
}

/** 当前环境能否录音(需要安全上下文:HTTPS 或 localhost,以及麦克风 API)。 */
export function canRecordVoice(): boolean {
  return (
    typeof navigator !== 'undefined' &&
    typeof navigator.mediaDevices?.getUserMedia === 'function' &&
    typeof MediaRecorder !== 'undefined' &&
    pickMimeType() !== null
  )
}

/** 上传一段录音,返回后端给的签名 URL 与实测时长。 */
export async function uploadChatVoice(blob: Blob, durationMs: number): Promise<UploadedVoice> {
  const form = new FormData()
  form.append('file', blob, 'voice.m4a')
  form.append('duration_ms', String(Math.round(durationMs)))
  const response = await http.post('/im/voices', form)
  return response.data as UploadedVoice
}
