import { flushPromises, mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { HttpResponse, delay, http as mswHttp } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import StatsPage from '@/features/stats/StatsPage.vue'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

const reportOf = (period: string, over: Record<string, unknown> = {}) => ({
  period,
  start: '2026-11-09',
  end: '2026-11-15',
  matches: 2,
  likes_given: 14,
  likes_received: 9,
  visits: 6,
  posts: 3,
  post_likes: 11,
  new_followers: 1,
  ...over,
})

function mountPage() {
  return mount(StatsPage, {
    global: { plugins: [freshPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

/** 卡片:每张卡一段数字 + 一段中文标签。 */
function cards(w: ReturnType<typeof mountPage>) {
  return w.findAll('.stats__grid .app-card').map((card) => ({
    value: card.find('.stats__value').text(),
    label: card.find('.stats__label').text(),
  }))
}

describe('StatsPage', () => {
  afterEach(() => vi.restoreAllMocks())

  it('七张数字卡:数字 + 中文标签,顺序固定', async () => {
    server.use(mswHttp.get('/api/v1/stats/me', () => HttpResponse.json(reportOf('week'))))
    const w = mountPage()
    await flushPromises()

    expect(cards(w)).toEqual([
      { value: '2', label: '新的配对' },
      { value: '14', label: '喜欢给出' },
      { value: '9', label: '喜欢收到' },
      { value: '6', label: '访客' },
      { value: '3', label: '动态' },
      { value: '11', label: '动态获赞' },
      { value: '1', label: '新粉丝' },
    ])
  })

  it('顶部显示周期标签 start ~ end', async () => {
    server.use(mswHttp.get('/api/v1/stats/me', () => HttpResponse.json(reportOf('week'))))
    const w = mountPage()
    await flushPromises()

    expect(w.find('.stats__range').text()).toBe('2026-11-09 ~ 2026-11-15')
  })

  it('数字为 0 时正常显示 0(不是空白)', async () => {
    server.use(
      mswHttp.get('/api/v1/stats/me', () =>
        HttpResponse.json(
          reportOf('week', {
            matches: 0,
            likes_given: 0,
            likes_received: 0,
            visits: 0,
            posts: 0,
            post_likes: 0,
            new_followers: 0,
          }),
        ),
      ),
    )
    const w = mountPage()
    await flushPromises()

    const values = w.findAll('.stats__value').map((node) => node.text())
    expect(values).toEqual(['0', '0', '0', '0', '0', '0', '0'])
  })

  it('默认选中「周」;点「月」重新请求并换数字与周期标签', async () => {
    const requested: (string | null)[] = []
    server.use(
      mswHttp.get('/api/v1/stats/me', ({ request }) => {
        const period = new URL(request.url).searchParams.get('period')
        requested.push(period)
        if (period === 'month') {
          return HttpResponse.json(
            reportOf('month', { start: '2026-11-01', end: '2026-11-30', matches: 7 }),
          )
        }
        return HttpResponse.json(reportOf(period ?? 'week'))
      }),
    )
    const w = mountPage()
    await flushPromises()

    const segments = w.findAll('.app-segmented__segment')
    expect(segments.map((node) => node.text())).toEqual(['周', '月', '年'])
    expect(segments[0].attributes('aria-pressed')).toBe('true')
    expect(segments[1].attributes('aria-pressed')).toBe('false')

    await segments[1].trigger('click')
    await flushPromises()

    expect(requested).toEqual(['week', 'month'])
    expect(w.findAll('.app-segmented__segment')[1].attributes('aria-pressed')).toBe('true')
    expect(w.find('.stats__range').text()).toBe('2026-11-01 ~ 2026-11-30')
    expect(cards(w)[0]).toEqual({ value: '7', label: '新的配对' })
  })

  it('再点当前周期不重复请求', async () => {
    const requested: (string | null)[] = []
    server.use(
      mswHttp.get('/api/v1/stats/me', ({ request }) => {
        requested.push(new URL(request.url).searchParams.get('period'))
        return HttpResponse.json(reportOf('week'))
      }),
    )
    const w = mountPage()
    await flushPromises()

    await w.findAll('.app-segmented__segment')[0].trigger('click')
    await flushPromises()

    expect(requested).toEqual(['week'])
  })

  it('加载中显示骨架(既有 AppSkeleton)', async () => {
    server.use(
      mswHttp.get('/api/v1/stats/me', async () => {
        await delay(30)
        return HttpResponse.json(reportOf('week'))
      }),
    )
    const w = mountPage()
    await nextTick()

    expect(w.findAll('.app-skeleton').length).toBeGreaterThan(0)
    expect(w.findAll('.stats__value')).toHaveLength(0)

    await new Promise((resolve) => setTimeout(resolve, 60))
    await flushPromises()

    expect(w.findAll('.app-skeleton')).toHaveLength(0)
    expect(w.findAll('.stats__value')).toHaveLength(7)
  })

  it('失败态显示既有错误组件,点重试后成功展示数字', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/stats/me', () => {
        calls += 1
        if (calls === 1) {
          return HttpResponse.json(
            { code: 50002, message: '服务器开小差了', request_id: 'r' },
            { status: 500 },
          )
        }
        return HttpResponse.json(reportOf('week'))
      }),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-error').text()).toContain('服务器开小差了')
    expect(w.findAll('.stats__value')).toHaveLength(0)

    await w.find('.app-error button').trigger('click')
    await flushPromises()

    expect(calls).toBe(2)
    expect(w.find('.app-error').exists()).toBe(false)
    expect(w.findAll('.stats__value')).toHaveLength(7)
  })

  it('未登录走统一 401 通道:刷新失败后显示后端文案,卡片不渲染', async () => {
    server.use(
      mswHttp.get('/api/v1/stats/me', () =>
        HttpResponse.json({ code: 401, message: '登录已过期', request_id: 'r' }, { status: 401 }),
      ),
      mswHttp.post('/api/v1/auth/token/refresh', () =>
        HttpResponse.json({ code: 401, message: '登录已过期', request_id: 'r' }, { status: 401 }),
      ),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-error').text()).toContain('登录已过期')
    expect(w.findAll('.stats__value')).toHaveLength(0)
  })
})
