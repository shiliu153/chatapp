import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, delay, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { STAT_CARDS, STATS_PERIODS, useStatsStore } from '@/stores/stats'
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

/** 记录每次请求的 `period` 查询参数,用来断言「切换即重新请求」。 */
function trackPeriods() {
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
  return requested
}

describe('stats store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('默认周期是周,首次请求带 period=week', async () => {
    const requested = trackPeriods()
    const store = useStatsStore()

    expect(store.period).toBe('week')
    await store.load()

    expect(requested).toEqual(['week'])
    expect(store.loading).toBe(false)
    expect(store.error).toBe('')
  })

  it('字段映射:七张卡按固定顺序给中文标签与数字', async () => {
    trackPeriods()
    const store = useStatsStore()

    await store.load()

    expect(store.cards.map((card) => card.label)).toEqual([
      '新的配对',
      '喜欢给出',
      '喜欢收到',
      '访客',
      '动态',
      '动态获赞',
      '新粉丝',
    ])
    expect(store.cards.map((card) => card.value)).toEqual([2, 14, 9, 6, 3, 11, 1])
    // 顺序与标签目录是同一份事实来源
    expect(store.cards.map((card) => card.key)).toEqual(STAT_CARDS.map((card) => card.key))
  })

  it('数字为 0 时保留 0(不是 undefined / null)', async () => {
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
    const store = useStatsStore()

    await store.load()

    expect(store.cards.map((card) => card.value)).toEqual([0, 0, 0, 0, 0, 0, 0])
    for (const card of store.cards) {
      expect(card.value).toBe(0)
      expect(card.value).not.toBeUndefined()
    }
  })

  it('周期标签是 start ~ end(含首含尾的日期串)', async () => {
    trackPeriods()
    const store = useStatsStore()

    await store.load()

    expect(store.rangeText).toBe('2026-11-09 ~ 2026-11-15')
  })

  it('切换周期即重新请求,数字与周期标签一起换', async () => {
    const requested = trackPeriods()
    const store = useStatsStore()
    await store.load()

    await store.setPeriod('month')

    expect(requested).toEqual(['week', 'month'])
    expect(store.period).toBe('month')
    expect(store.rangeText).toBe('2026-11-01 ~ 2026-11-30')
    expect(store.cards[0].value).toBe(7)
  })

  it('同值重复设置不发请求', async () => {
    const requested = trackPeriods()
    const store = useStatsStore()
    await store.load()

    await store.setPeriod('week')

    expect(requested).toEqual(['week'])
  })

  it('切换周期先清旧数字:不会出现「月」的选中态配「周」的数字', async () => {
    trackPeriods()
    const store = useStatsStore()
    await store.load()
    expect(store.report).not.toBeNull()

    const pending = store.setPeriod('month')
    // 请求还没回来:旧报告已作废
    expect(store.report).toBeNull()
    expect(store.rangeText).toBe('')
    expect(store.cards.map((card) => card.value)).toEqual([0, 0, 0, 0, 0, 0, 0])
    await pending
  })

  it('失败时给出中文文案并向上抛,报告保持为空', async () => {
    server.use(
      mswHttp.get('/api/v1/stats/me', () =>
        HttpResponse.json(
          { code: 40005, message: '统计周期只能是 week / month / year', request_id: 'r' },
          { status: 400 },
        ),
      ),
    )
    const store = useStatsStore()

    await expect(store.load()).rejects.toMatchObject({ code: 40005 })
    expect(store.error).toBe('统计周期只能是 week / month / year')
    expect(store.report).toBeNull()
    expect(store.loading).toBe(false)
  })

  it('过期响应被丢弃:先发后到的旧周期结果不覆盖新周期', async () => {
    server.use(
      mswHttp.get('/api/v1/stats/me', async ({ request }) => {
        const period = new URL(request.url).searchParams.get('period')
        if (period === 'week') {
          await delay(50)
          return HttpResponse.json(reportOf('week', { matches: 1 }))
        }
        return HttpResponse.json(reportOf('month', { matches: 5 }))
      }),
    )
    const store = useStatsStore()

    const stale = store.load() // week,慢
    await store.setPeriod('month') // month,快
    await stale

    expect(store.report?.period).toBe('month')
    expect(store.cards[0].value).toBe(5)
    expect(store.loading).toBe(false)
  })

  it('周期选项就是验收要求的三态', () => {
    expect(STATS_PERIODS.map((item) => item.value)).toEqual(['week', 'month', 'year'])
    expect(STATS_PERIODS.map((item) => item.label)).toEqual(['周', '月', '年'])
  })
})
