import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import MessageMenu from '@/features/chat/MessageMenu.vue'
import { ChatMessageKind } from '@/im/types'
import type { ChatMessage } from '@/im/types'

const message: ChatMessage = {
  msgId: 'm1',
  peerId: 'u8',
  isSelf: true,
  seq: 0,
  timestamp: 1,
  kind: ChatMessageKind.text,
  text: '你好',
  senderName: '小雨',
  senderAvatar: null,
  isPending: false,
  isFailed: false,
  imageUrl: null,
  imageLargeUrl: null,
  isRevoked: false,
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

  it('自己 2 分钟内的消息显示「撤回」', async () => {
    const w = mount(MessageMenu, {
      props: { message: { ...message, timestamp: Date.now() - 1000 }, x: 0, y: 0 },
    })
    expect(w.find('.message-menu__recall').exists()).toBe(true)

    await w.find('.message-menu__recall').trigger('click')
    expect(w.emitted('action')?.[0]).toEqual(['recall'])
  })

  it('超过 2 分钟不显示「撤回」', () => {
    const w = mount(MessageMenu, {
      props: { message: { ...message, timestamp: Date.now() - 3 * 60 * 1000 }, x: 0, y: 0 },
    })
    expect(w.find('.message-menu__recall').exists()).toBe(false)
  })

  // --- 多选入口(批次 T)---

  it('普通消息提供「多选」入口,点了 enters multi', async () => {
    const w = mount(MessageMenu, { props: { message, x: 0, y: 0 } })
    const multi = w.get('[data-testid="menu-multi"]')
    expect(multi.text()).toBe('多选')

    await multi.trigger('click')
    expect(w.emitted('action')?.[0]).toEqual(['multi'])
  })

  it('对方的消息也提供「多选」(多选删除对双方消息都生效,只删我这一侧)', () => {
    const w = mount(MessageMenu, { props: { message: { ...message, isSelf: false }, x: 0, y: 0 } })
    expect(w.find('[data-testid="menu-multi"]').exists()).toBe(true)
  })

  it('发送中的消息不能进多选(还没落库,服务端没有这一行)', () => {
    const w = mount(MessageMenu, {
      props: { message: { ...message, isPending: true }, x: 0, y: 0 },
    })
    expect(w.find('[data-testid="menu-multi"]').exists()).toBe(false)
  })

  it('已撤回的消息不能进多选', () => {
    const w = mount(MessageMenu, {
      props: { message: { ...message, isRevoked: true }, x: 0, y: 0 },
    })
    expect(w.find('[data-testid="menu-multi"]').exists()).toBe(false)
  })

  it('系统灰条不能进多选(不是气泡、也不属于用户内容)', () => {
    const w = mount(MessageMenu, {
      props: { message: { ...message, kind: ChatMessageKind.matchNotice }, x: 0, y: 0 },
    })
    expect(w.find('[data-testid="menu-multi"]').exists()).toBe(false)
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
