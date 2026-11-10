import { flushPromises, mount } from '@vue/test-utils'
import { HttpResponse, http as mswHttp } from 'msw'
import { describe, expect, it } from 'vitest'
import FavoritesPage from '@/features/square/FavoritesPage.vue'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'
import type { Post } from '@/api/types'

const post = (id: number, favorited = true): Post => ({
  id,
  author: { user_id: 9, nickname: '小雨', avatar_url: null },
  text: `第 ${id} 条`,
  images: [],
  like_count: 0,
  comment_count: 0,
  liked_by_me: false,
  is_favorited: favorited,
  created_at: '2026-10-01T10:00:00Z',
})

const page = (results: unknown[], overrides = {}) => ({
  count: results.length,
  next_cursor: null,
  has_more: false,
  results,
  ...overrides,
})

/** RouterLink 桩:保留 `to`,好断言卡片上的数字指向哪条路由。 */
const RouterLinkStub = {
  props: ['to'],
  template: '<a :data-to="JSON.stringify(to)"><slot /></a>',
}

function mountPage() {
  return mount(FavoritesPage, {
    global: { plugins: [freshPinia()], stubs: { RouterLink: RouterLinkStub } },
  })
}

describe('FavoritesPage', () => {
  it('拉 /feed/favorites 并用 PostCard 网格渲染', async () => {
    const paths: string[] = []
    server.use(
      mswHttp.get('/api/v1/feed/favorites', ({ request }) => {
        paths.push(new URL(request.url).pathname)
        return HttpResponse.json(page([post(1), post(2)]))
      }),
    )
    const w = mountPage()
    await flushPromises()

    expect(paths).toEqual(['/api/v1/feed/favorites'])
    expect(w.findAll('.post-card')).toHaveLength(2)
    // 收藏列表里的卡片本身就是已收藏状态
    expect(w.find('.post-card__favorite').classes()).toContain('post-card__favorite--active')
  })

  it('没有收藏时展示空态', async () => {
    server.use(mswHttp.get('/api/v1/feed/favorites', () => HttpResponse.json(page([]))))
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-empty').exists()).toBe(true)
    expect(w.text()).toContain('还没有收藏')
    expect(w.findAll('.post-card')).toHaveLength(0)
  })

  it('加载失败展示错误态,重试后恢复', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/feed/favorites', () => {
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

  it('在收藏页点书签走 DELETE,卡片留在列表里(可再点回来)', async () => {
    let deletes = 0
    server.use(
      mswHttp.get('/api/v1/feed/favorites', () => HttpResponse.json(page([post(1)]))),
      mswHttp.delete('/api/v1/posts/1/favorite', () => {
        deletes += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.post-card__favorite').trigger('click')
    await flushPromises()

    expect(deletes).toBe(1)
    expect(w.findAll('.post-card')).toHaveLength(1)
    expect(w.find('.post-card__favorite').classes()).not.toContain(
      'post-card__favorite--active',
    )
  })
})
