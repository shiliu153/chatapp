import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MessageMenu from '@/features/chat/MessageMenu.vue'
import { ChatMessageKind } from '@/im/types'
import type { ChatMessage } from '@/im/types'

const message: ChatMessage = {
  msgId: 'm1',
  peerId: 'u8',
  isSelf: true,
  timestamp: 1,
  kind: ChatMessageKind.text,
  text: '你好',
  senderName: '小雨',
  senderAvatar: null,
  isPending: false,
  isFailed: false,
  imageUrl: null,
  imageLargeUrl: null,
}

describe('MessageMenu', () => {
  it('自己的文本消息:可复制、可删除', async () => {
    const w = mount(MessageMenu, { props: { message, x: 10, y: 10 } })
    expect(w.text()).toContain('复制')
    expect(w.text()).toContain('删除')

    await w.find('.message-menu__copy').trigger('click')
    expect(w.emitted('action')?.[0]).toEqual(['copy'])
  })

  it('对方的消息:不提供删除', () => {
    const w = mount(MessageMenu, { props: { message: { ...message, isSelf: false }, x: 0, y: 0 } })
    expect(w.find('.message-menu__delete').exists()).toBe(false)
  })

  it('失败的消息:提供重发', () => {
    const w = mount(MessageMenu, { props: { message: { ...message, isFailed: true }, x: 0, y: 0 } })
    expect(w.find('.message-menu__retry').exists()).toBe(true)
  })

  it('按 Esc 关闭', async () => {
    const w = mount(MessageMenu, {
      props: { message, x: 0, y: 0 },
      attachTo: document.body,
    })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(w.emitted('close')).toHaveLength(1)
    w.unmount()
  })
})
