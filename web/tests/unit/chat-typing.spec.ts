import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatStore } from '@/stores/chat'
import { setImClientFactory } from '@/im/client'
import { server } from '../support/server'
import type { ChatMessage, ImClient, ImConversation, ImEvent } from '@/im/types'

/**
 * 输入中状态(批次 L-1)在 store 里的两条核心行为:
 * 1) **接收端 5 秒过期**:typing 是可丢信号,服务端不落库也不补发,「对端停手」
 *    只能靠客户端超时 —— 不超时的话「正在输入…」会一直挂着;
 * 2) **发送端 3 秒节流**:首次输入立即发,之后 3 秒内最多一次(服务端另有
 *    1 次 / 2 秒的令牌桶兜底,客户端这层只省流量)。
 *
 * 时间一律用 `vi.useFakeTimers()` 推:定时器就是这两条行为的全部实现。
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
  ...overrides,
})

function fakeClient() {
  let listener: ((event: ImEvent) => void) | null = null
  const sendTyping = vi.fn(async (_peerId: string) => {})
  const client = {
    onEvent: (fn: (event: ImEvent) => void) => {
      listener = fn
    },
    init: vi.fn(),
    login: vi.fn(async () => {}),
    logout: vi.fn(async () => {}),
    fetchConversations: vi.fn(async () => [
      conversation({ peerId: 'u8' }),
      conversation({ peerId: 'u9' }),
    ]),
    fetchHistory: vi.fn(async () => [msg({ msgId: 'm1', seq: 1 })]),
    searchMessages: vi.fn(async () => ({ items: [], hasMore: false })),
    capabilities: { image: true, search: true, voice: true, readReceipt: true },
    sendText: vi.fn(async (peerId: string, text: string) => msg({ msgId: 'm1', peerId, text })),
    sendImage: vi.fn(async (peerId: string) => msg({ msgId: 'm2', peerId })),
    sendVoice: vi.fn(async (peerId: string) => msg({ msgId: 'm3', peerId })),
    sendSticker: vi.fn(async (peerId: string) => msg({ msgId: 'm4', peerId })),
    deleteMessage: vi.fn(async () => {}),
    revokeMessage: vi.fn(async () => {}),
    markConversationRead: vi.fn(async () => {}),
    sendTyping,
    deleteConversation: vi.fn(async () => {}),
  }
  return { client, sendTyping, emit: (event: ImEvent) => listener?.(event) }
}

describe('输入中状态:store(批次 L-1)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
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

  afterEach(() => {
    vi.useRealTimers()
  })

  it('收到 typing 后 5 秒内为真,之后自动变假', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    await store.openConversation('u8')
    expect(store.peerTyping.u8).toBeUndefined()

    emit({ type: 'typing', peerId: 'u8' })
    expect(store.peerTyping.u8).toBe(true)

    // 4 秒时还在:窗口是 5 秒
    vi.advanceTimersByTime(4000)
    expect(store.peerTyping.u8).toBe(true)

    // 累计 6 秒:对端没发新帧 → 自动清掉(不能一直挂着「正在输入…」)
    vi.advanceTimersByTime(2000)
    expect(store.peerTyping.u8).toBeUndefined()
  })

  it('连续收帧会续期:最后一帧后 5 秒才变假', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    await store.openConversation('u8')

    emit({ type: 'typing', peerId: 'u8' })
    vi.advanceTimersByTime(3000)
    emit({ type: 'typing', peerId: 'u8' })
    vi.advanceTimersByTime(4000)
    expect(store.peerTyping.u8).toBe(true)

    vi.advanceTimersByTime(2000)
    expect(store.peerTyping.u8).toBeUndefined()
  })

  it('非当前会话的 typing 不点亮,切会话时清掉上一个会话的状态', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    await store.openConversation('u8')

    // u9 的帧不该点亮 u8 的提示
    emit({ type: 'typing', peerId: 'u9' })
    expect(store.peerTyping.u9).toBeUndefined()

    emit({ type: 'typing', peerId: 'u8' })
    expect(store.peerTyping.u8).toBe(true)

    // 切到 u9:u8 的瞬时状态必须立刻清掉,不能带过去
    await store.openConversation('u9')
    expect(store.peerTyping.u8).toBeUndefined()
  })

  it('3 秒节流:连续输入只发一次,冷却结束再发', async () => {
    const { client, sendTyping } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()

    store.notifyTyping('u8') // 首次:立即发
    store.notifyTyping('u8') // 3 秒内:不发
    expect(sendTyping).toHaveBeenCalledTimes(1)
    expect(sendTyping).toHaveBeenLastCalledWith('u8')

    vi.advanceTimersByTime(3000)
    store.notifyTyping('u8') // 冷却结束:再发
    expect(sendTyping).toHaveBeenCalledTimes(2)
  })

  it('clearPeerTyping 立即清掉(离开聊天页用)', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    await store.openConversation('u8')

    emit({ type: 'typing', peerId: 'u8' })
    expect(store.peerTyping.u8).toBe(true)

    store.clearPeerTyping('u8')
    expect(store.peerTyping.u8).toBeUndefined()

    // 定时器也一起清掉了:再推 5 秒也不会有残留状态
    vi.advanceTimersByTime(6000)
    expect(store.peerTyping.u8).toBeUndefined()
  })
})
