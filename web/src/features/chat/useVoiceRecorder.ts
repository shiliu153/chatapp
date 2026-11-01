/**
 * 聊天语音录制状态机(契约见 specs/2026-11-01-voice-recording-interaction-design.md §4)。
 *
 * 状态:idle → requesting → recording → sending → idle
 * 关键约束:不足 1 秒不发、60 秒自动发、离开页面只取消不发送。
 */

import { ref } from 'vue'
import type { Ref } from 'vue'
import { pickMimeType } from '@/im/self/voice'

export type VoicePhase = 'idle' | 'requesting' | 'recording' | 'sending'

/** 与 App 端 voice_record_controller.dart 的常量逐字对应,改一边必须改另一边。 */
export const VOICE_TEXT = {
  permissionDenied: '需要麦克风权限才能发语音',
  noDevice: '未检测到麦克风',
  unsupported: '当前浏览器不支持录音（需 HTTPS）',
  startFailed: '录音启动失败，请重试',
  tooShort: '说话时间太短',
  sendFailed: '语音发送失败，点击重试',
} as const

const MIN_DURATION_MS = 1000
const MAX_DURATION_MS = 60_000

export interface VoiceRecorderOptions {
  /** 能力位 + 浏览器支持,任一不满足都进不了录音 */
  enabled: () => boolean
  /** 发送一段录音;失败时调用方必须已经落了可重试气泡,这里静默 */
  onSend: (blob: Blob, durationMs: number) => Promise<void>
  /** 需要提示用户的话术(权限/设备/太短/启动失败) */
  onNotice: (text: string) => void
}

export interface VoiceRecorderHandle {
  phase: Ref<VoicePhase>
  seconds: Ref<number>
  start: () => Promise<void>
  stopAndSend: () => Promise<void>
  cancel: () => Promise<void>
  dispose: () => void
}

export function useVoiceRecorder(options: VoiceRecorderOptions): VoiceRecorderHandle {
  const phase = ref<VoicePhase>('idle')
  const seconds = ref(0)

  let recorder: MediaRecorder | null = null
  let stream: MediaStream | null = null
  let chunks: Blob[] = []
  let startedAt = 0
  let ticker: ReturnType<typeof setInterval> | undefined
  let timeout: ReturnType<typeof setTimeout> | undefined

  function clearTimers(): void {
    if (ticker) clearInterval(ticker)
    ticker = undefined
    if (timeout) clearTimeout(timeout)
    timeout = undefined
  }

  function stopTracks(): void {
    stream?.getTracks().forEach((track) => track.stop())
    stream = null
  }

  function toIdle(): void {
    clearTimers()
    stopTracks()
    recorder = null
    chunks = []
    seconds.value = 0
    phase.value = 'idle'
  }

  /** getUserMedia 的异常名 → 文案;浏览器各家名字不一致,多认几个。 */
  function noticeFor(error: unknown): string {
    const name = (error as { name?: string } | null)?.name ?? ''
    if (name === 'NotAllowedError' || name === 'SecurityError') return VOICE_TEXT.permissionDenied
    if (name === 'NotFoundError' || name === 'DevicesNotFoundError') return VOICE_TEXT.noDevice
    return VOICE_TEXT.startFailed
  }

  async function start(): Promise<void> {
    if (phase.value !== 'idle') return
    if (!options.enabled()) {
      options.onNotice(VOICE_TEXT.unsupported)
      return
    }
    const mime = pickMimeType()
    if (!mime) {
      options.onNotice(VOICE_TEXT.unsupported)
      return
    }
    phase.value = 'requesting'
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    } catch (error) {
      toIdle()
      options.onNotice(noticeFor(error))
      return
    }
    recorder = new MediaRecorder(stream, { mimeType: mime })
    chunks = []
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) chunks.push(event.data)
    }
    recorder.start()
    startedAt = Date.now()
    seconds.value = 0
    phase.value = 'recording'
    ticker = setInterval(() => {
      seconds.value = Math.min(60, Math.ceil((Date.now() - startedAt) / 1000))
    }, 200)
    timeout = setTimeout(() => void stopAndSend(), MAX_DURATION_MS)
  }

  async function stopAndSend(): Promise<void> {
    if (phase.value !== 'recording') return
    const duration = Date.now() - startedAt
    clearTimers()
    const current = recorder
    recorder = null
    phase.value = 'sending'

    let blob: Blob | null = null
    if (current && current.state !== 'inactive') {
      blob = await new Promise<Blob | null>((resolve) => {
        current.onstop = () => {
          // Blob.type 会带 `;codecs=opus`;去掉参数,服务端白名单按主类型匹配
          const type = current.mimeType.split(';')[0] || 'audio/webm'
          resolve(new Blob(chunks, { type }))
        }
        current.stop()
      })
    }
    stopTracks()
    chunks = []

    if (duration < MIN_DURATION_MS) {
      seconds.value = 0
      phase.value = 'idle'
      options.onNotice(VOICE_TEXT.tooShort)
      return
    }
    if (!blob) {
      seconds.value = 0
      phase.value = 'idle'
      options.onNotice(VOICE_TEXT.startFailed)
      return
    }
    try {
      await options.onSend(blob, duration)
    } catch {
      // 失败态由 onSend 的调用方落气泡(store.sendVoice 内部已标 isFailed)
    } finally {
      seconds.value = 0
      phase.value = 'idle'
    }
  }

  async function cancel(): Promise<void> {
    if (phase.value === 'idle') return
    const current = recorder
    recorder = null
    if (current && current.state !== 'inactive') {
      current.onstop = null
      current.stop()
    }
    toIdle()
  }

  /** 组件卸载时调用:一律取消,绝不把没录完的话发出去。 */
  function dispose(): void {
    void cancel()
  }

  return { phase, seconds, start, stopAndSend, cancel, dispose }
}
