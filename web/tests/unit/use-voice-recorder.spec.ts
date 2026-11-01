import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { VOICE_TEXT, useVoiceRecorder } from '@/features/chat/useVoiceRecorder'

/** 假 MediaRecorder:start 后 state 变 recording,stop 触发 onstop。 */
class FakeRecorder {
  static supported = ['audio/webm;codecs=opus']
  static isTypeSupported = (type: string) => FakeRecorder.supported.includes(type)

  state = 'inactive'
  mimeType = 'audio/webm;codecs=opus'
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null

  start(): void {
    this.state = 'recording'
  }

  stop(): void {
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob(['chunk'], { type: this.mimeType }) })
    this.onstop?.()
  }
}

function installRecorder(): void {
  vi.stubGlobal('MediaRecorder', FakeRecorder)
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] })),
    },
  })
}

function setup(overrides: Partial<{ enabled: () => boolean }> = {}) {
  const onSend = vi.fn(async () => {})
  const onNotice = vi.fn()
  const voice = useVoiceRecorder({
    enabled: overrides.enabled ?? (() => true),
    onSend,
    onNotice,
  })
  return { voice, onSend, onNotice }
}

describe('useVoiceRecorder', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    installRecorder()
  })
  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('start 后进入 recording 并开始计时', async () => {
    const { voice } = setup()
    await voice.start()
    expect(voice.phase.value).toBe('recording')
    vi.advanceTimersByTime(2000)
    expect(voice.seconds.value).toBe(2)
  })

  it('不足 1 秒不发送，提示太短', async () => {
    const { voice, onSend, onNotice } = setup()
    await voice.start()
    vi.advanceTimersByTime(500)
    await voice.stopAndSend()
    expect(onSend).not.toHaveBeenCalled()
    expect(onNotice).toHaveBeenCalledWith(VOICE_TEXT.tooShort)
    expect(voice.phase.value).toBe('idle')
  })

  it('满 1 秒正常发送并回到 idle', async () => {
    const { voice, onSend } = setup()
    await voice.start()
    vi.advanceTimersByTime(2500)
    await voice.stopAndSend()
    expect(onSend).toHaveBeenCalledTimes(1)
    expect(voice.phase.value).toBe('idle')
  })

  it('60 秒自动发送', async () => {
    const { voice, onSend } = setup()
    await voice.start()
    await vi.advanceTimersByTimeAsync(60_000)
    expect(onSend).toHaveBeenCalledTimes(1)
  })

  it('取消不发任何消息', async () => {
    const { voice, onSend } = setup()
    await voice.start()
    vi.advanceTimersByTime(3000)
    await voice.cancel()
    expect(onSend).not.toHaveBeenCalled()
    expect(voice.phase.value).toBe('idle')
  })

  it('dispose 等价取消，绝不发送', async () => {
    const { voice, onSend } = setup()
    await voice.start()
    vi.advanceTimersByTime(3000)
    voice.dispose()
    expect(onSend).not.toHaveBeenCalled()
    expect(voice.phase.value).toBe('idle')
  })

  it('权限被拒映射成对应文案', async () => {
    const denied = Object.assign(new Error('denied'), { name: 'NotAllowedError' })
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn(async () => Promise.reject(denied)) },
    })
    const { voice, onNotice } = setup()
    await voice.start()
    expect(onNotice).toHaveBeenCalledWith(VOICE_TEXT.permissionDenied)
    expect(voice.phase.value).toBe('idle')
  })

  it('enabled 为假时直接提示不支持', async () => {
    const { voice, onNotice } = setup({ enabled: () => false })
    await voice.start()
    expect(onNotice).toHaveBeenCalledWith(VOICE_TEXT.unsupported)
    expect(voice.phase.value).toBe('idle')
  })
})
