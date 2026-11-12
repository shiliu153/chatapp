import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createMemoryHistory, createRouter } from 'vue-router'
import ChatPage from '@/features/chat/ChatPage.vue'
import { useChatStore } from '@/stores/chat'
import { useDiscoveryStore } from '@/stores/discovery'
import { freshPinia } from '../support/pinia'
import { ApiError } from '@/api/error'
import { resetDrafts, saveDraft } from '@/features/chat/draft'
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
  store.sendSticker = vi.fn(async () => msg({ isSelf: true, kind: ChatMessageKind.sticker }))
  store.deleteConversation = vi.fn(async () => {})
  store.deleteMessages = vi.fn(async (_peerId: string, ids: string[]) => ids.length)
  discovery.loadMatches = vi.fn(async () => {})
  discovery.matchesLoaded = true
  discovery.matches = [
    {
      user_id: 8,
      im_user_id: 'u8',
      nickname: '小雨',
      avatar_url: null,
      matched_at: '',
      shared_tags: [],
    },
  ]
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

/** 挂载 → 打开菜单 → 点「多选」:多选模式的唯一入口(与 App 一致) */
async function enterMultiSelect(w: ReturnType<typeof mount>, msgId: string) {
  await w.find(`[data-msg-id="${msgId}"] .message-bubble__more`).trigger('click')
  await w.find('[data-testid="menu-multi"]').trigger('click')
  await flushPromises()
}

describe('ChatPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    // 草稿是模块级镜像 + localStorage:不逐用例清会互相污染
    localStorage.clear()
    resetDrafts()
  })

  // 2026-11-11 默认分支的 web 轨红过一次(PR 轨绿、合并后红),失败用例正是草稿防抖:
  // 它在 299ms 时断言「旧草稿还在」,而旧草稿是**上一个用例的残留状态**。CI 上环境创建
  // 慢(每个 jsdom ~1s),跨用例的 fake timer 若没被清掉,会在下个用例里触发
  // `saveDraft('', ...)` → `clearDraft`,把预置值删掉。这里统一兜底清 timer,
  // 并让防抖用例不依赖任何预置草稿(见下)。
  afterEach(() => {
    vi.clearAllTimers()
    vi.useRealTimers()
  })

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

    store.capabilities = { image: true, search: false, voice: false, readReceipt: false }
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

  it('贴纸面板:切 tab 点选直接发送,不插输入框', async () => {
    const { w, store } = await mountPage()
    await flushPromises()

    await w.find('[aria-label="表情"]').trigger('click')
    await w.find('[data-testid="panel-tab-sticker"]').trigger('click')
    await w.find('[data-testid="sticker-sticker_01"]').trigger('click')
    await flushPromises()

    expect(store.sendSticker).toHaveBeenCalledWith('u8', 'sticker_01')
    // 贴纸是直接发送:输入框不该被写进任何东西
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

  it('会话被另一台设备删掉(多端在线 K-3):自动退回消息列表', async () => {
    const { store, router } = await mountPage([msg()], {
      beforeMount: (chat) => {
        chat.conversations = [
          {
            peerId: 'u8',
            unreadCount: 0,
            showName: '小雨',
            faceUrl: null,
            lastMessage: null,
            peerReadSeq: 0,
            pinned: false,
            muted: false,
          },
        ]
      },
    })
    await flushPromises()
    expect(router.currentRoute.value.name).toBe('chat')

    // store 收到 conversation_deleted 后移除该会话(见 stores/chat.ts::removeConversation)
    store.conversations = []
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('chats')
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

  it('能力不支持时麦克风仍渲染但置灰,点击给出原因', async () => {
    const { w } = await mountPage()
    await flushPromises()
    const mic = w.find('[aria-label="语音消息"]')
    expect(mic.exists()).toBe(true)
    // 置灰用 aria-disabled 而不是 disabled:disabled 会吞掉 click,就没法解释原因
    expect(mic.attributes('aria-disabled')).toBe('true')

    await mic.trigger('click')
    await flushPromises()
    expect(w.text()).toContain('当前浏览器不支持录音')
  })

  it('能力支持时点麦克风进入录音条', async () => {
    const { w, store } = await mountPage()
    await flushPromises()

    // jsdom 没有 MediaRecorder:先把浏览器能力桩上,再改能力位触发重算
    vi.stubGlobal(
      'MediaRecorder',
      class {
        static isTypeSupported = () => true
        state = 'inactive'
        mimeType = 'audio/webm'
        ondataavailable: ((event: { data: Blob }) => void) | null = null
        onstop: (() => void) | null = null
        start(): void {
          this.state = 'recording'
        }
        stop(): void {
          this.state = 'inactive'
          this.onstop?.()
        }
      },
    )
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] })) },
    })
    store.capabilities = { image: true, search: false, voice: true, readReceipt: false }
    await flushPromises()

    await w.find('[aria-label="语音消息"]').trigger('click')
    await flushPromises()
    expect(w.find('.voice-bar').exists()).toBe(true)

    w.unmount()
    vi.unstubAllGlobals()
  })
  // --- 多选删除(批次 T)---

  it('多选:菜单「多选」→ 勾选两条 → 确认框 → 调接口并从列表移除', async () => {
    const { w, store } = await mountPage([
      msg({ msgId: 'm1', seq: 1, text: '一' }),
      msg({ msgId: 'm2', seq: 2, text: '二' }),
      msg({ msgId: 'm3', seq: 3, text: '三' }),
    ])
    // store 真的把消息摘掉,才能验证「删除后列表少两条」而不只是「接口被调过」
    store.deleteMessages = vi.fn(async (peerId: string, ids: string[]) => {
      store.messages = {
        [peerId]: store.messagesOf(peerId).filter((item) => !ids.includes(item.msgId)),
      }
      return ids.length
    })
    await flushPromises()

    await enterMultiSelect(w, 'm1')
    // 进多选时顺手勾上触发它的那条
    expect(w.get('[data-test="chat-multi-count"]').text()).toBe('已选 1 条')
    // 普通顶栏与输入区让位
    expect(w.find('.chat__composer').exists()).toBe(false)

    await w.find('[data-msg-id="m2"]').trigger('click')
    expect(w.get('[data-test="chat-multi-count"]').text()).toBe('已选 2 条')

    await w.find('[data-test="chat-multi-delete"]').trigger('click')
    expect(w.text()).toContain('只在你这边删除,对方仍可见')

    await w.find('.delete-messages__confirm').trigger('click')
    await flushPromises()

    expect(store.deleteMessages).toHaveBeenCalledWith('u8', ['m1', 'm2'])
    // 删完退出多选、恢复普通顶栏
    expect(w.find('[data-test="chat-multi-count"]').exists()).toBe(false)
    expect(w.findAll('[data-msg-id]')).toHaveLength(1)
    expect(w.text()).toContain('三')
  })

  it('多选:点同一条再点一次就取消勾选', async () => {
    const { w } = await mountPage([msg({ msgId: 'm1', seq: 1 })])
    await flushPromises()

    await enterMultiSelect(w, 'm1')
    expect(w.get('[data-test="chat-multi-count"]').text()).toBe('已选 1 条')

    await w.find('[data-msg-id="m1"]').trigger('click')
    expect(w.get('[data-test="chat-multi-count"]').text()).toBe('已选 0 条')
  })

  it('多选:删除失败保留选中并 toast,不退多选', async () => {
    const { w, store } = await mountPage([
      msg({ msgId: 'm1', seq: 1 }),
      msg({ msgId: 'm2', seq: 2 }),
    ])
    store.deleteMessages = vi.fn(async () => {
      throw new ApiError(42901, '操作过于频繁')
    })
    await flushPromises()

    await enterMultiSelect(w, 'm1')
    await w.find('[data-msg-id="m2"]').trigger('click')
    await w.find('[data-test="chat-multi-delete"]').trigger('click')
    await w.find('.delete-messages__confirm').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('操作过于频繁')
    // 选中与多选模式都原样保留,用户可以原地重试
    expect(w.get('[data-test="chat-multi-count"]').text()).toBe('已选 2 条')
    expect(w.findAll('[data-msg-id]')).toHaveLength(2)
  })

  it('多选模式下长按/右键不再弹菜单(点消息只切换勾选)', async () => {
    const { w } = await mountPage([msg({ msgId: 'm1', seq: 1 })])
    await flushPromises()

    await enterMultiSelect(w, 'm1')
    await w.find('[data-msg-id="m1"]').trigger('contextmenu')
    await flushPromises()

    expect(w.find('.message-menu').exists()).toBe(false)
  })

  it('已撤回的消息不可勾选(点它不加计数)', async () => {
    const { w } = await mountPage([
      msg({ msgId: 'm1', seq: 1 }),
      msg({ msgId: 'm2', seq: 2, isRevoked: true, isSelf: true }),
    ])
    await flushPromises()

    await enterMultiSelect(w, 'm1')
    await w.find('[data-msg-id="m2"]').trigger('click')
    expect(w.get('[data-test="chat-multi-count"]').text()).toBe('已选 1 条')
  })

  it('发送中的消息不可勾选,也不提供多选入口', async () => {
    const { w } = await mountPage([
      msg({ msgId: 'm1', seq: 1 }),
      msg({ msgId: 'm2', seq: 0, isPending: true, isSelf: true }),
    ])
    await flushPromises()

    await enterMultiSelect(w, 'm1')
    await w.find('[data-msg-id="m2"]').trigger('click')
    expect(w.get('[data-test="chat-multi-count"]').text()).toBe('已选 1 条')
  })

  it('多选:复制文本把选中的文本按顺序用换行连接', async () => {
    const writeText = vi.fn(async () => {})
    Object.defineProperty(navigator, 'clipboard', {
      value: { writeText },
      configurable: true,
    })
    const { w } = await mountPage([
      msg({ msgId: 'm1', seq: 1, text: '你好' }),
      msg({ msgId: 'm2', seq: 2, text: '在吗' }),
      msg({ msgId: 'm3', seq: 3, text: '', kind: ChatMessageKind.image }),
    ])
    await flushPromises()

    await enterMultiSelect(w, 'm1')
    await w.find('[data-msg-id="m2"]').trigger('click')
    await w.find('[data-msg-id="m3"]').trigger('click')

    await w.find('[data-test="chat-multi-copy"]').trigger('click')
    await flushPromises()

    // 图片消息没有正文,不参与拼接
    expect(writeText).toHaveBeenCalledWith('你好\n在吗')
    expect(w.text()).toContain('已复制')
  })

  it('多选:「取消」退出多选,回到普通顶栏与输入区', async () => {
    const { w } = await mountPage([msg({ msgId: 'm1', seq: 1 })])
    await flushPromises()

    await enterMultiSelect(w, 'm1')
    await w.find('[data-test="chat-multi-cancel"]').trigger('click')

    expect(w.find('[data-test="chat-multi-count"]').exists()).toBe(false)
    expect(w.find('.chat__composer').exists()).toBe(true)
  })

  // --- 草稿(批次 T)---

  it('草稿:进会话回填(预置草稿出现在输入框)', async () => {
    saveDraft('u8', '上次没说完')
    const { w } = await mountPage()
    await flushPromises()

    expect((w.find('input[type="text"]').element as HTMLInputElement).value).toBe('上次没说完')
  })

  it('草稿:输入防抖 300ms 落盘', async () => {
    // **不预置草稿**:这个用例只验证「输入 → 300ms 后落盘」的时序。
    // 旧版在这里预置 '上次没说完' 再断言「299ms 时它还在」,那等于把
    // 「上一个用例有没有留下 timer」也变成了断言条件 —— CI 上就是这么红的。
    const { w } = await mountPage()
    await flushPromises()

    vi.useFakeTimers()
    try {
      await w.find('input[type="text"]').setValue('这次接着说')
      // 300ms 内不落盘(边打字边写 localStorage 没必要)
      vi.advanceTimersByTime(299)
      expect(localStorage.getItem('chat_draft:u8')).toBeNull()

      vi.advanceTimersByTime(1)
      expect(localStorage.getItem('chat_draft:u8')).toBe('这次接着说')
    } finally {
      vi.useRealTimers()
    }
  })

  it('草稿:发送成功后删掉键(不会留下「[草稿] 」前缀)', async () => {
    const { w } = await mountPage()
    await flushPromises()

    vi.useFakeTimers()
    try {
      await w.find('input[type="text"]').setValue('马上发出去')
      vi.advanceTimersByTime(300)
      expect(localStorage.getItem('chat_draft:u8')).toBe('马上发出去')
    } finally {
      vi.useRealTimers()
    }

    await w.find('.chat__send').trigger('click')
    await flushPromises()

    expect(localStorage.getItem('chat_draft:u8')).toBeNull()
    expect((w.find('input[type="text"]').element as HTMLInputElement).value).toBe('')
  })

  it('草稿:清空输入框等于删掉草稿', async () => {
    saveDraft('u8', '算了不说了')
    const { w } = await mountPage()
    await flushPromises()

    vi.useFakeTimers()
    try {
      await w.find('input[type="text"]').setValue('')
      vi.advanceTimersByTime(300)
      expect(localStorage.getItem('chat_draft:u8')).toBeNull()
    } finally {
      vi.useRealTimers()
    }
  })

  it('离开聊天页立刻把没落盘的草稿写下来(不能丢最后几个字)', async () => {
    const { w } = await mountPage()
    await flushPromises()

    await w.find('input[type="text"]').setValue('打了一半就走')
    w.unmount()

    expect(localStorage.getItem('chat_draft:u8')).toBe('打了一半就走')
  })
})
