import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatStore } from '@/stores/chat'
import { setImClientFactory } from '@/im/client'
import { messageFromJson } from '@/im/self/map'
import MessageBubble from '@/features/chat/MessageBubble.vue'
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
