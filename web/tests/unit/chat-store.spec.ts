import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatStore } from '@/stores/chat'
import { setImClientFactory } from '@/im/client'
import { sessionEvents } from '@/api/session-events'
import { server } from '../support/server'
import type { ChatMessage, ImClient, ImConversation, ImEvent } from '@/im/types'

const msg = (overrides: Partial<ChatMessage>): ChatMessage => ({
  msgId: 'm0',
  peerId: 'u8',
  isSelf: false,
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

  it('先连上再拉会话(否则会用 SDKAppID=0 建实例 → No SDKAppID)', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()

    await store.loadConversations()

    expect(client.init).toHaveBeenCalledWith(1600161711)
    expect(client.login).toHaveBeenCalled()
    expect((client.init as unknown as { mock: { invocationCallOrder: number[] } }).mock.invocationCallOrder[0])
      .toBeLessThan(
        (client.fetchConversations as unknown as { mock: { invocationCallOrder: number[] } }).mock
          .invocationCallOrder[0],
      )
  })

  it('服务端会话摘要残缺时不覆盖本地已知的昵称与最后一条消息', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()

    // 1) 先收到一条真实消息(带发送者昵称与时间)
    emit({
      type: 'newMessage',
      message: msg({
        msgId: 'm9',
        peerId: 'u18',
        text: '你好呀',
        timestamp: 1791189500000,
        senderName: '婉婷18',
      }),
    })
    expect(store.conversations[0].showName).toBe('婉婷18')

    // 2) 服务端随后返回的会话摘要只有正文,昵称/时间/方向都空(真机实测)
    client.fetchConversations = vi.fn(async () => [
      {
        peerId: 'u18',
        unreadCount: 4,
        showName: '',
        faceUrl: null,
        lastMessage: msg({ msgId: 'm9', peerId: '', text: '你好呀', timestamp: 0 }),
      },
    ])
    await store.loadConversations()

    expect(store.conversations[0].showName).toBe('婉婷18')
    expect(store.conversations[0].lastMessage?.timestamp).toBe(1791189500000)
    expect(store.conversations[0].unreadCount).toBe(4) // 服务端更权威的字段仍然生效
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

  it('同端第二个标签页被顶 → 不清凭证、不自动重连(否则两个标签页会互相踢成风暴)', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const expired = vi.fn()
    sessionEvents.onKickedOffline(expired)
    const store = useChatStore()

    emit({ type: 'kickedOffline', reason: 'multiAccount' })

    expect(expired).not.toHaveBeenCalled() // 凭证必须留着(否则所有标签页一起掉线)
    expect(store.status).toBe('inactive')
    expect(client.login).not.toHaveBeenCalled() // 关键:不自动抢回来
  })

  it('被同端顶掉后可以手动接管(reconnect 才会真的重连)', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    emit({ type: 'kickedOffline', reason: 'multiAccount' })

    await store.reconnect()

    expect(client.login).toHaveBeenCalledTimes(1)
    expect(store.status).toBe('ready')
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
