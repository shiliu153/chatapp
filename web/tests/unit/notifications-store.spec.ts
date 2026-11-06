import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { useNotificationsStore } from '@/stores/notifications'
import { server } from '../support/server'

const page = (results: unknown[], nextCursor: string | null = null) => ({
  count: results.length,
  next_cursor: nextCursor,
  has_more: nextCursor !== null,
  results,
})

const notification = (id: number, isRead = false) => ({
  id,
  kind: 'post_like',
  text: `通知${id}`,
  is_read: isRead,
  created_at: '2026-11-06T12:30:00+08:00',
  actor: { id: 7, nickname: '小明', avatar: null },
  target: { kind: 'post', id: 9 },
})

describe('notifications store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('拉取第一页', async () => {
    server.use(
      mswHttp.get('/api/v1/notifications', () =>
        HttpResponse.json(page([notification(2)])),
      ),
    )
    const store = useNotificationsStore()

    await store.load(true)

    expect(store.items).toHaveLength(1)
    expect(store.count).toBe(1)
    expect(store.cursor).toBeNull()
  })

  it('load 追加下一页(带上游标)', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/notifications', ({ request }) => {
        calls += 1
        const before = new URL(request.url).searchParams.get('before')
        if (calls === 1) return HttpResponse.json(page([notification(2)], 'c2'))
        expect(before).toBe('c2')
        return HttpResponse.json(page([notification(1)]))
      }),
    )
    const store = useNotificationsStore()
    await store.load(true)

    await store.load()

    expect(store.items.map((item) => item.id)).toEqual([2, 1])
    expect(store.cursor).toBeNull()
  })

  it('loadUnread 拉未读数', async () => {
    server.use(
      mswHttp.get('/api/v1/notifications/unread_count', () =>
        HttpResponse.json({ unread: 3 }),
      ),
    )
    const store = useNotificationsStore()

    await store.loadUnread()

    expect(store.unread).toBe(3)
  })

  it('markOne → 发 ids、条目已读、刷新角标', async () => {
    let unread = 2
    server.use(
      mswHttp.get('/api/v1/notifications', () =>
        HttpResponse.json(page([notification(2), notification(1, true)])),
      ),
      mswHttp.post('/api/v1/notifications/read', async ({ request }) => {
        expect(await request.json()).toEqual({ ids: [2] })
        unread = 1
        return new HttpResponse(null, { status: 204 })
      }),
      mswHttp.get('/api/v1/notifications/unread_count', () =>
        HttpResponse.json({ unread }),
      ),
    )
    const store = useNotificationsStore()
    await store.load(true)
    await store.loadUnread()
    expect(store.unread).toBe(2)

    await store.markOne(store.items[0])

    expect(store.items[0].is_read).toBe(true)
    expect(store.unread).toBe(1)
  })

  it('markOne 对已读条目不请求', async () => {
    let posted = 0
    server.use(
      mswHttp.get('/api/v1/notifications', () =>
        HttpResponse.json(page([notification(1, true)])),
      ),
      mswHttp.post('/api/v1/notifications/read', () => {
        posted += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const store = useNotificationsStore()
    await store.load(true)

    await store.markOne(store.items[0])

    expect(posted).toBe(0)
  })

  it('markAll → 发 all=true、全部已读、角标清零', async () => {
    server.use(
      mswHttp.get('/api/v1/notifications', () =>
        HttpResponse.json(page([notification(2), notification(1)])),
      ),
      mswHttp.post('/api/v1/notifications/read', async ({ request }) => {
        expect(await request.json()).toEqual({ all: true })
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const store = useNotificationsStore()
    await store.load(true)
    store.unread = 2

    await store.markAll()

    expect(store.items.every((item) => item.is_read)).toBe(true)
    expect(store.unread).toBe(0)
  })

  it('加载失败 → 记录错误并上抛', async () => {
    server.use(
      mswHttp.get('/api/v1/notifications', () =>
        HttpResponse.json(
          { code: 50002, message: '服务器开小差了', request_id: 'r' },
          { status: 500 },
        ),
      ),
    )
    const store = useNotificationsStore()

    await expect(store.load(true)).rejects.toThrow()
    expect(store.error).toBe('服务器开小差了')
    expect(store.loading).toBe(false)
  })
})
