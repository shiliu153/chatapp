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

function mountPage(quota: Quota = unlimitedQuota) {
  // 每个用例都会打一次额度对账(页面挂载时),不给 handler 会被 msw 当成未处理请求
  server.use(mswHttp.get('/api/v1/discovery/quota', () => HttpResponse.json(quota)))
  return mount(DiscoveryPage, {
    global: {
      plugins: [createPinia()],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
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
})
