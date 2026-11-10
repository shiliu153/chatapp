import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ChatsPage from '@/features/chat/ChatsPage.vue'
import { useChatStore, type ChatStatus } from '@/stores/chat'
import { freshPinia } from '../support/pinia'
import { clearDraft, resetDrafts, saveDraft } from '@/features/chat/draft'
import type { ImConversation } from '@/im/types'

/**
 * 组件测试只验证渲染与交互:两个动作都替换掉,避免真的去连 IM 服务。
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

/** 一条带最后消息的会话(草稿前缀只挂在有摘要的行上) */
function conversationWithText(peerId: string, name: string, text: string): ImConversation {
  return {
    peerId,
    unreadCount: 0,
    showName: name,
    faceUrl: null,
    lastMessage: {
      msgId: 'm1',
      peerId,
      isSelf: false,
      seq: 1,
      timestamp: 1_700_000_000_000,
      kind: 'text' as never,
      text,
      senderName: name,
      senderAvatar: null,
      isPending: false,
      isFailed: false,
      imageUrl: null,
      imageLargeUrl: null,
      isRevoked: false,
    },
    peerReadSeq: 0,
    pinned: false,
    muted: false,
  }
}

describe('ChatsPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    // 草稿是模块级镜像 + localStorage,不逐用例清会互相污染
    localStorage.clear()
    resetDrafts()
  })

  it('没有会话时展示空态', async () => {
    const { pinia } = stubChatStore([])
    const w = mountPage(pinia)
    await flushPromises()
    expect(w.find('.app-empty').exists()).toBe(true)
  })

  it('系统通知置顶并显示未读角标', async () => {
    const { pinia } = stubChatStore([
      {
        peerId: 'system_notice',
        unreadCount: 1,
        showName: '系统通知',
        faceUrl: null,
        lastMessage: null,
        peerReadSeq: 0,
        pinned: false,
        muted: false,
      },
      {
        peerId: 'u8',
        unreadCount: 2,
        showName: '小雨',
        faceUrl: null,
        lastMessage: null,
        peerReadSeq: 0,
        pinned: false,
        muted: false,
      },
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
  // --- 草稿前缀(批次 T)---

  it('有草稿的会话在摘要前加「[草稿] 」,摘要本身仍然照常显示', async () => {
    saveDraft('u8', '没发完的半句话')
    const { pinia } = stubChatStore([conversationWithText('u8', '小雨', '对方最后一句')])
    const w = mountPage(pinia)
    await flushPromises()

    const draft = w.get('[data-testid="chats-draft"]')
    expect(draft.text()).toContain('[草稿]')
    // 草稿只是前缀,不能把摘要顶掉
    expect(w.text()).toContain('对方最后一句')
  })

  it('草稿存/清是响应式的:会话行跟着出现 / 消失前缀', async () => {
    const { pinia } = stubChatStore([conversationWithText('u8', '小雨', '对方最后一句')])
    const w = mountPage(pinia)
    await flushPromises()
    expect(w.find('[data-testid="chats-draft"]').exists()).toBe(false)

    saveDraft('u8', '打了一句')
    await flushPromises()
    expect(w.find('[data-testid="chats-draft"]').exists()).toBe(true)

    clearDraft('u8')
    await flushPromises()
    expect(w.find('[data-testid="chats-draft"]').exists()).toBe(false)
  })

  it('只是空白内容的草稿不算草稿(不会挂一个点进去什么都没有的前缀)', async () => {
    saveDraft('u8', '   ')
    const { pinia } = stubChatStore([conversationWithText('u8', '小雨', '对方最后一句')])
    const w = mountPage(pinia)
    await flushPromises()
    expect(w.find('[data-testid="chats-draft"]').exists()).toBe(false)
  })
})
