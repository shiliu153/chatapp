import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { useFeedStore } from '@/stores/feed'
import { server } from '../support/server'

export const post = (id: number, liked = false) => ({
  id,
  author: { user_id: 3, nickname: '小雨', avatar_url: null },
  text: `第 ${id} 条`,
  images: [],
  like_count: liked ? 1 : 0,
  comment_count: 0,
  liked_by_me: liked,
  created_at: '2026-10-01T10:00:00Z',
})

const paged = (results: unknown[], overrides: Record<string, unknown> = {}) => ({
  count: results.length,
  next: null,
  previous: null,
  results,
  ...overrides,
})

describe('feed store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('分页追加而不是替换', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/posts', () => {
        calls += 1
        return HttpResponse.json(
          calls === 1 ? paged([post(1)], { count: 2, next: 'x' }) : paged([post(2)], { count: 2 }),
        )
      }),
    )
    const store = useFeedStore()

    await store.load()
    await store.load()

    expect(store.posts.map((p) => p.id)).toEqual([1, 2])
  })

  it('点赞先行更新界面,失败时回滚', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(paged([post(1)]))),
      mswHttp.post('/api/v1/posts/1/like', () =>
        HttpResponse.json({ code: 50002, message: '服务器开小差了', request_id: 'r' }, { status: 500 }),
      ),
    )
    const store = useFeedStore()
    await store.load()

    await store.toggleLike(store.posts[0])

    expect(store.posts[0].liked_by_me).toBe(false) // 已回滚
    expect(store.posts[0].like_count).toBe(0)
  })

  it('点赞成功后计数 +1', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(paged([post(1)]))),
      mswHttp.post('/api/v1/posts/1/like', () => HttpResponse.json({ liked: true })),
    )
    const store = useFeedStore()
    await store.load()

    await store.toggleLike(store.posts[0])

    expect(store.posts[0].liked_by_me).toBe(true)
    expect(store.posts[0].like_count).toBe(1)
  })

  it('取消点赞走 DELETE 并把计数减回去', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(paged([post(1, true)]))),
      mswHttp.delete('/api/v1/posts/1/like', () => HttpResponse.json({ liked: false })),
    )
    const store = useFeedStore()
    await store.load()

    await store.toggleLike(store.posts[0])

    expect(store.posts[0].liked_by_me).toBe(false)
    expect(store.posts[0].like_count).toBe(0)
  })

  it('发布成功后新动态插到最前', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(paged([post(1)]))),
      mswHttp.post('/api/v1/posts', () => HttpResponse.json(post(99))),
    )
    const store = useFeedStore()
    await store.load()

    await store.create('新动态', [])

    expect(store.posts[0].id).toBe(99)
    expect(store.count).toBe(2)
  })
})
