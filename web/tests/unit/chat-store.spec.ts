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
  const conversations: ImConversation[] = [
    {
      peerId: 'u8',
      unreadCount: 2,
      showName: '小雨',
      faceUrl: null,
      lastMessage: null,
      peerReadSeq: 0,
      pinned: false,
      muted: false,
    },
    {
      peerId: 'system_notice',
      unreadCount: 1,
      showName: '系统通知',
      faceUrl: null,
      lastMessage: null,
      peerReadSeq: 0,
      pinned: false,
      muted: false,
    },
  ]
  const client = {
    onEvent: (fn: (event: ImEvent) => void) => {
      listener = fn
    },
    init: vi.fn(),
    login: vi.fn(async () => {}),
    logout: vi.fn(async () => {}),
    fetchConversations: vi.fn(async () => conversations),
    fetchHistory: vi.fn(async (_peerId?: string, _count?: number, _beforeSeq?: number) => [] as ChatMessage[]),
    searchMessages: vi.fn(async () => ({ items: [], hasMore: false })),
    capabilities: { image: true, search: true, voice: true, readReceipt: true },
    sendText: vi.fn(async (peerId: string, text: string) => msg({ msgId: 'm1', peerId, isSelf: true, text })),
    sendImage: vi.fn(async (peerId: string) => msg({ msgId: 'm2', peerId, isSelf: true })),
    sendVoice: vi.fn(async (peerId: string) =>
      msg({ msgId: 'm3', peerId, isSelf: true, kind: 'voice' as never }),
    ),
    sendSticker: vi.fn(async (peerId: string, stickerId: string) =>
      msg({ msgId: 'm4', peerId, isSelf: true, kind: 'sticker' as never, stickerId }),
    ),
    deleteMessage: vi.fn(async () => {}),
    deleteMessages: vi.fn(async (ids: string[]) => ids.length),
    revokeMessage: vi.fn(async () => {}),
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

  it('先连上再拉会话(否则会在 init 之前就用空凭证连 WS)', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()

    await store.loadConversations()

    expect(client.init).toHaveBeenCalledWith(
      expect.objectContaining({ token: 'tok-41', imUserId: 'u41' }),
    )
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
        peerReadSeq: 0,
        pinned: false,
        muted: false,
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

  it('IM 断线 → reconnecting → 退避 1s 后重连,并补拉会话与当前会话消息', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    // 先建立「当前会话」(真实定时器下把网络请求跑完,再切假定时器)
    await store.openConversation('u8')
    expect(store.status).toBe('ready')

    vi.useFakeTimers()
    try {
      client.login.mockClear()
      client.fetchConversations.mockClear()
      client.fetchHistory.mockClear()

      emit({ type: 'disconnected' })

      expect(store.status).toBe('reconnecting')
      expect(client.login).not.toHaveBeenCalled() // 第一次退避 1s 还没到

      await vi.advanceTimersByTimeAsync(1_000)
      await vi.advanceTimersByTimeAsync(0) // 让重连里的 HTTP 落地

      expect(client.login).toHaveBeenCalledTimes(1)
      expect(store.status).toBe('ready')
      // 断线期间的消息不会自己回来:必须补拉会话列表 + 当前会话历史
      expect(client.fetchConversations).toHaveBeenCalled()
      expect(client.fetchHistory).toHaveBeenCalledWith('u8')
    } finally {
      vi.useRealTimers()
    }
  })

  it('退避按 1/2/4… 递增:第一次 1s 未成功时下一次等 2s', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    await store.loadConversations()

    vi.useFakeTimers()
    try {
      // 让每次重连都失败(网络还没恢复)
      client.login = vi.fn(async () => Promise.reject(new Error('offline')))
      client.init = vi.fn()

      emit({ type: 'disconnected' })
      await vi.advanceTimersByTimeAsync(1_000)
      await vi.advanceTimersByTimeAsync(0)
      expect(client.login).toHaveBeenCalledTimes(1)
      // 这次没连上 → 继续排下一档退避,状态回到「重连中」(而不是停在 error)
      expect(store.status).toBe('reconnecting')

      // 第二次退避是 2s:999ms 时还不该重试
      await vi.advanceTimersByTimeAsync(1_999)
      expect(client.login).toHaveBeenCalledTimes(1)
      await vi.advanceTimersByTimeAsync(1)
      await vi.advanceTimersByTimeAsync(0)
      expect(client.login).toHaveBeenCalledTimes(2)
    } finally {
      vi.useRealTimers()
    }
  })

  it('被同端顶掉后即使收到 disconnected 也不自动重连', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    await store.loadConversations()
    client.login.mockClear()

    emit({ type: 'kickedOffline', reason: 'multiAccount' })
    emit({ type: 'disconnected' })

    expect(store.status).toBe('inactive')
    await new Promise((resolve) => setTimeout(resolve, 1_200))
    expect(client.login).not.toHaveBeenCalled()
  })

  it('主动退出登录后不因 disconnected 重连', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    await store.loadConversations()
    await store.close()
    client.login.mockClear()

    emit({ type: 'disconnected' })

    expect(store.status).toBe('idle')
    expect(client.login).not.toHaveBeenCalled()
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

  it('收到 messageRevoked 事件:对应消息标记 isRevoked', () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    emit({ type: 'newMessage', message: msg({ msgId: 'm7', peerId: 'u8', text: '打错了' }) })

    emit({ type: 'messageRevoked', msgId: 'm7' })

    expect(store.messagesOf('u8')[0].isRevoked).toBe(true)
  })

  it('revokeMessage 调 IM 并置灰', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    const message = msg({ msgId: 'm8', peerId: 'u8', isSelf: true, text: '打错了' })
    store.messages = { u8: [message] }

    await store.revokeMessage(message)

    expect(client.revokeMessage).toHaveBeenCalledWith('m8')
    expect(store.messagesOf('u8')[0].isRevoked).toBe(true)
  })

  it('连上之后才把客户端能力位同步进 store(入口按它显示)', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    // init 之前是兜底值:直接读 client.capabilities 会拿到 false(图片入口曾因此不显示)
    expect(store.capabilities).toEqual({
      image: false,
      search: false,
      voice: false,
      readReceipt: false,
    })

    await store.loadConversations()

    // 能力位整体同步:包括 readReceipt(已读回执的渲染开关)
    expect(store.capabilities).toMatchObject({
      image: true,
      search: true,
      voice: true,
      readReceipt: true,
    })
  })

  it('searchMessages 先确保已连接,再透传关键词/条数/游标', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()

    await store.searchMessages('火锅', 10, '99')

    expect(client.login).toHaveBeenCalled()
    expect(client.searchMessages).toHaveBeenCalledWith('火锅', 10, '99')
  })

  it('loadOlder 用最旧一条的 seq 作游标,找到目标即停', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    store.messages = {
      u8: [msg({ msgId: 'm2', seq: 101, timestamp: 2 }), msg({ msgId: 'm3', seq: 102, timestamp: 3 })],
    }
    client.fetchHistory = vi.fn(
      async (_peerId?: string, _count?: number, beforeSeq?: number) =>
        beforeSeq ? [msg({ msgId: 'target', seq: 99, timestamp: 1 })] : [],
    )

    await store.loadOlder('u8', 'target')

    expect(client.fetchHistory).toHaveBeenCalledWith('u8', 50, 101)
    expect(store.messagesOf('u8').map((item) => item.msgId)).toEqual(['target', 'm2', 'm3'])
  })

  it('sendVoice 先插入 isPending 占位,成功后替换成真实消息', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    const real = msg({ msgId: 'real-1', peerId: 'u8', isSelf: true, kind: 'voice' as never })
    client.sendVoice = vi.fn(async () => real)

    const pending = store.sendVoice('u8', new Blob(['a']), 3000)
    // 占位是同步上屏的:失败时才有东西可重试
    expect(store.messagesOf('u8').some((item) => item.isPending)).toBe(true)
    await pending
    const voices = store.messagesOf('u8').filter((item) => item.kind === 'voice')
    expect(voices).toHaveLength(1)
    expect(voices[0].msgId).toBe('real-1')
  })

  it('sendVoice 失败把占位标成 isFailed 并抛出', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    client.sendVoice = vi.fn(async () => Promise.reject(new Error('boom')))

    await expect(store.sendVoice('u8', new Blob(['a']), 3000)).rejects.toThrow('boom')
    const failed = store.messagesOf('u8').find((item) => item.kind === 'voice')
    expect(failed?.isFailed).toBe(true)
    expect(failed?.isPending).toBe(false)
  })

  it('resend 用缓存 blob 重发失败语音', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    client.sendVoice = vi.fn(async () => Promise.reject(new Error('boom')))
    await expect(store.sendVoice('u8', new Blob(['a']), 3000)).rejects.toThrow()

    const failed = store.messagesOf('u8').find((item) => item.isFailed)!
    client.sendVoice = vi.fn(async () =>
      msg({ msgId: 'real-2', peerId: 'u8', isSelf: true, kind: 'voice' as never }),
    )
    await store.resend(failed)
    expect(client.sendVoice).toHaveBeenCalledTimes(1)
    expect(store.messagesOf('u8').some((item) => item.msgId === 'real-2')).toBe(true)
  })

  it('sendImage 先插入 isPending 占位,成功后替换成真实消息', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    const real = msg({ msgId: 'img-1', peerId: 'u8', isSelf: true, kind: 'image' as never })
    client.sendImage = vi.fn(async () => real)

    const pending = store.sendImage('u8', new File(['a'], 'a.png'))
    expect(store.messagesOf('u8').some((item) => item.isPending)).toBe(true)
    await pending
    const images = store.messagesOf('u8').filter((item) => item.kind === 'image')
    expect(images).toHaveLength(1)
    expect(images[0].msgId).toBe('img-1')
  })

  it('sendImage 失败把占位标成 isFailed 并抛出', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    client.sendImage = vi.fn(async () => Promise.reject(new Error('boom')))

    await expect(store.sendImage('u8', new File(['a'], 'a.png'))).rejects.toThrow('boom')
    const failed = store.messagesOf('u8').find((item) => item.kind === 'image')
    expect(failed?.isFailed).toBe(true)
    expect(failed?.isPending).toBe(false)
  })

  it('resend 用缓存文件重发失败图片', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    client.sendImage = vi.fn(async () => Promise.reject(new Error('boom')))
    await expect(store.sendImage('u8', new File(['a'], 'a.png'))).rejects.toThrow()

    const failed = store.messagesOf('u8').find((item) => item.isFailed)!
    client.sendImage = vi.fn(async () =>
      msg({ msgId: 'img-2', peerId: 'u8', isSelf: true, kind: 'image' as never }),
    )
    await store.resend(failed)
    expect(client.sendImage).toHaveBeenCalledTimes(1)
    expect(store.messagesOf('u8').some((item) => item.msgId === 'img-2')).toBe(true)
  })

  it('sendSticker 先插入 isPending 占位,成功后替换成真实消息', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    const real = msg({
      msgId: 'stk-1',
      peerId: 'u8',
      isSelf: true,
      kind: 'sticker' as never,
      stickerId: 'sticker_01',
    })
    client.sendSticker = vi.fn(async () => real)

    const pending = store.sendSticker('u8', 'sticker_01')
    // 占位同步上屏,且带 stickerId(重发要靠它)
    expect(store.messagesOf('u8').some((item) => item.isPending)).toBe(true)
    await pending
    const stickers = store.messagesOf('u8').filter((item) => item.kind === 'sticker')
    expect(stickers).toHaveLength(1)
    expect(stickers[0].msgId).toBe('stk-1')
    expect(stickers[0].stickerId).toBe('sticker_01')
    // 第三个参数是引用回复的 `ref_msg_id`(批次 L-2);没引用时就是 undefined
    expect(client.sendSticker).toHaveBeenCalledWith('u8', 'sticker_01', undefined)
  })

  it('sendSticker 失败把占位标成 isFailed,resend 直接用 id 重发', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    client.sendSticker = vi.fn(async () => Promise.reject(new Error('boom')))
    await expect(store.sendSticker('u8', 'sticker_02')).rejects.toThrow('boom')

    const failed = store.messagesOf('u8').find((item) => item.isFailed)!
    expect(failed.kind).toBe('sticker')
    expect(failed.stickerId).toBe('sticker_02')

    client.sendSticker = vi.fn(async () =>
      msg({ msgId: 'stk-2', peerId: 'u8', isSelf: true, kind: 'sticker' as never }),
    )
    await store.resend(failed)
    expect(client.sendSticker).toHaveBeenCalledWith('u8', 'sticker_02', undefined)
    expect(store.messagesOf('u8').some((item) => item.msgId === 'stk-2')).toBe(true)
  })
  // --- 多选删除(批次 T)---

  it('批量删除:先调服务端、成功后从 store 摘掉这几条', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    store.messages = {
      u8: [
        msg({ msgId: '101', peerId: 'u8', seq: 1, text: '一' }),
        msg({ msgId: '102', peerId: 'u8', seq: 2, text: '二' }),
        msg({ msgId: '103', peerId: 'u8', seq: 3, text: '三' }),
      ],
    }

    const deleted = await store.deleteMessages('u8', ['101', '103'])

    expect(client.deleteMessages).toHaveBeenCalledWith(['101', '103'])
    expect(deleted).toBe(2)
    expect(store.messagesOf('u8').map((item) => item.msgId)).toEqual(['102'])
  })

  it('批量删除失败:上抛且**一条都不摘**(不留「界面没了、刷新又回来」)', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    store.messages = {
      u8: [msg({ msgId: '101', peerId: 'u8', seq: 1 }), msg({ msgId: '102', peerId: 'u8', seq: 2 })],
    }
    client.deleteMessages = vi.fn(async () => Promise.reject(new Error('IM HTTP 500')))

    await expect(store.deleteMessages('u8', ['101', '102'])).rejects.toThrow('IM HTTP 500')
    expect(store.messagesOf('u8').map((item) => item.msgId)).toEqual(['101', '102'])
  })

  it('本地占位消息(还没落库)不上行,只在本地摘掉', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    store.messages = {
      u8: [
        msg({ msgId: 'local-1', peerId: 'u8', isSelf: true, isFailed: true }),
        msg({ msgId: '101', peerId: 'u8', seq: 1 }),
      ],
    }

    const deleted = await store.deleteMessages('u8', ['local-1', '101'])

    // 服务端只收到真实 id:占位 id 上行会被判 42201
    expect(client.deleteMessages).toHaveBeenCalledWith(['101'])
    expect(deleted).toBe(1)
    expect(store.messagesOf('u8')).toHaveLength(0)
  })

  it('只选本地占位时不发请求,直接本地摘掉', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    store.messages = { u8: [msg({ msgId: 'local-9', peerId: 'u8', isSelf: true, isFailed: true })] }

    const deleted = await store.deleteMessages('u8', ['local-9'])

    expect(client.deleteMessages).not.toHaveBeenCalled()
    expect(deleted).toBe(0)
    expect(store.messagesOf('u8')).toHaveLength(0)
  })

  it('空列表是空操作(服务端把空数组判 42201,不能白白发出去)', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()

    await expect(store.deleteMessages('u8', [])).resolves.toBe(0)
    expect(client.deleteMessages).not.toHaveBeenCalled()
  })

  it('单条「删除」走同一个批量接口(两条路径不会走样)', async () => {
    const { client } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    store.messages = { u8: [msg({ msgId: '101', peerId: 'u8', seq: 1 })] }

    await store.deleteMessage(store.messagesOf('u8')[0])

    expect(client.deleteMessages).toHaveBeenCalledWith(['101'])
    expect(store.messagesOf('u8')).toHaveLength(0)
  })
})
