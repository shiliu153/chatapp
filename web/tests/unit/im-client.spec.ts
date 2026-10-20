import { describe, expect, it, vi } from 'vitest'
import { createImClient, kickReasonOf, type TimChatLike } from '@/im/client'
import { ChatMessageKind } from '@/im/types'

/** 手写一个最小假 SDK:记录调用、可手动触发事件。 */
function fakeSdk() {
  const handlers = new Map<string, ((event: { data: unknown; name?: string }) => void)[]>()
  const sent: unknown[] = []
  const sdk: TimChatLike = {
    login: vi.fn(async () => ({})),
    logout: vi.fn(async () => {}),
    isReady: () => true,
    on: (name, handler) => {
      handlers.set(name, [...(handlers.get(name) ?? []), handler])
    },
    off: (name, handler) => {
      handlers.set(
        name,
        (handlers.get(name) ?? []).filter((h) => h !== handler),
      )
    },
    createTextMessage: ({ payload }) => ({ ID: 'm1', type: 'TIMTextElem', payload, flow: 'out' }),
    createImageMessage: ({ payload }) => ({ ID: 'm2', type: 'TIMImageElem', payload, flow: 'out' }),
    sendMessage: vi.fn(async (message: unknown) => {
      sent.push(message)
      return { data: { message } }
    }),
    deleteMessage: vi.fn(async () => ({})),
    revokeMessage: vi.fn(async () => ({})),
    getMessageList: vi.fn(async () => ({ data: { messageList: [] } })),
    setMessageRead: vi.fn(async () => ({})),
    getConversationList: vi.fn(async () => ({ data: { conversationList: [] } })),
    getUserProfile: vi.fn(async () => ({ data: [] })),
    deleteConversation: vi.fn(async () => ({})),
  }
  return {
    sdk,
    sent,
    emit: (name: string, data: unknown) => handlers.get(name)?.forEach((h) => h({ data, name })),
  }
}

function makeClient(overrides: Record<string, string> = {}) {
  const fake = fakeSdk()
  const client = createImClient({
    sdk: fake.sdk,
    events: { messageReceived: 'onMessageReceived', ...overrides },
  })
  return { ...fake, client }
}

describe('im client', () => {
  it('登录后把新消息转成领域事件', async () => {
    const { client, emit } = makeClient()
    const events: unknown[] = []
    client.onEvent((e) => events.push(e))

    await client.login('u9', 'sig')
    emit('onMessageReceived', [
      {
        ID: 'x1',
        type: 'TIMTextElem',
        payload: { text: '你好' },
        flow: 'in',
        from: 'u8',
        to: 'u9',
        time: 1700000000,
        status: 'success',
      },
    ])

    expect(events).toEqual([
      expect.objectContaining({
        type: 'newMessage',
        message: expect.objectContaining({ text: '你好', isSelf: false, peerId: 'u8' }),
      }),
    ])
  })

  it('发文本走 createTextMessage + sendMessage,并返回本端消息', async () => {
    const { client, sent } = makeClient()

    const message = await client.sendText('u8', '在吗')

    expect(sent).toHaveLength(1)
    expect(message).toMatchObject({ text: '在吗', isSelf: true, peerId: 'u8' })
  })

  it('发图片把 File 交给 SDK(浏览器原生对象,不做路径转换)', async () => {
    const { client, sent } = makeClient()
    const file = new File(['x'], 'a.png', { type: 'image/png' })

    const message = await client.sendImage('u8', file)

    expect(message.isSelf).toBe(true)
    expect(message.kind).toBe(ChatMessageKind.image)
    expect((sent[0] as { payload: { file: File } }).payload.file).toBe(file)
  })

  it('login 要等 SDK really ready 才 resolve', async () => {
    // spike 实测:login 的 Promise 先 resolve,isReady() 还是 false;
    // 不等就调其它 API 会拿到「SDK 未就绪」的错误(真机上表现为聊天历史永远空白)。
    const { client, sdk, emit } = makeClient()
    let ready = false
    sdk.isReady = () => ready
    let resolved = false

    const loginPromise = client.login('u9', 'sig').then(() => {
      resolved = true
    })
    // 用真实定时器排空微任务:否则「恰好还没轮到」会让断言假绿(修不修都过)
    await new Promise((resolve) => setTimeout(resolve, 30))
    expect(resolved).toBe(false) // 还没 ready

    ready = true
    emit('sdkStateReady', undefined)
    await loginPromise

    expect(resolved).toBe(true)
  })

  it('踢下线事件带上原因', async () => {
    const { client, emit } = makeClient({ kickedOut: 'kickedOut' })
    const events: { type: string; reason?: string }[] = []
    client.onEvent((e) => events.push(e as never))

    emit('kickedOut', { type: 'multipleDevice' })

    expect(events[0]).toMatchObject({ type: 'kickedOffline', reason: 'multiDevice' })
  })

  it('会话列表更新事件被转发', () => {
    const { client, emit } = makeClient({ conversationListUpdated: 'onConversationListUpdated' })
    const events: unknown[] = []
    client.onEvent((e) => events.push(e))

    emit('onConversationListUpdated', [])

    expect(events).toEqual([{ type: 'conversationsChanged' }])
  })

  it('拉会话列表:过滤非单聊并解析对端', async () => {
    const { client, sdk } = makeClient()
    sdk.getConversationList = vi.fn(async () => ({
      data: {
        conversationList: [
          {
            conversationID: 'C2Cu8',
            type: 'C2C',
            unreadCount: 1,
            userProfile: { nick: '小雨', avatar: 'https://cdn/a.jpg' },
          },
          { conversationID: 'GROUP1', type: 'GROUP', unreadCount: 9 },
        ],
      },
    }))

    const conversations = await client.fetchConversations()

    expect(conversations).toHaveLength(1)
    expect(conversations[0]).toMatchObject({ peerId: 'u8', showName: '小雨', unreadCount: 1 })
  })

  it('昵称未知的会话会补拉一次 IM 用户资料(真机实测 SDK 不会自己补)', async () => {
    const { client, sdk } = makeClient()
    sdk.getConversationList = vi.fn(async () => ({
      data: {
        conversationList: [
          {
            conversationID: 'C2Cu18',
            type: 'C2C',
            unreadCount: 4,
            userProfile: { userID: 'u18', nick: '', avatar: '' },
            lastMessage: { ID: 'x', type: 'TIMTextElem', payload: { text: '你好' } },
          },
        ],
      },
    }))
    const seen: string[][] = []
    sdk.getUserProfile = vi.fn(async ({ userIDList }) => {
      seen.push(userIDList)
      return { data: [{ userID: 'u18', nick: '婉婷18', avatar: 'https://cdn/p.jpg' }] }
    })

    const conversations = await client.fetchConversations()

    expect(seen).toEqual([['u18']])
    expect(conversations[0]).toMatchObject({ showName: '婉婷18', faceUrl: 'https://cdn/p.jpg' })
  })

  it('markConversationRead / deleteConversation 用 C2C 前缀拼会话 ID', async () => {
    const { client, sdk } = makeClient()

    await client.markConversationRead('u8')
    await client.deleteConversation('u8')

    expect(sdk.setMessageRead).toHaveBeenCalledWith({ conversationID: 'C2Cu8' })
    expect(sdk.deleteConversation).toHaveBeenCalledWith('C2Cu8')
  })

  it('deleteMessage 按 msgId 从历史里找到消息对象再删', async () => {
    const { client, sdk } = makeClient()
    sdk.getMessageList = vi.fn(async () => ({
      data: { messageList: [{ ID: 'zz', type: 'TIMTextElem', payload: { text: 'x' }, flow: 'in' }] },
    }))
    await client.fetchHistory('u8')

    await client.deleteMessage('zz')

    expect(sdk.deleteMessage).toHaveBeenCalledTimes(1)
    expect((sdk.deleteMessage as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][0]).toEqual([
      expect.objectContaining({ ID: 'zz' }),
    ])
  })

  it('撤回:找到消息对象交给 SDK,并广播 messageRevoked', async () => {
    const { client, sdk, emit } = makeClient({ messageRevoked: 'onMessageRevoked' })
    sdk.getMessageList = vi.fn(async () => ({
      data: {
        messageList: [{ ID: 'zz', type: 'TIMTextElem', payload: { text: 'x' }, flow: 'out' }],
      },
    }))
    const revoked: string[] = []
    client.onEvent((e) => {
      if (e.type === 'messageRevoked') revoked.push(e.msgId)
    })
    await client.fetchHistory('u8')

    await client.revokeMessage('zz')
    emit('onMessageRevoked', { msgID: 'zz' })

    expect(sdk.revokeMessage).toHaveBeenCalledWith(expect.objectContaining({ ID: 'zz' }))
    expect(revoked).toEqual(['zz'])
  })
})

describe('kickReasonOf', () => {
  it('映射四类踢出原因,未知归为 restApi', () => {
    expect(kickReasonOf({ type: 'multipleDevice' })).toBe('multiDevice')
    expect(kickReasonOf({ type: 'multipleAccount' })).toBe('multiAccount')
    expect(kickReasonOf({ type: 'userSigExpired' })).toBe('sigExpired')
    expect(kickReasonOf({ type: 'REST_API_Kick' })).toBe('restApi')
    expect(kickReasonOf(undefined)).toBe('restApi')
  })
})
