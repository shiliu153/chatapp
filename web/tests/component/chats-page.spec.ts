import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ChatsPage from '@/features/chat/ChatsPage.vue'
import { useChatStore, type ChatStatus } from '@/stores/chat'
import { freshPinia } from '../support/pinia'
import type { ImConversation } from '@/im/types'

/**
 * 组件测试只验证渲染与交互:两个动作都替换掉,避免真的去连腾讯云。
 * (预置状态的 pinia 必须与挂载用的是同一个,否则组件读到空 store。)
 */
function stubChatStore(conversations: ImConversation[], status: ChatStatus = 'ready') {
  const pinia = freshPinia()
  const store = useChatStore()
  store.conversations = conversations
  store.status = status
  store.connect = vi.fn(async () => {})
  store.loadConversations = vi.fn(async () => {})
  return { store, pinia }
}

function mountPage(pinia: ReturnType<typeof freshPinia>) {
  return mount(ChatsPage, {
    global: { plugins: [pinia], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

describe('ChatsPage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('没有会话时展示空态', async () => {
    const { pinia } = stubChatStore([])
    const w = mountPage(pinia)
    await flushPromises()
    expect(w.find('.app-empty').exists()).toBe(true)
  })

  it('系统通知置顶并显示未读角标', async () => {
    const { pinia } = stubChatStore([
      { peerId: 'system_notice', unreadCount: 1, showName: '系统通知', faceUrl: null, lastMessage: null },
      { peerId: 'u8', unreadCount: 2, showName: '小雨', faceUrl: null, lastMessage: null },
    ])
    const w = mountPage(pinia)
    await flushPromises()

    const rows = w.findAll('.chats__row')
    expect(rows[0].text()).toContain('系统通知')
    expect(rows[0].find('.app-badge').text()).toBe('1')
  })

  it('连接中展示骨架', async () => {
    // 计划的用例写的是 'loading',但 6.4 定义的状态机里没有这个值 —— 用 'connecting'
    const { pinia } = stubChatStore([], 'connecting')
    const w = mountPage(pinia)
    await flushPromises()
    expect(w.find('.app-skeleton').exists()).toBe(true)
  })

  it('同端被另一个窗口接管时,提示并提供手动接管', async () => {
    const { store, pinia } = stubChatStore([], 'inactive')
    store.reconnect = vi.fn(async () => {})
    const w = mountPage(pinia)
    await flushPromises()

    expect(w.find('.chats__inactive').exists()).toBe(true)
    expect(w.find('.app-skeleton').exists()).toBe(false) // 不能一直转圈
    await w.find('.chats__takeover').trigger('click')
    expect(store.reconnect).toHaveBeenCalled()
  })

  it('出错时给出重试入口', async () => {
    const { store, pinia } = stubChatStore([], 'error')
    const w = mountPage(pinia)
    await flushPromises()

    expect(w.find('.app-error').exists()).toBe(true)
    await w.find('.app-error button').trigger('click')
    expect(store.loadConversations).toHaveBeenCalled()
  })
})
