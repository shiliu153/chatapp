import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatStore } from '@/stores/chat'
import { setImClientFactory } from '@/im/client'
import { sessionEvents } from '@/api/session-events'
import MessageBubble from '@/features/chat/MessageBubble.vue'
import { server } from '../support/server'
import type { ChatMessage, ImClient, ImConversation, ImEvent } from '@/im/types'

/**
 * 已读回执的两条链路(与 App 侧对齐):
 * 1) 实时:下行 `peerRead` 事件推进 store 里的 `peerReadSeq`(**只增不减**);
 * 2) 补拉:打开会话时用会话列表的 `peer_read_seq` 初始化。
 * 另外覆盖「后端不支持(腾讯分支)不渲染已读」。
 */

const msg = (overrides: Partial<ChatMessage>): ChatMessage => ({
  msgId: 'm0',
  peerId: 'u8',
  isSelf: true,
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

const conversation = (overrides: Partial<ImConversation>): ImConversation => ({
  peerId: 'u8',
  unreadCount: 0,
  showName: '小雨',
  faceUrl: null,
  lastMessage: null,
  peerReadSeq: 0,
  ...overrides,
})

function fakeClient() {
  let listener: ((event: ImEvent) => void) | null = null
  const client = {
    onEvent: (fn: (event: ImEvent) => void) => {
      listener = fn
    },
    init: vi.fn(),
    login: vi.fn(async () => {}),
    logout: vi.fn(async () => {}),
    fetchConversations: vi.fn(async () => [conversation({ peerId: 'u8', peerReadSeq: 3 })]),
    fetchHistory: vi.fn(async () => [msg({ msgId: 'm1', seq: 1 }), msg({ msgId: 'm2', seq: 2 })]),
    searchMessages: vi.fn(async () => ({ items: [], hasMore: false })),
    capabilities: { image: true, search: true, voice: true, readReceipt: true },
    sendText: vi.fn(async (peerId: string, text: string) => msg({ msgId: 'm1', peerId, text })),
    sendImage: vi.fn(async (peerId: string) => msg({ msgId: 'm2', peerId })),
    sendVoice: vi.fn(async (peerId: string) => msg({ msgId: 'm3', peerId, kind: 'voice' as never })),
    deleteMessage: vi.fn(async () => {}),
    revokeMessage: vi.fn(async () => {}),
    markConversationRead: vi.fn(async () => {}),
    deleteConversation: vi.fn(async () => {}),
  }
  return { client, emit: (event: ImEvent) => listener?.(event) }
}

describe('已读回执:store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionEvents._reset()
    server.use(
      mswHttp.post('/api/v1/im/user_sig', () =>
        HttpResponse.json({
          user_sig: 'sig',
          sdkappid: '1600161711',
          im_user_id: 'u41',
          expire: 1791189272,
        }),
      ),
    )
  })

  it('下行 peerRead 推进已读位置,旧值不回退', () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()

    store.connect()
    emit({ type: 'peerRead', peerId: 'u8', seq: 2 })
    expect(store.peerReadSeq.u8).toBe(2)

    // 乱序到达的旧帧不能把「已读」推回「未读」
    emit({ type: 'peerRead', peerId: 'u8', seq: 1 })
    expect(store.peerReadSeq.u8).toBe(2)

    emit({ type: 'peerRead', peerId: 'u8', seq: 5 })
    expect(store.peerReadSeq.u8).toBe(5)
  })

  it('打开会话时从会话列表补拉 peer_read_seq(断线期间的已读靠它)', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()

    await store.openConversation('u8')

    expect(client.fetchConversations).toHaveBeenCalled()
    expect(store.peerReadSeq.u8).toBe(3)
    // 已读回执与未读数是两条链路:打开会话仍然照旧清未读
    expect(client.markConversationRead).toHaveBeenCalledWith('u8')
  })

  it('close() 清掉已读位置(换账号不能带着上一个人的状态)', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()

    store.connect()
    emit({ type: 'peerRead', peerId: 'u8', seq: 4 })
    expect(store.peerReadSeq.u8).toBe(4)

    await store.close()
    expect(store.peerReadSeq).toEqual({})
  })
})

describe('已读回执:气泡', () => {
  it('支持已读时,我方已读消息显示「已读」', () => {
    const w = mount(MessageBubble, {
      props: { message: msg({ seq: 2 }), isRead: true, readReceiptEnabled: true },
    })
    expect(w.find('[data-testid="chat-read"]').exists()).toBe(true)
  })

  it('后端不支持已读回执(腾讯分支)时不显示「已读」', () => {
    const w = mount(MessageBubble, {
      props: { message: msg({ seq: 2 }), isRead: true, readReceiptEnabled: false },
    })
    expect(w.find('[data-testid="chat-read"]').exists()).toBe(false)
  })

  it('发送中/失败时不显示「已读」', () => {
    const pending = mount(MessageBubble, {
      props: {
        message: msg({ seq: 2, isPending: true }),
        isRead: true,
        readReceiptEnabled: true,
      },
    })
    expect(pending.find('[data-testid="chat-read"]').exists()).toBe(false)
    expect(pending.text()).toContain('发送中')

    const failed = mount(MessageBubble, {
      props: {
        message: msg({ seq: 2, isFailed: true }),
        isRead: true,
        readReceiptEnabled: true,
      },
    })
    expect(failed.find('[data-testid="chat-read"]').exists()).toBe(false)
    expect(failed.text()).toContain('重发')
  })

  it('未读的我方消息不显示任何状态词(微信口径)', () => {
    const w = mount(MessageBubble, {
      props: { message: msg({ seq: 2 }), isRead: false, readReceiptEnabled: true },
    })
    expect(w.find('[data-testid="chat-read"]').exists()).toBe(false)
    expect(w.text()).not.toContain('未读')
  })
})
