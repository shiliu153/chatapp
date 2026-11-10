import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import DiscoveryPage from '@/features/discovery/DiscoveryPage.vue'
import type { Candidate } from '@/api/types'
import { server } from '../support/server'

const card: Candidate = {
  user_id: 8,
  nickname: '小雨',
  gender: 'female',
  age: 26,
  city: '上海',
  bio: '',
  tags: [],
  photos: [{ id: 1, url: 'https://cdn/a.jpg', status: 'approved', order: 0 }],
}

const emptyMatches = { count: 0, next_cursor: null, has_more: false, results: [] }

/** 额度默认关闭(like_limit = 0 = 不限),与生产默认一致 */
const unlimitedQuota = { like_limit: 0, likes_used: 0, likes_remaining: null }

type Quota = { like_limit: number; likes_used: number; likes_remaining: number | null }
type Daily = { date: string; candidates: Candidate[] }

/** 今日精选默认给空:区块整块不渲染(它是滑卡之上的加餐,不该污染其它用例的 DOM) */
const emptyDaily: Daily = { date: '2026-11-10', candidates: [] }

/** 筛选面板的默认值来自「想找的人」偏好(GET /users/me 里带回来) */
const me = {
  id: 11,
  user_id: 9,
  phone: '13800000001',
  nickname: '小雨',
  gender: 'female',
  birthday: '2000-01-01',
  age: 26,
  city: '上海',
  bio: '',
  status: 'complete',
  ban_reason: '',
  missing_fields: [],
  tags: [],
  photos: [],
  preference: { target_gender: null, age_min: 25, age_max: 35, city: '上海' },
}

const tags = [
  { id: 1, name: '运动', icon: 'sports' },
  { id: 2, name: '电影', icon: 'movie' },
]

function mountPage(quota: Quota = unlimitedQuota, daily: Daily = emptyDaily) {
  // 页面挂载时会打额度、今日精选、我的资料(筛选默认值)三个请求;
  // 不给 handler 会被 msw 当成未处理请求
  server.use(
    mswHttp.get('/api/v1/discovery/quota', () => HttpResponse.json(quota)),
    mswHttp.get('/api/v1/discovery/daily', () => HttpResponse.json(daily)),
    mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)),
  )
  return mount(DiscoveryPage, {
    global: {
      plugins: [createPinia()],
      stubs: {
        // 把 to 渲染成 data-to:精选卡要断言「点进去是对方资料页」
        RouterLink: { props: ['to'], template: '<a :data-to="JSON.stringify(to)"><slot /></a>' },
      },
    },
  })
}

describe('DiscoveryPage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('没有候选时展示空态', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([])),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-empty').exists()).toBe(true)
  })

  it('有候选时渲染滑卡台', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([card])),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.swipe-deck').exists()).toBe(true)
    expect(w.text()).toContain('小雨')
  })

  it('拉取失败时展示错误态并可重试', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json({ code: 50002, message: '服务器开小差了', request_id: 'r' }, { status: 500 })
          : HttpResponse.json([card])
      }),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.app-error').exists()).toBe(true)
    await w.find('.app-error button').trigger('click')
    await flushPromises()
    expect(w.find('.swipe-deck').exists()).toBe(true)
  })

  it('候选人在线时显示在线光(在线状态接线)', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([card])),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
      mswHttp.get('/api/v1/presence', () =>
        HttpResponse.json({ results: [{ user_id: 8, online: true, last_active_at: null }] }),
      ),
    )
    const w = mountPage()
    await flushPromises()
    // presence 的拉取是「微任务合并 + 异步请求」,多冲几次
    await new Promise((r) => setTimeout(r, 30))
    await flushPromises()

    expect(w.find('.candidate-card__online').exists()).toBe(true)
    w.unmount()
  })

  it('互相喜欢时弹出情感时刻', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([card])),
      mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: true })),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.swipe-deck__like').trigger('click')
    await flushPromises()

    expect(w.find('.match-moment').exists()).toBe(true)
  })

  it('额度开启时显示「今日还可喜欢 N 次」', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([card])),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
    )
    const w = mountPage({ like_limit: 10, likes_used: 7, likes_remaining: 3 })
    await flushPromises()

    expect(w.text()).toContain('今日还可喜欢 3 次')
  })

  it('额度不限(like_limit = 0)时整块不显示', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([card])),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.text()).not.toContain('今日还可喜欢')
  })

  it('滑卡后出现撤销按钮,撤销把卡放回卡堆并提示「已撤销」', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([card])),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
      mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: false })),
      mswHttp.post('/api/v1/discovery/swipe/undo', () =>
        HttpResponse.json({ undone: true, target_user_id: card.user_id }),
      ),
    )
    const w = mountPage()
    await flushPromises()
    expect(w.find('.undo-button').exists()).toBe(false) // 还没划过

    await w.find('.swipe-deck__pass').trigger('click')
    await flushPromises()
    expect(w.find('.undo-button').exists()).toBe(true)
    expect(w.find('.app-empty').exists()).toBe(true) // 只有一张卡,划完即空态

    await w.find('.undo-button').trigger('click')
    await flushPromises()

    expect(w.find('.swipe-deck').exists()).toBe(true) // 卡回来了
    expect(w.text()).toContain('小雨')
    expect(w.text()).toContain('已撤销')
    expect(w.find('.undo-button').exists()).toBe(false) // 撤销后收起
    w.unmount()
  })

  it('撤销被拒(40003)时提示「没有可撤销的操作」并收起按钮', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([card])),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
      mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: false })),
      mswHttp.post('/api/v1/discovery/swipe/undo', () =>
        HttpResponse.json(
          { code: 40003, message: '没有可撤销的滑卡', request_id: 'r' },
          { status: 400 },
        ),
      ),
    )
    const w = mountPage()
    await flushPromises()
    await w.find('.swipe-deck__pass').trigger('click')
    await flushPromises()

    await w.find('.undo-button').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('没有可撤销的操作')
    expect(w.find('.undo-button').exists()).toBe(false)
    w.unmount()
  })

  it('额度用完(429 + 42904)时置灰「喜欢」并提示明天再来', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([card, card])),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
      mswHttp.post('/api/v1/discovery/swipe', () =>
        HttpResponse.json(
          { code: 42904, message: '今天的喜欢次数已用完', request_id: 'r' },
          { status: 429, headers: { 'Retry-After': '60' } },
        ),
      ),
    )
    const w = mountPage({ like_limit: 5, likes_used: 4, likes_remaining: 1 })
    await flushPromises()

    await w.find('.swipe-deck__like').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('今日喜欢次数已用完,明天再来')
    expect(w.find('.swipe-deck__like').attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('今日还可喜欢 0 次')
    w.unmount()
  })

  it('显示喜欢我的人入口与数量', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([card])),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
      mswHttp.get('/api/v1/discovery/likes/count', () => HttpResponse.json({ count: 3 })),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.top-entry').exists()).toBe(true)
    expect(w.text()).toContain('喜欢我的人')
    expect(w.text()).toContain('3')
  })

  it('显示谁看过我入口与数量', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([card])),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
      mswHttp.get('/api/v1/discovery/visits/count', () => HttpResponse.json({ count: 5 })),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.findAll('.top-entry')).toHaveLength(2)
    expect(w.text()).toContain('谁看过我')
    expect(w.text()).toContain('5')
  })

  it('今日精选渲染 6 张卡,点一张进对方资料页', async () => {
    const dailyCards = Array.from({ length: 6 }, (_, i) => ({
      ...card,
      user_id: 100 + i,
      nickname: `精选${i}`,
    }))
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([card])),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
    )
    const w = mountPage(unlimitedQuota, { date: '2026-11-10', candidates: dailyCards })
    await flushPromises()

    expect(w.find('.daily-strip').exists()).toBe(true)
    expect(w.text()).toContain('今日精选')
    const items = w.findAll('.daily-strip__card')
    expect(items).toHaveLength(6)
    // 链接指向对方资料页(路由 /users/:id)
    expect(items[0].attributes('data-to')).toContain('"id":100')
    expect(items[5].attributes('data-to')).toContain('"id":105')
    w.unmount()
  })

  it('今日精选为空时整块不渲染', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([card])),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.daily-strip').exists()).toBe(false)
    expect(w.text()).not.toContain('今日精选')
    w.unmount()
  })

  it('打开筛选 → 只改城市 → 应用:请求带 city,不多发没改的字段', async () => {
    const queries: URLSearchParams[] = []
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', ({ request }) => {
        queries.push(new URL(request.url).searchParams)
        return HttpResponse.json([card])
      }),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
      mswHttp.get('/api/v1/users/tags', () => HttpResponse.json(tags)),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.discovery__filter').trigger('click')
    await flushPromises()
    // 面板默认值 = 偏好:年龄 25–35、城市「上海」
    const inputs = w.findAll('.filter-panel__body input')
    expect((inputs[0].element as HTMLInputElement).value).toBe('25')
    await inputs[2].setValue('杭州')
    await w.find('.filter-panel__apply').trigger('click')
    await flushPromises()

    const last = queries[queries.length - 1]
    expect(last.get('city')).toBe('杭州')
    // 覆盖语义:没改的年龄区间继续沿用偏好,不能当成筛选发出去
    expect(last.has('age_min')).toBe(false)
    expect(last.has('age_max')).toBe(false)
    expect(last.has('tag_ids')).toBe(false)
    expect(w.find('.filter-panel').exists()).toBe(false) // 应用后关面板
    expect(w.find('.discovery__filter').classes()).toContain('discovery__filter--active')
    w.unmount()
  })

  it('筛选后候选为空:给「这个范围里暂时没人」的空态,不崩', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => {
        calls += 1
        return HttpResponse.json(calls === 1 ? [card] : [])
      }),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
      mswHttp.get('/api/v1/users/tags', () => HttpResponse.json(tags)),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.discovery__filter').trigger('click')
    await flushPromises()
    await w.findAll('.filter-panel__body input')[2].setValue('杭州')
    await w.find('.filter-panel__apply').trigger('click')
    await flushPromises()

    expect(w.find('.app-empty').exists()).toBe(true)
    expect(w.text()).toContain('这个范围里暂时没人')
    expect(w.find('.discovery__filter').classes()).toContain('discovery__filter--active')
    w.unmount()
  })

  it('「重置」后请求不带筛选参数,按钮回到未激活态', async () => {
    const queries: URLSearchParams[] = []
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', ({ request }) => {
        queries.push(new URL(request.url).searchParams)
        return HttpResponse.json([card])
      }),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
      mswHttp.get('/api/v1/users/tags', () => HttpResponse.json(tags)),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.discovery__filter').trigger('click')
    await flushPromises()
    await w.findAll('.filter-panel__body input')[2].setValue('杭州')
    await w.find('.filter-panel__apply').trigger('click')
    await flushPromises()
    expect(queries[queries.length - 1].get('city')).toBe('杭州')

    await w.find('.discovery__filter').trigger('click')
    await flushPromises()
    await w.find('.filter-panel__reset').trigger('click')
    await flushPromises()

    const last = queries[queries.length - 1]
    expect(last.get('city')).toBeNull()
    expect(last.has('age_min')).toBe(false)
    expect(w.find('.discovery__filter').classes()).not.toContain('discovery__filter--active')
    w.unmount()
  })
})
