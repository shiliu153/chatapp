import { describe, expect, it } from 'vitest'
import { canRecall, RECALL_WINDOW_MS } from '@/features/chat/recall'
import { ChatMessageKind } from '@/im/types'
import type { ChatMessage } from '@/im/types'

function msg(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    msgId: 'm1',
    peerId: 'u9',
    isSelf: true,
    seq: 0,
    timestamp: 1_700_000_000_000,
    kind: ChatMessageKind.text,
    text: '你好',
    senderName: '',
    senderAvatar: null,
    isPending: false,
    isFailed: false,
    isRevoked: false,
    imageUrl: null,
    imageLargeUrl: null,
    ...overrides,
  }
}

describe('canRecall', () => {
  const now = 1_700_000_000_000

  it('自己 2 分钟内可撤回', () => {
    expect(canRecall(msg({ timestamp: now - 30_000 }), now)).toBe(true)
  })

  it('超过窗口不可撤回', () => {
    expect(canRecall(msg({ timestamp: now - RECALL_WINDOW_MS - 1 }), now)).toBe(false)
  })

  it('对方消息不可撤回', () => {
    expect(canRecall(msg({ isSelf: false }), now)).toBe(false)
  })

  it('发送中/失败/已撤回不可撤回', () => {
    expect(canRecall(msg({ isPending: true }), now)).toBe(false)
    expect(canRecall(msg({ isFailed: true }), now)).toBe(false)
    expect(canRecall(msg({ isRevoked: true }), now)).toBe(false)
  })

  it('系统灰条不可撤回', () => {
    expect(canRecall(msg({ kind: ChatMessageKind.matchNotice }), now)).toBe(false)
  })

  it('图片消息可撤回', () => {
    expect(canRecall(msg({ kind: ChatMessageKind.image }), now)).toBe(true)
  })
})
