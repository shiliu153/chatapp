import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatStore } from '@/stores/chat'
import { setImClientFactory } from '@/im/client'
import { sessionEvents } from '@/api/session-events'
import { server } from '../support/server'
import type { ChatMessage, ImClient, ImConversation, ImEvent } from '@/im/types'

/**
 * 跨端同步帧(多端在线 K-3)在 store 里的落点:
 * 1) `selfRead` → 该会话未读清零,**`peerReadSeq` 一律不动**(那是「对方读我」);
 * 2) `conversationDeleted` → 从会话列表移除,当前正打开的会话要清掉 activePeerId。
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
    fetchConversations: vi.fn(async () => [
      conversation({ peerId: 'u8', unreadCount: 3, peerReadSeq: 7 }),
      conversation({ peerId: 'u9', unreadCount: 1 }),
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
    deleteConversation: vi.fn(async () => {}),
  }
  return { client, emit: (event: ImEvent) => listener?.(event) }
}

describe('跨端同步帧:store(多端在线 K-3)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionEvents._reset()
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

  it('selfRead 只清未读,不动 peerReadSeq(那是「对方读我」)', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()

    await store.loadConversations()
    expect(store.conversations.find((item) => item.peerId === 'u8')?.unreadCount).toBe(3)
    expect(store.unreadTotal).toBe(4)

    emit({ type: 'selfRead', peerId: 'u8', seq: 42 })

    expect(store.conversations.find((item) => item.peerId === 'u8')?.unreadCount).toBe(0)
    expect(store.unreadTotal).toBe(1)
    // 关键断言:跨端已读**不是**对端已读,peerReadSeq 保持服务端给的 7
    expect(store.peerReadSeq.u8).toBeUndefined()
    expect(store.conversations.find((item) => item.peerId === 'u8')?.peerReadSeq).toBe(7)
  })

  it('conversationDeleted 从列表移除该会话并清掉本地消息', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()

    await store.loadConversations()
    await store.openConversation('u8')
    expect(store.conversations.map((item) => item.peerId)).toEqual(['u8', 'u9'])
    expect(store.messagesOf('u8').length).toBeGreaterThan(0)

    emit({ type: 'conversationDeleted', peerId: 'u8' })

    expect(store.conversations.map((item) => item.peerId)).toEqual(['u9'])
    expect(store.messagesOf('u8')).toEqual([])
  })
})
