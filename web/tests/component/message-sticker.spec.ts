import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MessageBubble from '@/features/chat/MessageBubble.vue'
import { CHAT_STICKERS, UNKNOWN_STICKER_LABEL, stickerById } from '@/features/chat/stickers'
import type { ChatMessage } from '@/im/types'

/**
 * 贴纸气泡(批次 J)。
 *
 * 覆盖两件在单测里最容易漏、真机上最难看出来的事:
 * 1) 已知 id 渲染本地资源,**不套气泡底色**(贴纸自带描边与圆角);
 * 2) 未知 id(老版本收到新贴纸)降级成「[贴纸]」文本,不白屏。
 */

function stickerMessage(stickerId: string): ChatMessage {
  return {
    msgId: 's1',
    peerId: 'u8',
    isSelf: false,
    seq: 1,
    timestamp: 1,
    kind: 'sticker' as never,
    text: '',
    senderName: '小雨',
    senderAvatar: null,
    isPending: false,
    isFailed: false,
    imageUrl: null,
    imageLargeUrl: null,
    stickerId,
    isRevoked: false,
  }
}

describe('贴纸气泡', () => {
  it('已知 id:按 id 渲染本地资源,且不套气泡底色', () => {
    const w = mount(MessageBubble, { props: { message: stickerMessage('sticker_01') } })

    const img = w.get('[data-testid="sticker-sticker_01"]')
    expect(img.attributes('src')).toBe('/stickers/sticker_01.png')
    expect(w.get('.message-bubble__body').classes()).toContain('message-bubble__body--sticker')
  })

  it('未知 id:降级「[贴纸]」文本,不渲染图片', () => {
    const w = mount(MessageBubble, { props: { message: stickerMessage('sticker_99') } })

    expect(w.find('[data-testid="sticker-unknown"]').exists()).toBe(true)
    expect(w.text()).toContain(UNKNOWN_STICKER_LABEL)
    expect(w.find('img').exists()).toBe(false)
  })

  it('目录:12 张,id 与资源地址一一对应', () => {
    expect(CHAT_STICKERS).toHaveLength(12)
    for (const sticker of CHAT_STICKERS) {
      expect(sticker.id).toMatch(/^sticker_\d{2}$/)
      expect(sticker.src).toBe(`/stickers/${sticker.id}.png`)
      expect(stickerById(sticker.id)?.label).toBe(sticker.label)
    }
    expect(stickerById(null)).toBeUndefined()
    expect(stickerById('sticker_99')).toBeUndefined()
  })
})
