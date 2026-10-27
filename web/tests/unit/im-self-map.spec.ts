import { describe, expect, it } from 'vitest'
import { messageFromJson } from '@/im/self/map'
import { ChatMessageKind } from '@/im/types'

describe('自建 IM 语音消息映射', () => {
  it('解析 kind=voice 的载荷', () => {
    const message = messageFromJson(
      {
        msg_id: '9',
        seq: 4,
        from: 'u9',
        to: 'u2',
        kind: 'voice',
        ts: 1_760_000_000_000,
        revoked: false,
        voice: {
          url: 'http://cdn/media/chat/voices/a.m4a?e=1&s=2',
          duration_ms: 12500,
          size: 48000,
        },
      },
      'u2',
    )
    expect(message.kind).toBe(ChatMessageKind.voice)
    expect(message.voiceUrl).toBe('http://cdn/media/chat/voices/a.m4a?e=1&s=2')
    expect(message.voiceDurationMs).toBe(12500)
  })

  it('文本消息没有语音字段', () => {
    const message = messageFromJson(
      { msg_id: '1', from: 'u9', to: 'u2', kind: 'text', text: 'hi', ts: 1 },
      'u2',
    )
    expect(message.kind).toBe(ChatMessageKind.text)
    expect(message.voiceUrl).toBeNull()
    expect(message.voiceDurationMs).toBe(0)
  })
})
