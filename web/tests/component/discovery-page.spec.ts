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

const emptyMatches = { count: 0, next: null, previous: null, results: [] }

function mountPage() {
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

  it('显示喜欢我的人入口与数量', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json([card])),
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(emptyMatches)),
      mswHttp.get('/api/v1/discovery/likes/count', () => HttpResponse.json({ count: 3 })),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.likes-entry').exists()).toBe(true)
    expect(w.text()).toContain('3')
  })
})
