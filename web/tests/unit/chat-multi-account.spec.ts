/**
 * 多标签互顶(批次 K / K-4 复核)。
 *
 * 批次 K 之后一个账号可同时在线「1 个 App + 1 个网页」,但**两个浏览器标签仍属同类端**
 * —— 第二个标签登录照样顶掉第一个。被顶的那个标签必须:
 *
 * 1. **保留凭证**:凭证在 localStorage / Cookie 里是所有标签共享的,清掉等于把另一个
 *    标签也一起登出;
 * 2. **不自动重连**:两个标签会自动互相踢成风暴 —— 2026 年的 A-1 事故里 10 秒打了
 *    27 次 `user_sig`,直接被 IM 限流,表现成「莫名其妙掉线」。
 *
 * 所以本文件只断言「同类端仍互顶 + 被顶不自动抢回来」,实现改动属于 K-3 的
 * `stores/chat.ts` 范围,这里不碰。
 */
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useChatStore } from '@/stores/chat'
import { setImClientFactory } from '@/im/client'
import { sessionEvents } from '@/api/session-events'
import { server } from '../support/server'
import type { ImClient, ImEvent } from '@/im/types'

/** 最小假 IM 客户端:只保留这条用例走到的部分。 */
function fakeClient() {
  let listener: ((event: ImEvent) => void) | null = null
  const client = {
    onEvent: (fn: (event: ImEvent) => void) => {
      listener = fn
    },
    init: vi.fn(async () => {}),
    login: vi.fn(async () => {}),
    logout: vi.fn(async () => {}),
    fetchConversations: vi.fn(async () => []),
    fetchHistory: vi.fn(async () => []),
    searchMessages: vi.fn(async () => ({ items: [], hasMore: false })),
    capabilities: { image: true, search: true, voice: true, readReceipt: true },
    markConversationRead: vi.fn(async () => {}),
    deleteConversation: vi.fn(async () => {}),
  }
  return { client, emit: (event: ImEvent) => listener?.(event) }
}

/** 取 IM 凭证的调用次数 —— A-1 事故的量化指标就是它。 */
let userSigCalls = 0

describe('chat store:多标签互顶', () => {
  beforeEach(() => {
    userSigCalls = 0
    setActivePinia(createPinia())
    sessionEvents._reset()
    server.use(
      mswHttp.post('/api/v1/im/user_sig', () => {
        userSigCalls += 1
        return HttpResponse.json({
          backend: 'self',
          token: 'tok-41',
          ws_url: 'ws://test/im/ws',
          http_url: 'http://test/im/api',
          im_user_id: 'u41',
          expire: 1791189272,
        })
      }),
    )
  })

  it('第二个标签登录顶掉第一个标签后:不自动重连、不再打 user_sig、凭证留着', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const expired = vi.fn()
    sessionEvents.onKickedOffline(expired)
    const store = useChatStore()

    // 第一个标签已连上(一次 user_sig)
    await store.loadConversations()
    expect(store.status).toBe('ready')
    expect(userSigCalls).toBe(1)
    client.login.mockClear()

    // 第二个标签用同一账号登录 → 服务端按同类端互顶,第一个标签收到 kicked
    emit({ type: 'kickedOffline', reason: 'multiAccount' })

    expect(store.status).toBe('inactive')
    expect(expired).not.toHaveBeenCalled() // 凭证不能清,否则两个标签一起掉线

    vi.useFakeTimers()
    try {
      // 10 秒是 A-1 事故的量级:那 10 秒里旧实现打了 27 次 user_sig 被限流
      await vi.advanceTimersByTimeAsync(10_000)
      // 服务端随后用 4001 关连接,客户端会补一个 disconnected
      emit({ type: 'disconnected' })
      await vi.advanceTimersByTimeAsync(10_000)

      expect(userSigCalls).toBe(1) // 一次都没有再取凭证
      expect(client.login).not.toHaveBeenCalled() // 也没有偷偷重连
      expect(store.status).toBe('inactive')
    } finally {
      vi.useRealTimers()
    }
  })

  it('被另一个标签顶掉后,用户显式接管(reconnect)才会重新取凭证', async () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const store = useChatStore()
    await store.loadConversations()

    emit({ type: 'kickedOffline', reason: 'multiAccount' })
    expect(userSigCalls).toBe(1)

    await store.reconnect()

    expect(userSigCalls).toBe(2)
    expect(store.status).toBe('ready')
  })

  it('被「别的端」顶掉(不是同类标签)仍走全屏提示,与上一条区分开', () => {
    const { client, emit } = fakeClient()
    setImClientFactory(() => client as unknown as ImClient)
    const expired = vi.fn()
    sessionEvents.onKickedOffline(expired)
    useChatStore()

    emit({ type: 'kickedOffline', reason: 'multiDevice' })

    expect(expired).toHaveBeenCalledTimes(1)
  })
})
