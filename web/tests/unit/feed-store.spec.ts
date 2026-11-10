import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { useFavoritesStore, useFeedStore, useFollowingFeedStore, usePostLikesStore } from '@/stores/feed'
import { server } from '../support/server'

export const post = (id: number, liked = false, favorited = false) => ({
  id,
  author: { user_id: 3, nickname: '小雨', avatar_url: null },
  text: `第 ${id} 条`,
  images: [],
  like_count: liked ? 1 : 0,
  comment_count: 0,
  liked_by_me: liked,
  is_favorited: favorited,
  created_at: '2026-10-01T10:00:00Z',
})

const paged = (results: unknown[], overrides: Record<string, unknown> = {}) => ({
  count: results.length,
  next_cursor: null,
  has_more: false,
  results,
  ...overrides,
})

const liker = (userId: number, likedAt = '2026-11-10T06:00:00Z') => ({
  user_id: userId,
  nickname: `小雨${userId}`,
  avatar_url: null,
  liked_at: likedAt,
})

describe('feed store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('按游标分页追加而不是替换', async () => {
    let calls = 0
    let secondQuery = ''
    server.use(
      mswHttp.get('/api/v1/posts', ({ request }) => {
        calls += 1
        if (calls > 1) secondQuery = new URL(request.url).search
        return HttpResponse.json(
          calls === 1
            ? paged([post(1)], { count: 2, next_cursor: 'c2', has_more: true })
            : paged([post(2)], { count: 2 }),
        )
      }),
    )
    const store = useFeedStore()

    await store.load()
    await store.load()

    expect(store.items.map((p) => p.id)).toEqual([1, 2])
    expect(secondQuery).toContain('before=c2')   // 第二页带游标,不再带 offset
    expect(store.hasMore).toBe(false)
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

    await store.toggleLike(store.items[0])

    expect(store.items[0].liked_by_me).toBe(false) // 已回滚
    expect(store.items[0].like_count).toBe(0)
  })

  it('点赞成功后计数 +1', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(paged([post(1)]))),
      mswHttp.post('/api/v1/posts/1/like', () => HttpResponse.json({ liked: true })),
    )
    const store = useFeedStore()
    await store.load()

    await store.toggleLike(store.items[0])

    expect(store.items[0].liked_by_me).toBe(true)
    expect(store.items[0].like_count).toBe(1)
  })

  it('取消点赞走 DELETE 并把计数减回去', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(paged([post(1, true)]))),
      mswHttp.delete('/api/v1/posts/1/like', () => HttpResponse.json({ liked: false })),
    )
    const store = useFeedStore()
    await store.load()

    await store.toggleLike(store.items[0])

    expect(store.items[0].liked_by_me).toBe(false)
    expect(store.items[0].like_count).toBe(0)
  })

  it('发布成功后新动态插到最前', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(paged([post(1)]))),
      mswHttp.post('/api/v1/posts', () => HttpResponse.json(post(99))),
    )
    const store = useFeedStore()
    await store.load()

    await store.create('新动态', [])

    expect(store.items[0].id).toBe(99)
    expect(store.count).toBe(2)
  })

  it('关注流是独立列表:走 /feed/following,不与推荐列表串数据', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(paged([post(1)]))),
      mswHttp.get('/api/v1/feed/following', () => HttpResponse.json(paged([post(9)]))),
    )
    const feed = useFeedStore()
    const following = useFollowingFeedStore()

    await feed.load()
    await following.load()

    expect(feed.items.map((p) => p.id)).toEqual([1])
    expect(following.items.map((p) => p.id)).toEqual([9])
  })

  it('收藏先行翻转 is_favorited(不碰点赞字段)', async () => {
    let favoriteCalls = 0
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(paged([post(1)]))),
      mswHttp.post('/api/v1/posts/1/favorite', () => {
        favoriteCalls += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const store = useFeedStore()
    await store.load()

    await store.toggleFavorite(store.items[0])

    expect(store.items[0].is_favorited).toBe(true)
    expect(store.items[0].liked_by_me).toBe(false) // 收藏与点赞是两条独立状态
    expect(store.items[0].like_count).toBe(0)
    // 恒 204 的幂等写:客户端只看状态码,不看响应体
    expect(favoriteCalls).toBe(1)
  })

  it('取消收藏走 DELETE,失败时把 is_favorited 翻回去', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(paged([post(1, false, true)]))),
      mswHttp.delete('/api/v1/posts/1/favorite', () =>
        HttpResponse.json({ code: 50002, message: '服务器开小差了', request_id: 'r' }, { status: 500 }),
      ),
    )
    const store = useFeedStore()
    await store.load()

    await store.toggleFavorite(store.items[0])

    expect(store.items[0].is_favorited).toBe(true) // 已回滚
  })
})

describe('收藏列表 store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('走 /feed/favorites,并把 is_favorited 原样映射到卡片', async () => {
    let path = ''
    server.use(
      mswHttp.get('/api/v1/feed/favorites', ({ request }) => {
        path = new URL(request.url).pathname
        return HttpResponse.json(paged([post(7, false, true)]))
      }),
    )
    const store = useFavoritesStore()

    await store.load(true)

    expect(path).toBe('/api/v1/feed/favorites')
    expect(store.items.map((p) => p.id)).toEqual([7])
    expect(store.items[0].is_favorited).toBe(true)
    expect(store.count).toBe(1)
  })

  it('与广场列表互不覆盖:两个 store 各存各的', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(paged([post(1)]))),
      mswHttp.get('/api/v1/feed/favorites', () => HttpResponse.json(paged([post(2, false, true)]))),
    )
    const feed = useFeedStore()
    const favorites = useFavoritesStore()

    await feed.load(true)
    await favorites.load(true)

    expect(feed.items.map((p) => p.id)).toEqual([1])
    expect(favorites.items.map((p) => p.id)).toEqual([2])
  })

  it('在收藏页取消收藏:只翻转标记,卡片先留在列表里(失败回滚)', async () => {
    let deletes = 0
    server.use(
      mswHttp.get('/api/v1/feed/favorites', () =>
        HttpResponse.json(paged([post(2, false, true)])),
      ),
      mswHttp.delete('/api/v1/posts/2/favorite', () => {
        deletes += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const store = useFavoritesStore()
    await store.load(true)

    await store.toggleFavorite(store.items[0])

    expect(deletes).toBe(1)
    expect(store.items[0].is_favorited).toBe(false)
    expect(store.items).toHaveLength(1) // 不摘卡片,手滑还能再点回来
  })

  it('收藏为空时 items 是空数组、没有错误', async () => {
    server.use(mswHttp.get('/api/v1/feed/favorites', () => HttpResponse.json(paged([]))))
    const store = useFavoritesStore()

    await store.load(true)

    expect(store.items).toEqual([])
    expect(store.count).toBe(0)
    expect(store.error).toBe('')
    expect(store.hasMore).toBe(false)
  })
})

describe('点赞列表 store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('按 post_id 拉 /posts/{id}/likes,并按游标追加', async () => {
    const paths: string[] = []
    server.use(
      mswHttp.get('/api/v1/posts/:id/likes', ({ request }) => {
        const url = new URL(request.url)
        paths.push(`${url.pathname}${url.search}`)
        return HttpResponse.json(
          url.searchParams.get('before')
            ? paged([liker(9)], { count: 2 })
            : paged([liker(8)], { count: 2, next_cursor: 'c2', has_more: true }),
        )
      }),
    )
    const store = usePostLikesStore()

    await store.load(5, true)
    await store.loadMore()

    expect(paths[0]).toContain('/api/v1/posts/5/likes')
    expect(paths[1]).toContain('before=c2')
    expect(store.items.map((l) => l.user_id)).toEqual([8, 9])
    expect(store.count).toBe(2)
    expect(store.hasMore).toBe(false)
  })

  it('没人点赞时是空列表而不是错误(200 + results: [])', async () => {
    server.use(mswHttp.get('/api/v1/posts/5/likes', () => HttpResponse.json(paged([]))))
    const store = usePostLikesStore()

    await store.load(5, true)

    expect(store.items).toEqual([])
    expect(store.count).toBe(0)
    expect(store.error).toBe('')
  })

  it('没进过页面时 loadMore 不发请求', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/posts/:id/likes', () => {
        calls += 1
        return HttpResponse.json(paged([]))
      }),
    )
    const store = usePostLikesStore()

    await store.loadMore()

    expect(calls).toBe(0)
  })
})
