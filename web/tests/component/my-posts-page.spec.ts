import { flushPromises, mount } from '@vue/test-utils'
import { HttpResponse, http as mswHttp } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import MyPostsPage from '@/features/square/MyPostsPage.vue'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'
import type { Post } from '@/api/types'

const post = (id: number): Post => ({
  id,
  author: { user_id: 9, nickname: '我自己', avatar_url: null },
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
  return mount(MyPostsPage, {
    global: { plugins: [freshPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

describe('MyPostsPage', () => {
  it('拉的是「我的动态」接口,不是广场流', async () => {
    let path = ''
    server.use(
      mswHttp.get('/api/v1/posts/mine', ({ request }) => {
        path = new URL(request.url).pathname
        return HttpResponse.json(page([post(1)]))
      }),
    )
    const w = mountPage()
    await flushPromises()

    expect(path).toBe('/api/v1/posts/mine')
    expect(w.findAll('.post-card')).toHaveLength(1)
  })

  it('没有动态时展示空态', async () => {
    server.use(mswHttp.get('/api/v1/posts/mine', () => HttpResponse.json(page([]))))
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-empty').exists()).toBe(true)
    expect(w.text()).toContain('还没发过动态')
  })

  it('加载失败展示错误态,重试后恢复', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/posts/mine', () => {
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

  it('删除要先二次确认:点取消不发请求', async () => {
    let deletes = 0
    server.use(
      mswHttp.get('/api/v1/posts/mine', () => HttpResponse.json(page([post(1)]))),
      mswHttp.delete('/api/v1/posts/:id', () => {
        deletes += 1
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const w = mountPage()
    await flushPromises()

    await w.find('.post-card__delete').trigger('click')
    await flushPromises()

    expect(confirmSpy).toHaveBeenCalledOnce()
    expect(deletes).toBe(0)
    expect(w.findAll('.post-card')).toHaveLength(1)
  })

  it('确认后删除:列表里移除该条', async () => {
    server.use(
      mswHttp.get('/api/v1/posts/mine', () => HttpResponse.json(page([post(1), post(2)]))),
      mswHttp.delete('/api/v1/posts/1', () => new HttpResponse(null, { status: 204 })),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const w = mountPage()
    await flushPromises()
    expect(w.findAll('.post-card')).toHaveLength(2)

    await w.findAll('.post-card__delete')[0].trigger('click')
    await flushPromises()

    expect(w.findAll('.post-card')).toHaveLength(1)
    expect(w.text()).not.toContain('第 1 条')
  })

  it('删除失败时把后端文案显示出来,不静默', async () => {
    server.use(
      mswHttp.get('/api/v1/posts/mine', () => HttpResponse.json(page([post(1)]))),
      mswHttp.delete('/api/v1/posts/1', () =>
        HttpResponse.json(
          { code: 40301, message: '只能删除自己的动态', request_id: 'r' },
          { status: 403 },
        ),
      ),
    )
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    const w = mountPage()
    await flushPromises()

    await w.find('.post-card__delete').trigger('click')
    await flushPromises()

    expect(w.find('.my-posts__notice').text()).toContain('只能删除自己的动态')
    expect(w.findAll('.post-card')).toHaveLength(1)
  })

  it('举报走 /posts/{id}/report 并给出回执', async () => {
    let body: unknown = null
    server.use(
      mswHttp.get('/api/v1/posts/mine', () => HttpResponse.json(page([post(7)]))),
      mswHttp.post('/api/v1/posts/7/report', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({}, { status: 201 })
      }),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.post-card__report').trigger('click')
    await flushPromises()
    // 弹窗里选一个理由并提交
    await w.find('.report-dialog__reason').trigger('click')
    await w.find('.report-dialog__submit').trigger('click')
    await flushPromises()

    expect(body).toMatchObject({ type: 'harassment' })
    expect(w.find('.my-posts__notice').text()).toContain('已收到举报')
  })

  afterEach(() => vi.restoreAllMocks())
})
