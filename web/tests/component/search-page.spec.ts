import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ChatsPage from '@/features/chat/ChatsPage.vue'
import SearchPage from '@/features/chat/SearchPage.vue'
import { useChatStore } from '@/stores/chat'
import { freshPinia } from '../support/pinia'
import type { ImSearchHit, ImSearchResult } from '@/im/types'

function hit(overrides: Partial<ImSearchHit> = {}): ImSearchHit {
  return {
    msgId: '42',
    seq: 7,
    peerId: 'u9',
    peerName: '阿九',
    peerAvatar: null,
    text: '晚上吃火锅吗',
    timestamp: 1_761_465_600_000,
    ...overrides,
  }
}

/** 页面测试只验渲染与交互:搜索动作替换成假实现,不打网络。 */
function stubStore(results: ImSearchResult | (() => Promise<ImSearchResult>)) {
  const pinia = freshPinia()
  const store = useChatStore()
  const searchMessages =
    typeof results === 'function' ? vi.fn(results) : vi.fn(async () => results)
  store.searchMessages = searchMessages
  store.capabilities = { image: true, search: true, voice: false }
  return { store, pinia, searchMessages }
}

function mountSearch(pinia: ReturnType<typeof freshPinia>) {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', redirect: '/chats' },
      { path: '/chats', name: 'chats', component: { template: '<div>消息</div>' } },
      { path: '/search', name: 'search', component: SearchPage },
      { path: '/chat/:peerId', name: 'chat', component: { template: '<div>聊天</div>' } },
    ],
  })
  void router.push('/search')
  const w = mount(SearchPage, { global: { plugins: [pinia, router] } })
  return { w, router }
}

/** 输入后等过 300ms 防抖,再冲一遍微任务。 */
async function typeAndWait(w: ReturnType<typeof mountSearch>['w'], text: string) {
  await w.find('input').setValue(text)
  await new Promise((resolve) => setTimeout(resolve, 350))
  await flushPromises()
}

describe('SearchPage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('防抖后展示命中,并把关键词包成 mark', async () => {
    const { pinia, searchMessages } = stubStore({
      items: [hit()],
      hasMore: false,
    })
    const { w } = mountSearch(pinia)

    await typeAndWait(w, '火锅')

    expect(searchMessages).toHaveBeenCalledWith('火锅', 20, undefined)
    expect(w.find('[data-msg-id="42"]').exists()).toBe(true)
    expect(w.find('.search__name').text()).toBe('阿九')
    expect(w.find('.search__snippet mark').text()).toBe('火锅')
  })

  it('点结果进聊天页并带 focus 定位参数', async () => {
    const { pinia } = stubStore({ items: [hit()], hasMore: false })
    const { w, router } = mountSearch(pinia)

    await typeAndWait(w, '火锅')
    await w.find('[data-msg-id="42"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('chat')
    expect(router.currentRoute.value.params.peerId).toBe('u9')
    expect(router.currentRoute.value.query.focus).toBe('42')
  })

  it('没有命中时显示空态', async () => {
    const { pinia } = stubStore({ items: [], hasMore: false })
    const { w } = mountSearch(pinia)

    await typeAndWait(w, '不存在')

    expect(w.text()).toContain('没有找到相关消息')
  })

  it('加载更多用最后一条的 msgId 作游标', async () => {
    const { pinia, searchMessages } = stubStore({
      items: [hit()],
      hasMore: true,
    })
    const { w } = mountSearch(pinia)

    await typeAndWait(w, '火锅')
    await w.find('.search__more').trigger('click')
    await flushPromises()

    expect(searchMessages).toHaveBeenLastCalledWith('火锅', 20, '42')
  })

  it('命中文本里的 HTML 只当文本渲染(防 XSS)', async () => {
    const { pinia } = stubStore({
      items: [hit({ text: '<img src=x onerror=alert(1)> 火锅' })],
      hasMore: false,
    })
    const { w } = mountSearch(pinia)

    await typeAndWait(w, '火锅')

    expect(w.find('.search__snippet img').exists()).toBe(false)
    expect(w.find('.search__snippet').text()).toContain('<img src=x onerror=alert(1)>')
  })

  it('搜索失败给出错误态与重试', async () => {
    let calls = 0
    const { pinia } = stubStore(async () => {
      calls += 1
      if (calls === 1) throw new Error('网络开小差了')
      return { items: [hit()], hasMore: false }
    })
    const { w } = mountSearch(pinia)

    await typeAndWait(w, '火锅')
    expect(w.text()).toContain('网络开小差了')

    await w.find('.app-error button').trigger('click')
    await flushPromises()
    expect(w.find('[data-msg-id="42"]').exists()).toBe(true)
  })
})

describe('消息页搜索入口', () => {
  beforeEach(() => setActivePinia(createPinia()))

  function mountChats(pinia: ReturnType<typeof freshPinia>) {
    const router = createRouter({
      history: createMemoryHistory(),
      routes: [
        { path: '/', redirect: '/chats' },
        { path: '/chats', name: 'chats', component: ChatsPage },
        { path: '/search', name: 'search', component: { template: '<div>搜索</div>' } },
      ],
    })
    void router.push('/chats')
    return {
      router,
      w: mount(ChatsPage, {
        global: { plugins: [pinia, router], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
      }),
    }
  }

  function stubChatsStore(search: boolean) {
    const pinia = freshPinia()
    const store = useChatStore()
    store.capabilities = { image: false, search, voice: false }
    store.connect = vi.fn(async () => {})
    store.loadConversations = vi.fn(async () => {})
    return pinia
  }

  it('自建后端(能力位 true)显示搜索按钮并跳到 /search', async () => {
    const pinia = stubChatsStore(true)
    const { w, router } = mountChats(pinia)
    await flushPromises()

    const button = w.find('.chats__search')
    expect(button.exists()).toBe(true)
    expect(button.attributes('aria-label')).toBe('搜索聊天记录')

    await button.trigger('click')
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('search')
  })

  it('腾讯后端(能力位 false)不显示搜索入口', async () => {
    const pinia = stubChatsStore(false)
    const { w } = mountChats(pinia)
    await flushPromises()

    expect(w.find('.chats__search').exists()).toBe(false)
  })
})
