import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import NotificationsPage from '@/features/notifications/NotificationsPage.vue'
import { server } from '../support/server'

const push = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({ push }),
}))

const page = (results: unknown[], nextCursor: string | null = null) => ({
  count: results.length,
  next_cursor: nextCursor,
  has_more: nextCursor !== null,
  results,
})

const notification = (
  id: number,
  overrides: Partial<{
    is_read: boolean
    text: string
    target: { kind: string; id: number | null }
    actor: { id: number; nickname: string; avatar: string | null } | null
  }> = {},
) => ({
  id,
  kind: 'post_like',
  text: `通知${id}`,
  is_read: false,
  created_at: '2026-11-06T12:30:00+08:00',
  actor: { id: 7, nickname: '小明', avatar: null },
  target: { kind: 'post', id: 9 },
  ...overrides,
})

function mountPage() {
  return mount(NotificationsPage, {
    global: {
      plugins: [createPinia()],
      stubs: {
        RouterLink: { template: '<a><slot /></a>' },
      },
    },
  })
}

describe('NotificationsPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    push.mockReset()
  })

  it('空态', async () => {
    server.use(mswHttp.get('/api/v1/notifications', () => HttpResponse.json(page([]))))
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-empty').exists()).toBe(true)
    expect(w.text()).toContain('还没有通知')
  })

  it('渲染正文/时间/未读点,已读行无未读点', async () => {
    server.use(
      mswHttp.get('/api/v1/notifications', () =>
        HttpResponse.json(
          page([
            notification(2, { text: '小明 赞了你的动态' }),
            notification(1, { text: '小红 评论了你的动态', is_read: true }),
          ]),
        ),
      ),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('小明 赞了你的动态')
    expect(w.text()).toContain('小红 评论了你的动态')
    expect(w.findAll('.notifications__row')).toHaveLength(2)
    expect(w.findAll('.notifications__dot')).toHaveLength(1)
  })

  it('点一条 → 标已读并跳到动态详情', async () => {
    let body: unknown = null
    server.use(
      mswHttp.get('/api/v1/notifications', () =>
        HttpResponse.json(page([notification(2)])),
      ),
      mswHttp.post('/api/v1/notifications/read', async ({ request }) => {
        body = await request.json()
        return new HttpResponse(null, { status: 204 })
      }),
      mswHttp.get('/api/v1/notifications/unread_count', () =>
        HttpResponse.json({ unread: 0 }),
      ),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.notifications__row').trigger('click')
    await flushPromises()

    expect(body).toEqual({ ids: [2] })
    expect(push).toHaveBeenCalledWith({ name: 'post-detail', params: { id: '9' } })
    expect(w.findAll('.notifications__dot')).toHaveLength(0)
  })

  it('user 目标 → 跳到与对方聊天;none 目标 → 只标已读', async () => {
    server.use(
      mswHttp.get('/api/v1/notifications', () =>
        HttpResponse.json(
          page([
            notification(3, {
              text: '你们互相喜欢',
              target: { kind: 'user', id: 9 },
              actor: null,
            }),
            notification(2, {
              text: '你的举报已处理',
              target: { kind: 'none', id: null },
              actor: null,
            }),
          ]),
        ),
      ),
      mswHttp.post('/api/v1/notifications/read', () => new HttpResponse(null, { status: 204 })),
      mswHttp.get('/api/v1/notifications/unread_count', () =>
        HttpResponse.json({ unread: 0 }),
      ),
    )
    const w = mountPage()
    await flushPromises()

    const rows = w.findAll('.notifications__row')
    await rows[0].trigger('click')
    await flushPromises()
    expect(push).toHaveBeenLastCalledWith({ name: 'chat', params: { peerId: 'u9' } })

    await rows[1].trigger('click')
    await flushPromises()
    expect(push).toHaveBeenCalledTimes(1)
  })

  it('全部已读按钮:发 all=true 并清空未读点', async () => {
    let body: unknown = null
    server.use(
      mswHttp.get('/api/v1/notifications', () =>
        HttpResponse.json(page([notification(2), notification(1)])),
      ),
      mswHttp.post('/api/v1/notifications/read', async ({ request }) => {
        body = await request.json()
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.notifications__mark-all').trigger('click')
    await flushPromises()

    expect(body).toEqual({ all: true })
    expect(w.findAll('.notifications__dot')).toHaveLength(0)
    expect(w.find('.notifications__mark-all').exists()).toBe(false)
  })

  it('加载失败展示错误并可重试', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/notifications', () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json(
              { code: 50002, message: '服务器开小差了', request_id: 'r' },
              { status: 500 },
            )
          : HttpResponse.json(page([notification(2)]))
      }),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-error').exists()).toBe(true)
    await w.find('.app-error button').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('通知2')
  })
})
