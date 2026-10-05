import { createPinia, disposePinia, setActivePinia, type Pinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { usePresenceStore } from '@/stores/presence'
import { server } from '../support/server'

/**
 * ⚠️ 每个用例都新建 pinia → store 也会新建,而 store 的 setInterval 与
 * visibilitychange 监听是挂在实例上的。不在 afterEach 里 stop() + dispose,
 * 上一个用例的定时器/监听会在下一个用例里继续打请求,计数断言就会串。
 */
type PresenceStore = ReturnType<typeof usePresenceStore>
let current: PresenceStore | null = null
let pinia: Pinia

function makeStore(): PresenceStore {
  current = usePresenceStore()
  return current
}

describe('presence store', () => {
  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    vi.useFakeTimers()
  })
  afterEach(() => {
    current?.stop()
    current = null
    disposePinia(pinia) // 触发 onScopeDispose:摘掉全局 visibilitychange 监听
    vi.clearAllTimers()
    vi.useRealTimers()
  })

  it('track 后拉取在线状态', async () => {
    server.use(
      mswHttp.get('/api/v1/presence', () =>
        HttpResponse.json({ results: [{ user_id: 8, online: true, last_active_at: null }] }),
      ),
    )
    const store = makeStore()

    store.track('candidates', [8])
    await vi.advanceTimersByTimeAsync(0)

    expect(store.isOnline(8)).toBe(true)
  })

  it('多个 owner 的 id 合并去重后只发一次请求', async () => {
    let calls = 0
    let seenIds = ''
    server.use(
      mswHttp.get('/api/v1/presence', ({ request }) => {
        calls += 1
        seenIds = new URL(request.url).searchParams.get('user_ids') ?? ''
        return HttpResponse.json({ results: [] })
      }),
    )
    const store = makeStore()

    store.track('candidates', [8])
    store.track('chats', [8, 9])
    await vi.advanceTimersByTimeAsync(0)

    expect(calls).toBe(1)
    expect(seenIds).toBe('8,9')
  })

  it('超过 100 个 id 时按 100 分片', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/presence', () => {
        calls += 1
        return HttpResponse.json({ results: [] })
      }),
    )
    const store = makeStore()

    store.track(
      'feed',
      Array.from({ length: 150 }, (_, i) => i + 1),
    )
    await vi.advanceTimersByTimeAsync(0)

    expect(calls).toBe(2)
  })

  it('45 秒后自动再拉一轮', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/presence', () => {
        calls += 1
        return HttpResponse.json({ results: [] })
      }),
    )
    const store = makeStore()
    store.track('candidates', [8])
    await vi.advanceTimersByTimeAsync(0)

    await vi.advanceTimersByTimeAsync(45_000)

    expect(calls).toBe(2)
  })

  it('页面隐藏时停止轮询,重新可见立刻补一次', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/presence', () => {
        calls += 1
        return HttpResponse.json({ results: [] })
      }),
    )
    const store = makeStore()
    store.track('candidates', [8])
    await vi.advanceTimersByTimeAsync(0)
    expect(calls).toBe(1)

    Object.defineProperty(document, 'hidden', { configurable: true, value: true })
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(120_000)
    expect(calls).toBe(1) // 隐藏期间不轮询

    Object.defineProperty(document, 'hidden', { configurable: true, value: false })
    document.dispatchEvent(new Event('visibilitychange'))
    await vi.advanceTimersByTimeAsync(0)
    expect(calls).toBe(2) // 重新可见立即补一次
  })

  it('拉取失败保持旧值,不抛错', async () => {
    server.use(
      mswHttp.get('/api/v1/presence', () =>
        HttpResponse.json({ code: 50002, message: '服务器开小差了', request_id: 'r' }, { status: 500 }),
      ),
    )
    const store = makeStore()
    store.track('candidates', [8])

    // 不 reject 就算通过(错误被 store 吞掉,不该冒泡给页面)
    await vi.advanceTimersByTimeAsync(0)
    expect(store.isOnline(8)).toBe(false)
  })
})
