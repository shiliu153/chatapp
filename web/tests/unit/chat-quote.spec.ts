import { defineComponent, ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatStore } from '@/stores/chat'
import { setImClientFactory } from '@/im/client'
import { messageFromJson } from '@/im/self/map'
import MessageBubble from '@/features/chat/MessageBubble.vue'
import MessageMenu from '@/features/chat/MessageMenu.vue'
import { canQuote, quoteSummaryOf } from '@/features/chat/quote'
import { server } from '../support/server'
import type { ChatMessage, ImClient, ImConversation, ImEvent } from '@/im/types'

/**
 * 引用回复(批次 L-2)在 Web 侧的三条核心行为:
 * 1) **上行只带 id**:设了引用目标后 `sendText` 带 `ref_msg_id`,发完引用条自动清空;
 * 2) **下行快照照原样渲染**:气泡上方显示服务端摘要,`revoked` 时只显示「消息已撤回」;
 * 3) **没有引用时整块不渲染**:老消息 / 老服务端不会多出一个空框。
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

const msg = (overrides: Partial<ChatMessage>): ChatMessage => ({
  msgId: 'm0',
  peerId: 'u8',
  isSelf: false,
  seq: 0,
  timestamp: 1,
  kind: 'text' as never,
  text: '',
  senderName: '',
  senderAvatar: null,
  isPending: false,
  isFailed: false,
  imageUrl: null,
  imageLargeUrl: null,
  isRevoked: false,
  ref: null,
  ...overrides,
})

function fakeClient() {
  let listener: ((event: ImEvent) => void) | null = null
  const sendText = vi.fn(async (peerId: string, text: string) =>
    msg({ msgId: 'm1', peerId, text, isSelf: true }),
  )
  const client = {
    onEvent: (fn: (event: ImEvent) => void) => {
      listener = fn
    },
    init: vi.fn(),
    login: vi.fn(async () => {}),
    logout: vi.fn(async () => {}),
    fetchConversations: vi.fn(async () => [conversation({ peerId: 'u8' })]),
    fetchHistory: vi.fn(async () => []),
    searchMessages: vi.fn(async () => ({ items: [], hasMore: false })),
    capabilities: { image: true, search: true, voice: true, readReceipt: true },
    sendText,
    sendImage: vi.fn(async (peerId: string) => msg({ msgId: 'm2', peerId, isSelf: true })),
    sendVoice: vi.fn(async (peerId: string) => msg({ msgId: 'm3', peerId, isSelf: true })),
    sendSticker: vi.fn(async (peerId: string) => msg({ msgId: 'm4', peerId, isSelf: true })),
    deleteMessage: vi.fn(async () => {}),
    revokeMessage: vi.fn(async () => {}),
    markConversationRead: vi.fn(async () => {}),
    sendTyping: vi.fn(async () => {}),
    deleteConversation: vi.fn(async () => {}),
  }
  return { client, sendText, emit: (event: ImEvent) => listener?.(event) }
}

describe('引用回复:解析与规则(批次 L-2)', () => {
  it('带 ref 的下行帧解析成 ChatMessage.ref', () => {
    const parsed = messageFromJson(
      {
        msg_id: '900128',
        seq: 46,
        from: 'u8',
        to: 'u41',
        kind: 'text',
        ts: 1720000000004,
        revoked: false,
        text: '好,六点',
        ref: {
          msg_id: 900120,
          from: 'u41',
          kind: 'text',
          text: '今晚吃饭?',
          revoked: false,
        },
      },
      'u41',
    )
    expect(parsed.ref).toEqual({
      msgId: 900120,
      from: 'u41',
      kind: 'text',
      text: '今晚吃饭?',
      revoked: false,
    })
  })

  it('没有 ref 键时是 null(不能渲染出空引用块)', () => {
    const parsed = messageFromJson({ msg_id: '1', from: 'u8', to: 'u41', kind: 'text' }, 'u41')
    expect(parsed.ref).toBeNull()
  })

  it('canQuote:灰条 / 已撤回 / 发送中 / 本地 id 都不能引用', () => {
    expect(canQuote(msg({ msgId: '900124' }))).toBe(true)
    expect(canQuote(msg({ msgId: '900124', isRevoked: true }))).toBe(false)
    expect(canQuote(msg({ msgId: '900124', isPending: true }))).toBe(false)
    expect(canQuote(msg({ msgId: '900124', isFailed: true }))).toBe(false)
    expect(canQuote(msg({ msgId: 'local-1' }))).toBe(false)
    expect(canQuote(msg({ msgId: '900124', kind: 'matchNotice' as never }))).toBe(false)

    expect(quoteSummaryOf(msg({ text: '今晚吃饭?' }))).toBe('今晚吃饭?')
    expect(quoteSummaryOf(msg({ kind: 'image' as never }))).toBe('[图片]')
    expect(quoteSummaryOf(msg({ kind: 'voice' as never }))).toBe('[语音]')
    expect(quoteSummaryOf(msg({ kind: 'sticker' as never }))).toBe('[贴纸]')
  })
})

describe('引用回复:store(批次 L-2)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    server.use(
      mswHttp.post('/api/v1/im/user_sig', () =>
        HttpResponse.json({
          backend: 'self',
          token: 'tok-41',
          ws_url: 'ws://test/im/ws',
          http_url: 'http://test/im/api',
          im_user_id: 'u41',
          expire: 1791189272,
        }),
      ),
    )
  })

  it('设了引用目标后 sendText 上行带 ref_msg_id,发完清空引用条', async () => {
    const { client, sendText } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()

    store.setQuoteTarget({ msgId: 900124, from: 'u8', text: '今晚吃饭?' })
    expect(store.quoteTarget).toEqual({ msgId: 900124, from: 'u8', text: '今晚吃饭?' })

    const sent = await store.sendText('u8', '好,六点')
    expect(sendText).toHaveBeenCalledWith('u8', '好,六点', 900124)
    // 上行只有 id,回执里没有快照 → 本地补一份,刚发出的气泡上也带引用块
    expect(sent.ref).toEqual({
      msgId: 900124,
      from: 'u8',
      kind: 'text',
      text: '今晚吃饭?',
      revoked: false,
    })
    // 引用条用完即清:下一条消息不该莫名其妙继续引用
    expect(store.quoteTarget).toBeNull()
  })

  it('没有引用目标时 sendText 不带 ref_msg_id', async () => {
    const { client, sendText } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()

    const sent = await store.sendText('u8', '随便说一句')
    expect(sendText).toHaveBeenCalledWith('u8', '随便说一句', undefined)
    expect(sent.ref).toBeNull()
  })

  it('clearQuoteTarget 立即取消引用', () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()

    store.setQuoteTarget({ msgId: 900124, from: 'u8', text: '今晚吃饭?' })
    store.clearQuoteTarget()
    expect(store.quoteTarget).toBeNull()
  })

  it('切会话时清掉引用目标(不能带到下一个会话)', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()

    await store.openConversation('u8')
    store.setQuoteTarget({ msgId: 900124, from: 'u8', text: '今晚吃饭?' })
    await store.openConversation('u9')
    expect(store.quoteTarget).toBeNull()
  })
})

describe('引用回复:气泡渲染(批次 L-2)', () => {
  it('气泡上方渲染服务端摘要,点击发出 jumpQuote', async () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: msg({
          msgId: '900200',
          text: '好,六点',
          ref: {
            msgId: 900124,
            from: 'u8',
            kind: 'text',
            text: '今晚吃饭?',
            revoked: false,
          },
        }),
        peerName: '小雨',
      },
    })
    expect(wrapper.find('[data-testid="quote-block"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('今晚吃饭?')
    expect(wrapper.text()).toContain('好,六点')

    await wrapper.find('[data-testid="quote-block"]').trigger('click')
    expect(wrapper.emitted('jumpQuote')).toEqual([[900124]])
  })

  it('revoked 的引用渲染成「消息已撤回」', () => {
    const wrapper = mount(MessageBubble, {
      props: {
        message: msg({
          msgId: '900201',
          text: '你刚才说啥',
          ref: { msgId: 900125, from: 'u8', kind: 'text', text: '', revoked: true },
        }),
      },
    })
    expect(wrapper.find('[data-testid="quote-revoked"]').text()).toBe('消息已撤回')
  })

  it('没有引用时整块不渲染(老消息不受影响)', () => {
    const wrapper = mount(MessageBubble, {
      props: { message: msg({ msgId: '900202', text: '普通消息' }) },
    })
    expect(wrapper.find('[data-testid="quote-block"]').exists()).toBe(false)
  })
})

/**
 * 菜单**真实点击链路**回归(验收现场抓到的 bug)。
 *
 * 曾经的实现用 `window.addEventListener('mousedown', () => emit('close'))` 做「点别处关闭」。
 * 用户点菜单项时事件顺序是 `mousedown → mouseup → click`:mousedown 先把菜单关掉
 * (父组件 `menu.value = null` → 组件卸载),随后的 click 落在已卸载的节点上,
 * `onMenuAction` 根本不会被调用 —— 于是「引用 / 复制 / 撤回 / 删除」**全都点不动**。
 *
 * 所以这条用例必须走真实的事件序列(`mousedown` 再 `click`),只调 store 是抓不到的。
 */
describe('引用回复:菜单真实点击链路(批次 L-2 验收回归)', () => {
  /** 让出一拍,等菜单挂上「点别处关闭」的监听(setTimeout 0)。 */
  async function nextTickTask(): Promise<void> {
    await new Promise((resolve) => setTimeout(resolve, 0))
  }

  /** 一个最小宿主:负责开菜单、收 action、点别处关闭(与 ChatPage 同构)。 */
  const Host = defineComponent({
    components: { MessageMenu },
    setup() {
      const open = ref(false)
      const actions: string[] = []
      const target = msg({ msgId: '900124', text: '今晚吃饭?' })
      return {
        open,
        actions,
        target,
        show() {
          open.value = true
        },
        onAction(action: string) {
          actions.push(action)
          open.value = false
        },
        onClose() {
          open.value = false
        },
      }
    },
    template: `
      <div>
        <button data-testid="open" @click="show">⋯</button>
        <MessageMenu
          v-if="open"
          :message="target"
          :x="10"
          :y="10"
          @action="onAction"
          @close="onClose"
        />
      </div>
    `,
  })

  it('点「引用」真的会触发 action(mousedown → click 的真实序列)', async () => {
    // attachTo:必须挂到 document 上,否则事件冒泡到不了 window,
    // 「点别处关闭」的监听根本不会被触发 —— 那样这条用例就测不到真 bug 了。
    const wrapper = mount(Host, { attachTo: document.body })
    await wrapper.find('[data-testid="open"]').trigger('click')
    await nextTickTask()

    const item = wrapper.find('[data-testid="menu-quote"]')
    expect(item.exists()).toBe(true)

    // 真实用户操作:mousedown 先到,click 后到。
    await item.trigger('mousedown')
    // 关键断言:按下鼠标时菜单**必须还开着**。旧实现用 window mousedown 关菜单,
    // 按下就卸载了组件,随后真实浏览器里的 click 落在已经不存在的节点上 → 回调永不执行
    // (jsdom 的 trigger 仍能派发到游离节点,所以必须在这里断言「还开着」,不能只看 actions)。
    expect(wrapper.find('[data-testid="menu-quote"]').exists()).toBe(true)

    await item.trigger('click')
    expect(wrapper.vm.actions).toEqual(['quote'])
    wrapper.unmount()
  })

  it('点菜单外面仍然会关闭菜单', async () => {
    const wrapper = mount(Host, { attachTo: document.body })
    await wrapper.find('[data-testid="open"]').trigger('click')
    await nextTickTask()
    expect(wrapper.find('[data-testid="menu-quote"]').exists()).toBe(true)

    document.body.click()
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid="menu-quote"]').exists()).toBe(false)
    wrapper.unmount()
  })
})
