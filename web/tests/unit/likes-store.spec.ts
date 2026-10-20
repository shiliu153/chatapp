import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { useLikesStore } from '@/stores/likes'
import { server } from '../support/server'

const page = (results: unknown[], count = results.length) => ({
  count,
  next: null,
  previous: null,
  results,
})

const like = (id: number) => ({
  user_id: id,
  im_user_id: `u${id}`,
  nickname: `用户${id}`,
  gender: 'female',
  age: 25,
  city: '上海',
  bio: '',
  tags: [],
  photos: [],
  liked_at: '2026-10-20T02:30:00Z',
})

describe('likes store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('拉取喜欢我的人', async () => {
    server.use(mswHttp.get('/api/v1/discovery/likes', () => HttpResponse.json(page([like(1)]))))
    const store = useLikesStore()

    await store.load(true)

    expect(store.items).toHaveLength(1)
    expect(store.count).toBe(1)
  })

  it('accept → 调 like、移除该行、计数 -1', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/likes', () =>
        HttpResponse.json(page([like(1), like(2)])),
      ),
      mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: true })),
    )
    const store = useLikesStore()
    await store.load(true)

    await store.accept(1)

    expect(store.items.map((item) => item.user_id)).toEqual([2])
    expect(store.count).toBe(1)
    expect(store.matched?.user_id).toBe(1)
  })

  it('accept 失败 → 列表保留、错误上抛', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/likes', () => HttpResponse.json(page([like(1)]))),
      mswHttp.post('/api/v1/discovery/swipe', () =>
        HttpResponse.json({ code: 429, message: '操作太快了', request_id: 'r' }, { status: 429 }),
      ),
    )
    const store = useLikesStore()
    await store.load(true)

    await expect(store.accept(1)).rejects.toThrow()

    expect(store.items.map((item) => item.user_id)).toEqual([1])
    expect(store.busyUserId).toBeNull()
  })
})
