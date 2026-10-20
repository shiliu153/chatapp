import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import LikesPage from '@/features/discovery/LikesPage.vue'
import { server } from '../support/server'

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

const page = (results: unknown[]) => ({
  count: results.length,
  next: null,
  previous: null,
  results,
})

function mountPage() {
  return mount(LikesPage, {
    global: {
      plugins: [createPinia()],
      stubs: {
        RouterLink: { template: '<a><slot /></a>' },
      },
    },
  })
}

describe('LikesPage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('空态', async () => {
    server.use(mswHttp.get('/api/v1/discovery/likes', () => HttpResponse.json(page([]))))
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-empty').exists()).toBe(true)
    expect(w.text()).toContain('还没有人喜欢你')
  })

  it('渲染列表并回喜欢', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/likes', () =>
        HttpResponse.json(page([like(1), like(2)])),
      ),
      mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: true })),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(page([]))),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('用户1')
    await w.find('.likes__accept').trigger('click')
    await flushPromises()

    expect(w.find('.match-moment').exists()).toBe(true)
    expect(w.findAll('.likes__row')).toHaveLength(1)
    expect(w.text()).toContain('用户2')
  })

  it('加载失败展示错误并可重试', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/discovery/likes', () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json(
              { code: 50002, message: '服务器开小差了', request_id: 'r' },
              { status: 500 },
            )
          : HttpResponse.json(page([like(1)]))
      }),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-error').exists()).toBe(true)
    await w.find('.app-error button').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('用户1')
  })
})
