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
  created_at: '2026-10-01T10:00:00Z',
})

const page = (results: unknown[], overrides = {}) => ({
  count: results.length,
  next: null,
  previous: null,
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
        HttpResponse.json(page([post(1)], { count: 2, next: 'x' })),
      ),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.square__more').exists()).toBe(true)
  })
})
