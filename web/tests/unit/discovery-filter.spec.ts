import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { filtersToParams } from '@/api/discovery'
import { useDiscoveryStore } from '@/stores/discovery'
import { server } from '../support/server'

const card = (id: number) => ({
  user_id: id,
  nickname: `用户${id}`,
  gender: 'female',
  age: 25,
  city: '杭州',
  bio: '',
  tags: [],
  photos: [{ id: id * 10, url: `https://cdn/${id}.jpg`, status: 'approved', order: 0 }],
})

/** 记下候选接口收到的查询串:每个用例自己断言「有没有带上、带了哪些」参数 */
function recordCandidateQueries(ids: number[] = [1]): URLSearchParams[] {
  const queries: URLSearchParams[] = []
  server.use(
    mswHttp.get('/api/v1/discovery/candidates', ({ request }) => {
      queries.push(new URL(request.url).searchParams)
      return HttpResponse.json(ids.map(card))
    }),
  )
  return queries
}

describe('discovery store · 临时筛选(批次 S)', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('应用筛选后候选请求带上四个筛选参数', async () => {
    const queries = recordCandidateQueries()
    const store = useDiscoveryStore()

    await store.applyFilters({ age_min: 25, age_max: 30, city: '杭州', tag_ids: [3, 1] })

    expect(queries).toHaveLength(1)
    expect(queries[0].get('age_min')).toBe('25')
    expect(queries[0].get('age_max')).toBe('30')
    expect(queries[0].get('city')).toBe('杭州')
    expect(queries[0].get('tag_ids')).toBe('3,1')
  })

  it('只改城市时只发 city(覆盖语义:年龄区间继续沿用偏好)', async () => {
    const queries = recordCandidateQueries()
    const store = useDiscoveryStore()

    await store.applyFilters({ city: '杭州' })

    expect(queries[0].get('city')).toBe('杭州')
    expect(queries[0].has('age_min')).toBe(false)
    expect(queries[0].has('age_max')).toBe(false)
    expect(queries[0].has('tag_ids')).toBe(false)
  })

  it('重置后请求不带任何筛选参数,并回到未筛选态', async () => {
    const queries = recordCandidateQueries()
    const store = useDiscoveryStore()
    await store.applyFilters({ city: '杭州', age_min: 30, age_max: 40 })
    expect(store.filtersActive).toBe(true)

    await store.resetFilters()

    expect(store.filtersActive).toBe(false)
    expect(store.filters).toEqual({})
    const last = queries[queries.length - 1]
    expect(last.get('city')).toBeNull()
    expect(last.get('age_min')).toBeNull()
    expect(last.get('age_max')).toBeNull()
    expect(last.get('tag_ids')).toBeNull()
    expect(last.get('limit')).toBe('10') // 只留分页参数
  })

  it('没筛选时 filtersActive 为假,空串/空数组不算筛选', async () => {
    recordCandidateQueries()
    const store = useDiscoveryStore()
    await store.loadCandidates()

    expect(store.filtersActive).toBe(false)

    await store.applyFilters({ city: '   ', tag_ids: [] })

    expect(store.filtersActive).toBe(false)
  })
})

describe('discovery store · 今日精选(§3.11)', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('按包装对象解析 daily(不是裸数组)', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/daily', ({ request }) => {
        expect(new URL(request.url).searchParams.get('limit')).toBe('6')
        return HttpResponse.json({
          date: '2026-11-10',
          candidates: [card(1), card(2), card(3), card(4), card(5), card(6)],
        })
      }),
    )
    const store = useDiscoveryStore()

    await store.loadDaily()

    expect(store.daily?.date).toBe('2026-11-10')
    expect(store.dailyCandidates).toHaveLength(6)
  })

  it('拿到空 candidates 时 dailyCandidates 为空数组(区块整块不渲染)', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/daily', () =>
        HttpResponse.json({ date: '2026-11-10', candidates: [] }),
      ),
    )
    const store = useDiscoveryStore()

    await store.loadDaily()

    expect(store.dailyCandidates).toEqual([])
  })

  it('拉失败不抛异常,只是没有精选可渲染', async () => {
    server.use(
      mswHttp.get('/api/v1/discovery/daily', () =>
        HttpResponse.json({ code: 50002, message: '服务器开小差了', request_id: 'r' }, { status: 500 }),
      ),
    )
    const store = useDiscoveryStore()

    await expect(store.loadDaily()).resolves.toBeUndefined()
    expect(store.daily).toBeNull()
    expect(store.dailyCandidates).toEqual([])
  })
})

describe('filtersToParams', () => {
  it('只翻译真正有值的字段', () => {
    expect(filtersToParams({})).toEqual({})
    expect(filtersToParams({ city: '', tag_ids: [] })).toEqual({})
    expect(filtersToParams({ city: ' 杭州 ' })).toEqual({ city: '杭州' })
    expect(filtersToParams({ age_min: 20, age_max: 30, tag_ids: [2, 5] })).toEqual({
      age_min: 20,
      age_max: 30,
      tag_ids: '2,5',
    })
  })
})
