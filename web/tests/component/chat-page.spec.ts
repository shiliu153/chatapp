import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ChatPage from '@/features/chat/ChatPage.vue'
import { useChatStore } from '@/stores/chat'
import { freshPinia } from '../support/pinia'
import { ChatMessageKind } from '@/im/types'
import type { ChatMessage } from '@/im/types'

function msg(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    msgId: 'm1',
    peerId: 'u8',
    isSelf: false,
    timestamp: 1_700_000_000_000,
    kind: ChatMessageKind.text,
    text: '你好',
    senderName: '小雨',
    senderAvatar: null,
    isPending: false,
    isFailed: false,
    imageUrl: null,
    imageLargeUrl: null,
    ...overrides,
  }
}

/**
 * 组件测试只验证渲染与交互:三个会打网络的动作用假实现替换,
 * 预置状态的 pinia 与挂载必须是同一个。
 */
function mountPage(messages: ChatMessage[] = [msg()]) {
  const pinia = freshPinia()
  const store = useChatStore()
  store.messages = { u8: messages }
  store.connect = vi.fn(async () => {})
  store.loadConversations = vi.fn(async () => {})
  store.openConversation = vi.fn(async () => messages)
  store.sendText = vi.fn(async () => msg({ isSelf: true }))
  const w = mount(ChatPage, {
    props: { peerId: 'u8' },
    global: { plugins: [pinia], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
  return { w, store }
}

describe('ChatPage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('渲染气泡与文本', async () => {
    const { w } = mountPage()
    await flushPromises()
    expect(w.findAll('.message-bubble')).toHaveLength(1)
    expect(w.text()).toContain('你好')
  })

  it('系统灰条渲染成居中 pill', async () => {
    const { w } = mountPage([msg({ kind: ChatMessageKind.matchNotice, text: '你们已互相喜欢' })])
    await flushPromises()
    expect(w.find('.message-bubble--notice').exists()).toBe(true)
  })

  it('发送后清空输入框', async () => {
    const { w, store } = mountPage()
    await flushPromises()

    await w.find('input[type="text"]').setValue('在吗')
    await w.find('.chat__send').trigger('click')
    await flushPromises()

    expect(store.sendText).toHaveBeenCalledWith('u8', '在吗')
    expect((w.find('input[type="text"]').element as HTMLInputElement).value).toBe('')
  })

  it('失败的消息可重发', async () => {
    const { w, store } = mountPage([msg({ isFailed: true })])
    store.resend = vi.fn(async () => {})
    await flushPromises()

    await w.find('.message-bubble__retry').trigger('click')
    expect(store.resend).toHaveBeenCalled()
  })
})
