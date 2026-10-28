import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ChatPage from '@/features/chat/ChatPage.vue'
import { useChatStore } from '@/stores/chat'
import { useDiscoveryStore } from '@/stores/discovery'
import { freshPinia } from '../support/pinia'
import { ChatMessageKind } from '@/im/types'
import type { ChatMessage } from '@/im/types'

function msg(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    msgId: 'm1',
    peerId: 'u8',
    isSelf: false,
    seq: 0,
    timestamp: 1_700_000_000_000,
    kind: ChatMessageKind.text,
    text: '你好',
    senderName: '小雨',
    senderAvatar: null,
    isPending: false,
    isFailed: false,
    imageUrl: null,
    imageLargeUrl: null,
    isRevoked: false,
    ...overrides,
  }
}

/**
 * 组件测试只验证渲染与交互:会打网络的动作用假实现替换,
 * 预置状态的 pinia 与挂载必须是同一个。
 */
async function mountPage(
  messages: ChatMessage[] = [msg()],
  options: { focus?: string; beforeMount?: (store: ReturnType<typeof useChatStore>) => void } = {},
) {
  const pinia = freshPinia()
  const store = useChatStore()
  const discovery = useDiscoveryStore()
  store.messages = { u8: messages }
  store.connect = vi.fn(async () => {})
  store.loadConversations = vi.fn(async () => {})
  store.openConversation = vi.fn(async () => messages)
  // loadOlder 内部会走 ensureConnected(闭包里的真 connect),组件测试里一律替换掉
  store.loadOlder = vi.fn(async () => {})
  store.sendText = vi.fn(async () => msg({ isSelf: true }))
  store.deleteConversation = vi.fn(async () => {})
  discovery.loadMatches = vi.fn(async () => {})
  discovery.matchesLoaded = true
  discovery.matches = [{ user_id: 8, im_user_id: 'u8', nickname: '小雨', avatar_url: null, matched_at: '' }]
  options.beforeMount?.(store)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', redirect: '/chats' },
      { path: '/chats', name: 'chats', component: { template: '<div>消息</div>' } },
      { path: '/chat/:peerId', name: 'chat', component: { template: '<div />' } },
    ],
  })
  // 必须先完成导航再挂载:ChatPage 在 setup 里读 route.query.focus
  await router.push({
    name: 'chat',
    params: { peerId: 'u8' },
    query: options.focus ? { focus: options.focus } : {},
  })
  const w = mount(ChatPage, {
    props: { peerId: 'u8' },
    global: { plugins: [pinia, router], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
  return { w, store, discovery, router }
}

describe('ChatPage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('渲染气泡与文本', async () => {
    const { w } = await mountPage()
    await flushPromises()
    expect(w.findAll('.message-bubble')).toHaveLength(1)
    expect(w.text()).toContain('你好')
  })

  it('图片入口跟随 store 能力位(连上之前不显示)', async () => {
    const { w, store } = await mountPage()
    await flushPromises()
    // 兜底值 false:未连接时不能凭 client.capabilities 把入口藏死
    expect(w.find('[aria-label="发送图片"]').exists()).toBe(false)

    store.capabilities = { image: true, search: false, voice: false }
    await flushPromises()
    expect(w.find('[aria-label="发送图片"]').exists()).toBe(true)
  })

  it('系统灰条渲染成居中 pill', async () => {
    const { w } = await mountPage([msg({ kind: ChatMessageKind.matchNotice, text: '你们已互相喜欢' })])
    await flushPromises()
    expect(w.find('.message-bubble--notice').exists()).toBe(true)
  })

  it('发送后清空输入框', async () => {
    const { w, store } = await mountPage()
    await flushPromises()

    await w.find('input[type="text"]').setValue('在吗')
    await w.find('.chat__send').trigger('click')
    await flushPromises()

    expect(store.sendText).toHaveBeenCalledWith('u8', '在吗')
    expect((w.find('input[type="text"]').element as HTMLInputElement).value).toBe('')
  })

  it('失败的消息可重发', async () => {
    const { w, store } = await mountPage([msg({ isFailed: true })])
    store.resend = vi.fn(async () => {})
    await flushPromises()

    await w.find('.message-bubble__retry').trigger('click')
    expect(store.resend).toHaveBeenCalled()
  })

  it('自己 2 分钟内的消息:菜单点「撤回」→ 调 store', async () => {
    const { w, store } = await mountPage([msg({ isSelf: true, timestamp: Date.now() })])
    store.revokeMessage = vi.fn(async () => {})
    await flushPromises()

    await w.find('.message-bubble__more').trigger('click')
    await w.find('.message-menu__recall').trigger('click')
    await flushPromises()

    expect(store.revokeMessage).toHaveBeenCalledWith(expect.objectContaining({ msgId: 'm1' }))
  })

  it('已撤回的消息渲染成居中灰字', async () => {
    const { w } = await mountPage([msg({ isRevoked: true, isSelf: true })])
    await flushPromises()
    expect(w.text()).toContain('你撤回了一条消息')
  })

  it('「⋯」→ 解除配对 → 调接口、删会话并回消息页', async () => {
    const { w, store, discovery, router } = await mountPage()
    discovery.unmatch = vi.fn(async () => {})
    await flushPromises()

    await w.find('.chat__more').trigger('click')
    await w.find('.chat-more__unmatch').trigger('click')
    await flushPromises()
    await w.find('.unmatch-dialog__confirm').trigger('click')
    await flushPromises()

    expect(discovery.unmatch).toHaveBeenCalledWith(8)
    expect(store.deleteConversation).toHaveBeenCalledWith('u8')
    expect(router.currentRoute.value.name).toBe('chats')
  })

  it('配对列表里没有对方:显示已解除横幅并禁用输入', async () => {
    const { w, discovery } = await mountPage()
    discovery.matches = []
    await flushPromises()

    expect(w.find('.chat__unmatched').exists()).toBe(true)
    expect((w.find('input[type="text"]').element as HTMLInputElement).disabled).toBe(true)
  })

  it('带 focus 进聊天页:往前翻到目标消息并高亮', async () => {
    const target = msg({
      msgId: 'target',
      seq: 99,
      timestamp: 1_700_000_000_000,
      text: '上周的地址',
    })
    const recent = [
      msg({ msgId: 'm2', seq: 101, timestamp: 1_700_000_100_000 }),
      msg({ msgId: 'm3', seq: 102, timestamp: 1_700_000_200_000 }),
    ]
    const { w, store } = await mountPage(recent, {
      focus: 'target',
      // 模拟「目标在更早的一页」:loadOlder 把目标页并进消息列表
      beforeMount: (s) => {
        s.loadOlder = vi.fn(async (_peerId: string, msgId: string) => {
          if (msgId === 'target') s.messages = { u8: [target, ...recent] }
        })
      },
    })
    await flushPromises()

    expect(store.loadOlder).toHaveBeenCalledWith('u8', 'target')
    const element = w.find('[data-msg-id="target"]')
    expect(element.exists()).toBe(true)
    expect(element.classes()).toContain('message-bubble--hit')
    expect(element.text()).toContain('上周的地址')
    w.unmount()
  })
})
