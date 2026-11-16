/**
 * 气泡「发送中…」与「转码中…」两个 loading 文案(M-3)。
 *
 * 语音上传被 202 受理后要等服务端转码,这段等待与「正在发送」不是一回事:同一个
 * loading 位,文案必须说清用户等的是什么 —— 否则看起来就像卡住了。
 */
import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MessageBubble from '@/features/chat/MessageBubble.vue'
import type { ChatMessage } from '@/im/types'

const message = (overrides: Partial<ChatMessage> = {}): ChatMessage => ({
  msgId: 'local-1',
  peerId: 'u8',
  isSelf: true,
  seq: 0,
  timestamp: 1,
  kind: 'voice' as never,
  text: '',
  senderName: '',
  senderAvatar: null,
  isPending: true,
  isFailed: false,
  imageUrl: null,
  imageLargeUrl: null,
  voiceUrl: null,
  voiceDurationMs: 3000,
  isRevoked: false,
  ...overrides,
})

describe('MessageBubble:发送中 / 转码中', () => {
  it('普通发送中仍是「发送中…」', () => {
    const w = mount(MessageBubble, { props: { message: message() } })
    expect(w.text()).toContain('发送中')
    expect(w.text()).not.toContain('转码中')
  })

  it('语音 202 受理后显示「转码中…」(不是「发送中…」)', () => {
    const w = mount(MessageBubble, { props: { message: message({ voiceTranscoding: true }) } })
    expect(w.text()).toContain('转码中')
    expect(w.text()).not.toContain('发送中')
  })

  it('转码失败转成失败态后露出「重发」按钮', () => {
    const w = mount(MessageBubble, {
      props: { message: message({ isPending: false, isFailed: true }) },
    })
    expect(w.text()).toContain('重发')
    expect(w.text()).not.toContain('转码中')
  })
})
