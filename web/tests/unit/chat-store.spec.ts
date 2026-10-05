import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatStore } from '@/stores/chat'
import { setImClientFactory } from '@/im/client'
import { sessionEvents } from '@/api/session-events'
import type { ChatMessage, ImClient, ImConversation, ImEvent } from '@/im/types'

const msg = (overrides: Partial<ChatMessage>): ChatMessage => ({
  msgId: 'm0',
  peerId: 'u8',
  isSelf: false,
  timestamp: 1,
  kind: 'text' as never,
  text: '',
  isPending: false,
  isFailed: false,
  imageUrl: null,
  imageLargeUrl: null,
  ...overrides,
})

function fakeClient() {
  let listener: ((event: ImEvent) => void) | null = null
  const conversations: ImConversation[] = [
    { peerId: 'u8', unreadCount: 2, showName: '小雨', faceUrl: null, lastMessage: null },
    { peerId: 'system_notice', unreadCount: 1, showName: '系统通知', faceUrl: null, lastMessage: null },
  ]
  const client = {
    onEvent: (fn: (event: ImEvent) => void) => {
      listener = fn
    },
    init: vi.fn(),
    login: vi.fn(async () => {}),
    logout: vi.fn(async () => {}),
    fetchConversations: vi.fn(async () => conversations),
    fetchHistory: vi.fn(async () => [] as ChatMessage[]),
    sendText: vi.fn(async (peerId: string, text: string) => msg({ msgId: 'm1', peerId, isSelf: true, text })),
    sendImage: vi.fn(async (peerId: string) => msg({ msgId: 'm2', peerId, isSelf: true })),
    deleteMessage: vi.fn(async () => {}),
    markConversationRead: vi.fn(async () => {}),
    deleteConversation: vi.fn(async () => {}),
  }
  return { client, emit: (event: ImEvent) => listener?.(event) }
}

describe('chat store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionEvents._reset()
  })

  it('会话列表:未读合计,系统通知置顶', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()

    await store.loadConversations()

    expect(store.conversations[0].peerId).toBe('system_notice') // 置顶
    expect(store.unreadTotal).toBe(3)
  })

  it('新消息到达时插入对应会话并累加未读', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    await store.loadConversations()

    emit({
      type: 'newMessage',
      message: msg({ msgId: 'm9', peerId: 'u9', text: '在吗', timestamp: 2 }),
    })

    expect(store.messagesOf('u9').map((m) => m.msgId)).toEqual(['m9'])
  })

  it('多端被顶 → 触发会话失效(全屏提示)', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const expired = vi.fn()
    sessionEvents.onKickedOffline(expired)
    useChatStore()

    emit({ type: 'kickedOffline', reason: 'multiDevice' })

    expect(expired).toHaveBeenCalledTimes(1)
  })

  it('同端第二个标签页被顶 → 不清凭证,只重连(否则两个标签页一起掉线)', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const expired = vi.fn()
    sessionEvents.onKickedOffline(expired)
    const store = useChatStore()

    emit({ type: 'kickedOffline', reason: 'multiAccount' })

    expect(expired).not.toHaveBeenCalled()
    expect(store.status).toBe('reconnecting')
  })

  it('打开会话即清未读', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    await store.loadConversations()

    await store.openConversation('u8')

    expect(client.markConversationRead).toHaveBeenCalledWith('u8')
    expect(store.conversations.find((c) => c.peerId === 'u8')?.unreadCount).toBe(0)
  })
})
