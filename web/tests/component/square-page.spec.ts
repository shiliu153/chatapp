import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import SquarePage from '@/features/square/SquarePage.vue'
import { server } from '../support/server'
import type { Post } from '@/api/types'

const post = (id: number): Post => ({
  id,
  author: { user_id: 3, nickname: '小雨', avatar_url: null },
  text: `第 ${id} 条`,
  images: [],
  like_count: 0,
  comment_count: 0,
  liked_by_me: false,
  is_favorited: false,
  created_at: '2026-10-01T10:00:00Z',
})

const page = (results: unknown[], overrides = {}) => ({
  count: results.length,
  next_cursor: null,
  has_more: false,
  results,
  ...overrides,
})

function mountPage() {
  return mount(SquarePage, {
    global: { plugins: [createPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

describe('SquarePage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('渲染动态网格', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(page([post(1), post(2)]))),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.findAll('.post-card')).toHaveLength(2)
    expect(w.find('.square__grid').exists()).toBe(true)
  })

  it('没有动态时展示空态', async () => {
    server.use(mswHttp.get('/api/v1/posts', () => HttpResponse.json(page([]))))
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-empty').exists()).toBe(true)
  })

  it('加载失败展示错误态,重试后恢复', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/posts', () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json(
              { code: 50002, message: '服务器开小差了', request_id: 'r' },
              { status: 500 },
            )
          : HttpResponse.json(page([post(1)]))
      }),
    )
    const w = mountPage()
    await flushPromises()
    expect(w.find('.app-error').exists()).toBe(true)

    await w.find('.app-error button').trigger('click')
    await flushPromises()
    expect(w.findAll('.post-card')).toHaveLength(1)
  })

  it('还有下一页时展示「加载更多」', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () =>
        HttpResponse.json(page([post(1)], { count: 2, next_cursor: 'c2', has_more: true })),
      ),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.square__more').exists()).toBe(true)
  })

  it('切到「关注」tab 走 /feed/following,可切回推荐', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(page([post(1)]))),
      mswHttp.get('/api/v1/feed/following', () => HttpResponse.json(page([post(9)]))),
    )
    const w = mountPage()
    await flushPromises()
    expect(w.text()).toContain('第 1 条')

    await w.findAll('.square__tab')[1].trigger('click')
    await flushPromises()

    expect(w.find('.square__tab--active').text()).toBe('关注')
    expect(w.text()).toContain('第 9 条')
    expect(w.text()).not.toContain('第 1 条')

    await w.findAll('.square__tab')[0].trigger('click')
    await flushPromises()
    expect(w.text()).toContain('第 1 条')
  })

  it('点赞数为 0 时点数字不发请求(数字不是入口)', async () => {
    const paths: string[] = []
    server.use(
      mswHttp.get('/api/v1/posts', ({ request }) => {
        paths.push(new URL(request.url).pathname)
        return HttpResponse.json(page([post(1)]))
      }),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.post-card__like-count').trigger('click')
    await flushPromises()

    // 只有进页面那一次 /posts;点数字不该再打 /posts/1/likes
    expect(paths).toEqual(['/api/v1/posts'])
  })

  it('点收藏按钮打 /posts/{id}/favorite,并把书签点亮', async () => {
    let favorites = 0
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(page([post(1)]))),
      mswHttp.post('/api/v1/posts/1/favorite', () => {
        favorites += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.post-card__favorite').trigger('click')
    await flushPromises()

    expect(favorites).toBe(1)
    expect(w.find('.post-card__favorite').classes()).toContain('post-card__favorite--active')
  })

  it('关注 tab 空态:提示去推荐看看', async () => {
    server.use(
      mswHttp.get('/api/v1/posts', () => HttpResponse.json(page([]))),
      mswHttp.get('/api/v1/feed/following', () => HttpResponse.json(page([]))),
    )
    const w = mountPage()
    await flushPromises()

    await w.findAll('.square__tab')[1].trigger('click')
    await flushPromises()

    expect(w.text()).toContain('还没有关注的人')
    expect(w.text()).toContain('去「推荐」看看')
  })
})
