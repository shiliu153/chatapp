import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError } from '@/api/error'
import { setImClientFactory } from '@/im/client'
import { useChatStore } from '@/stores/chat'
import { sessionEvents } from '@/api/session-events'
import { server } from '../support/server'
import type {
  ChatMessage,
  ImClient,
  ImConversation,
  ImConversationFlags,
  ImConversationFlagsResult,
  ImEvent,
} from '@/im/types'

/**
 * 会话偏好(批次 N)在 store 里的落点:
 * 1) 写入只带要改的那一项,成功后按**服务端回读的真值**更新本地;
 * 2) 分组顺序**以服务端为准** —— 置顶组在前,组内不按本地「最后消息时间」重排;
 * 3) 失败(会话不存在 `40401`)时本地状态原样保留,错误上抛给页面提示。
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

/**
 * 假 IM 客户端。`setConversationFlags` 会**像服务端一样**改自己的列表并重排
 * (置顶的挪到最前),这样 store 的重拉才能验证「顺序来自服务端」。
 */
function fakeClient(initial: ImConversation[]) {
  let listener: ((event: ImEvent) => void) | null = null
  const state = { conversations: initial }
  const client = {
    onEvent: (fn: (event: ImEvent) => void) => {
      listener = fn
    },
    init: vi.fn(async () => {}),
    login: vi.fn(async () => {}),
    logout: vi.fn(async () => {}),
    fetchConversations: vi.fn(async () => state.conversations.map((item) => ({ ...item }))),
    fetchHistory: vi.fn(async () => [] as ChatMessage[]),
    searchMessages: vi.fn(async () => ({ items: [], hasMore: false })),
    capabilities: { image: true, search: true, voice: true, readReceipt: true },
    sendText: vi.fn(async (peerId: string, text: string) => msg({ peerId, isSelf: true, text })),
    sendImage: vi.fn(async (peerId: string) => msg({ peerId, isSelf: true })),
    sendVoice: vi.fn(async (peerId: string) => msg({ peerId, isSelf: true })),
    sendSticker: vi.fn(async (peerId: string) => msg({ peerId, isSelf: true })),
    deleteMessage: vi.fn(async () => {}),
    revokeMessage: vi.fn(async () => {}),
    markConversationRead: vi.fn(async () => {}),
    deleteConversation: vi.fn(async () => {}),
    setConversationFlags: vi.fn(
      async (peerId: string, flags: ImConversationFlags): Promise<ImConversationFlagsResult> => {
        const target = state.conversations.find((item) => item.peerId === peerId)
        if (!target) throw new ApiError(40401, '会话不存在', undefined, 404)
        const result: ImConversationFlagsResult = {
          pinned: flags.pinned ?? target.pinned,
          muted: flags.muted ?? target.muted,
        }
        target.pinned = result.pinned
        target.muted = result.muted
        if (flags.pinned === true) {
          // 服务端:置顶组在前,组内按置顶时间倒序 —— 刚置顶的排最前
          state.conversations = [target, ...state.conversations.filter((item) => item !== target)]
        }
        return result
      },
    ),
  }
  return {
    client,
    state,
    emit: (event: ImEvent) => listener?.(event),
  }
}

function useStore() {
  return useChatStore()
}

describe('chat store:会话置顶 / 免打扰', () => {
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

  it('置顶只上行 pinned 一项,并按服务端真值更新本地', async () => {
    const { client, emit } = fakeClient([
      conversation({ peerId: 'u8' }),
      conversation({ peerId: 'u9' }),
    ])
    setImClientFactory(() => client as unknown as ImClient)
    const store = useStore()
    await store.loadConversations()
    emit({ type: 'ready' })

    await store.setConversationFlags('u9', { pinned: true })

    expect(client.setConversationFlags).toHaveBeenCalledWith('u9', { pinned: true })
    expect(store.conversations.find((item) => item.peerId === 'u9')?.pinned).toBe(true)
    expect(store.conversations.find((item) => item.peerId === 'u9')?.muted).toBe(false)
  })

  it('置顶后分组变化:顺序来自服务端(刚置顶的进置顶组最前)', async () => {
    const { client, emit } = fakeClient([
      conversation({ peerId: 'u8' }),
      conversation({ peerId: 'u9' }),
    ])
    setImClientFactory(() => client as unknown as ImClient)
    const store = useStore()
    await store.loadConversations()
    emit({ type: 'ready' })

    await store.setConversationFlags('u9', { pinned: true })

    expect(store.pinnedConversations.map((item) => item.peerId)).toEqual(['u9'])
    expect(store.otherConversations.map((item) => item.peerId)).toEqual(['u8'])
    expect(store.conversations.map((item) => item.peerId)).toEqual(['u9', 'u8'])
  })

  it('置顶组内不按本地「最后消息时间」重排(以服务端顺序为准)', async () => {
    // 服务端顺序是 [u9, u8];u8 的最后消息时间更新。客户端**不能**因此把 u8 提到前面。
    const { client, emit } = fakeClient([
      conversation({ peerId: 'u9', pinned: true, lastMessage: msg({ peerId: 'u9', timestamp: 100 }) }),
      conversation({ peerId: 'u8', pinned: true, lastMessage: msg({ peerId: 'u8', timestamp: 900 }) }),
    ])
    setImClientFactory(() => client as unknown as ImClient)
    const store = useStore()
    await store.loadConversations()
    emit({ type: 'ready' })

    expect(store.conversations.map((item) => item.peerId)).toEqual(['u9', 'u8'])
  })

  it('免打扰只改 muted,不影响置顶与未读数(服务端不改统计)', async () => {
    const { client, emit } = fakeClient([
      conversation({ peerId: 'u8', unreadCount: 3 }),
    ])
    setImClientFactory(() => client as unknown as ImClient)
    const store = useStore()
    await store.loadConversations()
    emit({ type: 'ready' })

    await store.setConversationFlags('u8', { muted: true })

    const target = store.conversations.find((item) => item.peerId === 'u8')
    expect(target?.muted).toBe(true)
    expect(target?.pinned).toBe(false)
    expect(target?.unreadCount).toBe(3)
  })

  it('会话不存在(40401):本地状态原样保留,错误上抛', async () => {
    const { client, emit } = fakeClient([conversation({ peerId: 'u8' })])
    setImClientFactory(() => client as unknown as ImClient)
    const store = useStore()
    await store.loadConversations()
    emit({ type: 'ready' })

    await expect(store.setConversationFlags('u99', { pinned: true })).rejects.toBeInstanceOf(
      ApiError,
    )
    expect(store.conversations.find((item) => item.peerId === 'u8')?.pinned).toBe(false)
    expect(store.conversations.map((item) => item.peerId)).toEqual(['u8'])
  })

  it('删除会话:行从列表移除,本地消息缓存一起丢掉', async () => {
    const { client, emit } = fakeClient([
      conversation({ peerId: 'u8' }),
      conversation({ peerId: 'u9' }),
    ])
    setImClientFactory(() => client as unknown as ImClient)
    const store = useStore()
    await store.loadConversations()
    emit({ type: 'ready' })

    await store.deleteConversation('u8')

    expect(client.deleteConversation).toHaveBeenCalledWith('u8')
    expect(store.conversations.map((item) => item.peerId)).toEqual(['u9'])
  })

  it('重拉列表失败不影响写入成功', async () => {
    const { client, emit } = fakeClient([conversation({ peerId: 'u8' })])
    setImClientFactory(() => client as unknown as ImClient)
    const store = useStore()
    await store.loadConversations()
    emit({ type: 'ready' })
    client.fetchConversations = vi.fn(async () => {
      throw new Error('网络抖动')
    })

    const result = await store.setConversationFlags('u8', { pinned: true })

    expect(result).toEqual({ pinned: true, muted: false })
    expect(store.conversations.find((item) => item.peerId === 'u8')?.pinned).toBe(true)
  })
})
