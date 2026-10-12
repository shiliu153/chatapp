import { flushPromises, mount } from '@vue/test-utils'
import { HttpResponse, http as mswHttp } from 'msw'
import { describe, expect, it } from 'vitest'
import BlockedUsersPage from '@/features/settings/BlockedUsersPage.vue'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

const blocked = (id: number, nickname = '') => ({
  user_id: id,
  nickname,
  avatar_url: null,
  blocked_at: '2026-10-01T00:00:00Z',
})

const page = (results: unknown[], overrides = {}) => ({
  count: results.length,
  next: null,
  previous: null,
  results,
  ...overrides,
})

function mountPage() {
  return mount(BlockedUsersPage, { global: { plugins: [freshPinia()] } })
}

describe('BlockedUsersPage', () => {
  it('渲染黑名单列表', async () => {
    server.use(
      mswHttp.get('/api/v1/blocks', () => HttpResponse.json(page([blocked(1, '小雨')]))),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.findAll('.blocks__item')).toHaveLength(1)
    expect(w.find('.blocks__name').text()).toBe('小雨')
  })

  it('昵称为空时用 user_id 兜底,不显示空白行', async () => {
    server.use(mswHttp.get('/api/v1/blocks', () => HttpResponse.json(page([blocked(7)]))))
    const w = mountPage()
    await flushPromises()

    expect(w.find('.blocks__name').text()).toBe('用户7')
  })

  it('空黑名单展示空态', async () => {
    server.use(mswHttp.get('/api/v1/blocks', () => HttpResponse.json(page([]))))
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-empty').exists()).toBe(true)
    expect(w.find('.blocks__list').exists()).toBe(false)
  })

  it('加载失败展示错误文案', async () => {
    server.use(
      mswHttp.get('/api/v1/blocks', () =>
        HttpResponse.json(
          { code: 50002, message: '服务器开小差了', request_id: 'r' },
          { status: 500 },
        ),
      ),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.blocks__error').text()).toContain('服务器开小差了')
  })

  it('点「解除」调 DELETE 并把该行移出列表', async () => {
    let deleted = ''
    server.use(
      mswHttp.get('/api/v1/blocks', () => HttpResponse.json(page([blocked(1), blocked(2)]))),
      mswHttp.delete('/api/v1/blocks/:id', ({ request }) => {
        deleted = new URL(request.url).pathname
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const w = mountPage()
    await flushPromises()

    await w.findAll('.blocks__unblock')[0].trigger('click')
    await flushPromises()

    expect(deleted).toBe('/api/v1/blocks/1')
    expect(w.findAll('.blocks__item')).toHaveLength(1)
    expect(w.text()).not.toContain('用户1')
  })

  it('解除失败时把后端文案显示出来,该行保留', async () => {
    server.use(
      mswHttp.get('/api/v1/blocks', () => HttpResponse.json(page([blocked(1)]))),
      mswHttp.delete('/api/v1/blocks/1', () =>
        HttpResponse.json(
          { code: 50002, message: '服务器开小差了', request_id: 'r' },
          { status: 500 },
        ),
      ),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.blocks__unblock').trigger('click')
    await flushPromises()

    expect(w.find('.blocks__error').text()).toContain('服务器开小差了')
    expect(w.findAll('.blocks__item')).toHaveLength(1)
  })

  it('还有下一页时展示「加载更多」,点击后追加而不是替换', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/blocks', () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json(page([blocked(1)], { count: 2, next: 'x' }))
          : HttpResponse.json(page([blocked(2)], { count: 2, next: null }))
      }),
    )
    const w = mountPage()
    await flushPromises()
    expect(w.findAll('.blocks__item')).toHaveLength(1)

    await w.find('.blocks__more').trigger('click')
    await flushPromises()

    expect(w.findAll('.blocks__item')).toHaveLength(2)
    expect(w.find('.blocks__footer').exists()).toBe(false) // 拉完就没有了
  })
})
