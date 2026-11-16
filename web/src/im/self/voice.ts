/**
 * 聊天语音的浏览器侧处理:录音 + 上传到 Django + 等转码(M-3)。
 *
 * 浏览器录出来的容器因引擎而异(Chrome/Firefox 是 webm/ogg,Safari 可出 mp4),
 * 统一交给服务端 ffmpeg 转 m4a —— 这样 iOS 也能播放 Web 发来的语音。
 *
 * 上传有两条路(契约 `docs/api/im.md` §6.4 / §6.5):
 * - **抢到转码槽**(201):响应里就有签名 `url`,可以直接发 `send` 帧;
 * - **抢不到槽**(202):网络侧不再回 503,而是把原始文件排进 Celery,响应只有
 *   `{id, status:"pending", retry_after}`。这时**必须先轮询** `GET /im/voices/{id}`
 *   拿到 `ready` 的 `url` 才能发 —— 拿不到地址的 `send` 帧对方播不了。
 *
 * 上传本身带 `Idempotency-Key`(`docs/api/conventions.md` §幂等键):重试复用同一个 key,
 * 服务端不会因为「响应丢了重发一次」多建一条语音;`409` + `40901` 当可重试,不是终态失败。
 */

import {
  newIdempotencyKey,
  type UploadRetryOptions,
  withUploadRetries,
} from '@/api/idempotency'
import { http } from '@/api/http'
import { pollVoiceStatus } from '@/api/voice-status'
import type { VoiceQueued, VoiceStatus } from '@/api/types'

/** 已转码完成、可以直接塞进 WS `send` 帧的语音载荷(im.md §6.4 的 201 响应)。 */
export interface UploadedVoice {
  id: number
  url: string
  duration_ms: number
  size: number
}

/** 上传结果:转码已完成,或已被受理(202)等轮询。 */
export type ChatVoiceUpload =
  | { queued: false; voice: UploadedVoice }
  | { queued: true; id: number; retryAfterSeconds: number }

/** 转码失败的兜底话术(`failed` 且服务端没给 `message` 时用它)。 */
export const CHAT_VOICE_FAILED_TEXT = '语音转码失败，请重录'
/**
 * 重发时本地录音已经不在(Blob 只活在内存里,刷新/换页就没了)时的提示。
 *
 * 语音不像图片那样能凭服务端消息重发:消息里只有签名 URL,而 `url` 24 小时后过期,
 * 所以重试必须是**重新上传本地 Blob**;没有 Blob 就只能请用户重录。
 */
export const CHAT_VOICE_LOCAL_GONE_TEXT = '本地录音已失效，请重新录制'

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

/**
 * 构造一次 multipart 请求体(`file` + `duration_ms`)。
 *
 * **每次尝试都要新建**:`FormData` 发出去就被浏览器标脏,重试复用同一个对象会丢文件/丢字段。
 */
function chatVoiceForm(blob: Blob, durationMs: number): FormData {
  const form = new FormData()
  form.append('file', blob, 'voice.m4a')
  form.append('duration_ms', String(Math.round(durationMs)))
  return form
}

/**
 * 上传一段录音。抢到转码槽时直接拿到签名 URL;抢不到时拿到受理体,交给 `awaitChatVoice`。
 *
 * **幂等键**:一次「用户发出去的语音」生成一个 key(本函数进来时生成),上传的所有自动重试
 * 复用它 —— 网络抖动 / `429` / `5xx` / `409` + `40901`(同 key 的上一次还在处理中)都退避后
 * **同 key** 再打一次,不会因为重试多建一条语音(`docs/api/conventions.md` §幂等键)。
 * `400`(格式 / 时长不符)与 `413`(配额满)不重试,原样上抛。
 *
 * Args:
 *   blob: 浏览器录出来的音频(容器随引擎不同,服务端统一转 m4a)。
 *   durationMs: 客户端测得的时长;服务端会用 ffprobe 实测并比对(相差 >2 秒回 400)。
 *   options: 重试参数(单测注入点),缺省 3 次 + 500ms 起翻倍退避。
 *
 * Returns:
 *   201 → `{queued:false, voice}`;202 → `{queued:true, id, retryAfterSeconds}`。
 *
 * Raises:
 *   ApiError: 400 / 413 / 401 / 403 / 404 等不可重试错误,或重试次数用尽仍失败。
 */
export async function uploadChatVoice(
  blob: Blob,
  durationMs: number,
  options: UploadRetryOptions = {},
): Promise<ChatVoiceUpload> {
  const idempotencyKey = newIdempotencyKey()
  return withUploadRetries(async () => {
    const response = await http.post('/im/voices', chatVoiceForm(blob, durationMs), {
      headers: { 'Idempotency-Key': idempotencyKey },
      // 401 刷新后重放同一次上传:请求体重建,key 不变
      rebuildBody: () => chatVoiceForm(blob, durationMs),
    })
    if (response.status === 202) {
      const queued = response.data as VoiceQueued
      return { queued: true as const, id: queued.id, retryAfterSeconds: queued.retry_after }
    }
    return { queued: false as const, voice: response.data as UploadedVoice }
  }, options)
}

/** 查一条聊天语音的转码状态(`GET /im/voices/{voice_id}`,im.md §6.5)。 */
export async function fetchChatVoiceStatus(voiceId: number): Promise<VoiceStatus> {
  const { data } = await http.get(`/im/voices/${voiceId}`)
  return data as VoiceStatus
}

/**
 * 轮询到转码落定,返回可发送的语音载荷。
 *
 * Args:
 *   voiceId: 6.4 返回的聊天语音主键。
 *   retryAfterSeconds: 202 响应里的 `retry_after`(秒)。
 *
 * Returns:
 *   `status=ready` 时的 `{id, url, duration_ms, size}`。
 *
 * Raises:
 *   Error: 转码失败(`failed`,文案取服务端 `message`,缺省 `CHAT_VOICE_FAILED_TEXT`)、
 *   或轮询超时(`VOICE_POLL_TIMEOUT_TEXT`)。两者都可以直接展示给用户。
 */
export async function awaitChatVoice(
  voiceId: number,
  retryAfterSeconds: number,
): Promise<UploadedVoice> {
  const status = await pollVoiceStatus(() => fetchChatVoiceStatus(voiceId), { retryAfterSeconds })
  if (status?.status === 'ready' && status.url) {
    return {
      id: status.id,
      url: status.url,
      duration_ms: status.duration_ms ?? 0,
      size: status.size ?? 0,
    }
  }
  // failed:服务端给了可直接展示的中文就原样用(如「存储空间已满」),否则兜底
  throw new Error(status?.message || CHAT_VOICE_FAILED_TEXT)
}
