import { describe, expect, it, vi } from 'vitest'
import { canRecordVoice, pickMimeType } from '@/im/self/voice'

describe('语音 MIME 选择', () => {
  it('优先 webm/opus', () => {
    const supported = vi.fn((type: string) => type.startsWith('audio/webm'))
    expect(pickMimeType(supported)).toBe('audio/webm;codecs=opus')
  })

  it('Safari 只支持 mp4 时回退到 mp4', () => {
    const supported = vi.fn((type: string) => type === 'audio/mp4')
    expect(pickMimeType(supported)).toBe('audio/mp4')
  })

  it('都不支持时返回 null', () => {
    expect(pickMimeType(() => false)).toBeNull()
  })
})

describe('录音环境检测', () => {
  it('jsdom 里没有 mediaDevices,视为不能录音', () => {
    expect(canRecordVoice()).toBe(false)
  })
})
