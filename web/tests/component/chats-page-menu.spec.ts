import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/error'
import ChatsPage from '@/features/chat/ChatsPage.vue'
import { useChatStore } from '@/stores/chat'
import { freshPinia } from '../support/pinia'
import type { ImConversation } from '@/im/types'

/**
 * 会话列表的「更多」菜单(批次 N):置顶 / 免打扰 / 删除会话。
 *
 * 真正要钉住的四件事:
 * 1) 入口**常驻可见**(右键 + 行内 `⋯` 按钮),不做成 hover 才出现 —— 触屏点不到 hover;
 * 2) 菜单三项调用的参数正确(置顶传 `{pinned}`、免打扰传 `{muted}`、删除走 store);
 * 3) 展示:置顶分组标题、免打扰静音图标 + 灰点(不出数字);
 * 4) 错误:`40401` 提示会话已不存在并刷新列表,其他错误原样提示且**不改本地状态**。
 */

const conversation = (overrides: Partial<ImConversation>): ImConversation => ({
  peerId: 'u8',
  unreadCount: 0,
  showName: '小雨',
  faceUrl: null,
  lastMessage: null,
  peerReadSeq: 0,
  pinned: false,
  muted: false,
  ...overrides,
})

/** 组件测试只验证渲染与交互:连 IM / 拉列表 / 写偏好全部换掉 */
function stubChatStore(conversations: ImConversation[]) {
  const pinia = freshPinia()
  const store = useChatStore()
  store.conversations = conversations
  store.status = 'ready'
  store.connect = vi.fn(async () => {})
  store.loadConversations = vi.fn(async () => {})
  store.setConversationFlags = vi.fn(async () => ({ pinned: false, muted: false }))
  store.deleteConversation = vi.fn(async () => {})
  return { store, pinia }
}

function mountPage(pinia: ReturnType<typeof freshPinia>) {
  return mount(ChatsPage, {
    global: { plugins: [pinia], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

/** 打开第一行的「更多」菜单(行内 `⋯` 按钮,不需要 hover) */
async function openMenu(w: ReturnType<typeof mountPage>) {
  await w.find('.chats__more').trigger('click')
  await flushPromises()
}

describe('ChatsPage 会话菜单', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('每行都有常驻的「更多」入口(按钮在,不依赖 hover)', async () => {
    const { pinia } = stubChatStore([
      conversation({ peerId: 'u8' }),
      conversation({ peerId: 'u9' }),
    ])
    const w = mountPage(pinia)
    await flushPromises()

    const buttons = w.findAll('.chats__more')
    expect(buttons).toHaveLength(2)
    expect(buttons[0].attributes('type')).toBe('button')
    expect(buttons[0].attributes('aria-label')).toBe('更多操作')
  })

  it('右键整行也能打开菜单(PC 肌肉记忆)', async () => {
    const { pinia } = stubChatStore([conversation({ peerId: 'u8' })])
    const w = mountPage(pinia)
    await flushPromises()

    await w.find('.chats__item').trigger('contextmenu', { clientX: 40, clientY: 60 })
    await flushPromises()

    expect(w.find('[data-testid="menu-pin"]').text()).toBe('置顶')
    expect(w.find('[data-testid="menu-mute"]').text()).toBe('免打扰')
    expect(w.find('[data-testid="menu-delete"]').text()).toBe('删除会话')
  })

  it('点「置顶」调用 { pinned: true } 并收起菜单', async () => {
    const { store, pinia } = stubChatStore([conversation({ peerId: 'u8' })])
    const w = mountPage(pinia)
    await flushPromises()

    await openMenu(w)
    await w.find('[data-testid="menu-pin"]').trigger('click')
    await flushPromises()

    expect(store.setConversationFlags).toHaveBeenCalledWith('u8', { pinned: true })
    expect(w.find('[data-testid="menu-pin"]').exists()).toBe(false)
  })

  it('已置顶的会话菜单显示「取消置顶」,点了传 { pinned: false }', async () => {
    const { store, pinia } = stubChatStore([conversation({ peerId: 'u8', pinned: true })])
    const w = mountPage(pinia)
    await flushPromises()

    await openMenu(w)
    expect(w.find('[data-testid="menu-pin"]').text()).toBe('取消置顶')
    await w.find('[data-testid="menu-pin"]').trigger('click')
    await flushPromises()

    expect(store.setConversationFlags).toHaveBeenCalledWith('u8', { pinned: false })
  })

  it('点「免打扰」调用 { muted: true }', async () => {
    const { store, pinia } = stubChatStore([conversation({ peerId: 'u8' })])
    const w = mountPage(pinia)
    await flushPromises()

    await openMenu(w)
    await w.find('[data-testid="menu-mute"]').trigger('click')
    await flushPromises()

    expect(store.setConversationFlags).toHaveBeenCalledWith('u8', { muted: true })
  })

  it('免打扰会话:显示静音图标与灰点,不显示未读数字', async () => {
    const { pinia } = stubChatStore([
      conversation({ peerId: 'u8', muted: true, unreadCount: 5 }),
      conversation({ peerId: 'u9', unreadCount: 2 }),
    ])
    const w = mountPage(pinia)
    await flushPromises()

    const mutedRow = w.findAll('.chats__row')[0]
    expect(mutedRow.find('.chats__muted').exists()).toBe(true)
    expect(mutedRow.find('.chats__unread-dot').exists()).toBe(true)
    expect(mutedRow.find('.app-badge').exists()).toBe(false)

    // 未免打扰的行照旧显示数字
    const normalRow = w.findAll('.chats__row')[1]
    expect(normalRow.find('.chats__muted').exists()).toBe(false)
    expect(normalRow.find('.app-badge').text()).toBe('2')
  })

  it('免打扰且没有未读:只有静音图标,不出现灰点', async () => {
    const { pinia } = stubChatStore([conversation({ peerId: 'u8', muted: true, unreadCount: 0 })])
    const w = mountPage(pinia)
    await flushPromises()

    const row = w.find('.chats__row')
    expect(row.find('.chats__muted').exists()).toBe(true)
    expect(row.find('.chats__unread-dot').exists()).toBe(false)
  })

  it('置顶会话进「置顶」分组,其余在「全部会话」下(顺序不动)', async () => {
    const { pinia } = stubChatStore([
      conversation({ peerId: 'u8', pinned: true, showName: '小雨' }),
      conversation({ peerId: 'u9', showName: '小九' }),
      conversation({ peerId: 'u10', showName: '小十' }),
    ])
    const w = mountPage(pinia)
    await flushPromises()

    const titles = w.findAll('.chats__group-title').map((node) => node.text())
    expect(titles).toEqual(['置顶', '全部会话'])

    const names = w.findAll('.chats__name-text').map((node) => node.text())
    expect(names).toEqual(['小雨', '小九', '小十'])
  })

  it('没有置顶会话时不出现任何分组标题', async () => {
    const { pinia } = stubChatStore([conversation({ peerId: 'u8' })])
    const w = mountPage(pinia)
    await flushPromises()

    expect(w.findAll('.chats__group-title')).toHaveLength(0)
  })

  it('删除会话:必须先二次确认,确认后调 store.deleteConversation', async () => {
    const { store, pinia } = stubChatStore([conversation({ peerId: 'u8', showName: '小雨' })])
    const w = mountPage(pinia)
    await flushPromises()

    await openMenu(w)
    await w.find('[data-testid="menu-delete"]').trigger('click')
    await flushPromises()

    // 点了「删除会话」只是弹确认框,还没真删
    expect(w.find('.delete-conversation').exists()).toBe(true)
    expect(store.deleteConversation).not.toHaveBeenCalled()

    await w.find('.delete-conversation__confirm').trigger('click')
    await flushPromises()

    expect(store.deleteConversation).toHaveBeenCalledWith('u8')
    expect(w.find('.delete-conversation').exists()).toBe(false)
  })

  it('取消删除:不调 store,确认框收起', async () => {
    const { store, pinia } = stubChatStore([conversation({ peerId: 'u8' })])
    const w = mountPage(pinia)
    await flushPromises()

    await openMenu(w)
    await w.find('[data-testid="menu-delete"]').trigger('click')
    await flushPromises()
    const cancel = w.findAll('.delete-conversation__actions button')[0]
    await cancel.trigger('click')
    await flushPromises()

    expect(store.deleteConversation).not.toHaveBeenCalled()
    expect(w.find('.delete-conversation').exists()).toBe(false)
  })

  it('40401(会话不存在):提示并刷新列表', async () => {
    const { store, pinia } = stubChatStore([conversation({ peerId: 'u8' })])
    vi.mocked(store.setConversationFlags).mockRejectedValue(
      new ApiError(40401, '会话不存在', undefined, 404),
    )
    const w = mountPage(pinia)
    await flushPromises()
    const loadsBefore = vi.mocked(store.loadConversations).mock.calls.length

    await openMenu(w)
    await w.find('[data-testid="menu-pin"]').trigger('click')
    await flushPromises()

    expect(w.find('.app-toast').text()).toContain('该会话已不存在')
    expect(vi.mocked(store.loadConversations).mock.calls.length).toBe(loadsBefore + 1)
  })

  it('其他错误:提示服务端文案,本地状态不动(没有乐观更新)', async () => {
    const { store, pinia } = stubChatStore([conversation({ peerId: 'u8' })])
    vi.mocked(store.setConversationFlags).mockRejectedValue(
      new ApiError(50001, '内部错误', undefined, 500),
    )
    const w = mountPage(pinia)
    await flushPromises()

    await openMenu(w)
    await w.find('[data-testid="menu-pin"]').trigger('click')
    await flushPromises()

    expect(w.find('.app-toast').text()).toContain('内部错误')
    expect(store.conversations[0].pinned).toBe(false)
  })

  it('限流(429):提示稍后再试', async () => {
    const { store, pinia } = stubChatStore([conversation({ peerId: 'u8' })])
    vi.mocked(store.setConversationFlags).mockRejectedValue(
      new ApiError(42901, '操作过于频繁', undefined, 429),
    )
    const w = mountPage(pinia)
    await flushPromises()

    await openMenu(w)
    await w.find('[data-testid="menu-mute"]').trigger('click')
    await flushPromises()

    expect(w.find('.app-toast').text()).toContain('操作太频繁')
  })
})
