import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { useDiscoveryStore } from '@/stores/discovery'
import { server } from '../support/server'

const card = (id: number) => ({
  user_id: id,
  nickname: `用户${id}`,
  gender: 'female',
  age: 25,
  city: '上海',
  bio: '',
  tags: [],
  photos: [{ id: id * 10, url: `https://cdn/${id}.jpg`, status: 'approved', order: 0 }],
})

function mockCandidates(ids: number[]) {
  server.use(mswHttp.get('/api/v1/discovery/candidates', () => HttpResponse.json(ids.map(card))))
}

describe('discovery store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('拉取候选卡并把第一张设为当前卡', async () => {
    mockCandidates([1, 2])
    const store = useDiscoveryStore()

    await store.loadCandidates()

    expect(store.candidates).toHaveLength(2)
    expect(store.current?.user_id).toBe(1)
    expect(store.exhausted).toBe(false)
  })

  it('滑完所有卡后 exhausted 为真', async () => {
    mockCandidates([1])
    server.use(mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: false })))
    const store = useDiscoveryStore()
    await store.loadCandidates()

    await store.decide('pass')

    expect(store.current).toBeNull()
    expect(store.exhausted).toBe(true)
  })

  it('互相喜欢时记录 matched,且配对对象就是刚滑的人', async () => {
    mockCandidates([7])
    server.use(mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: true })))
    const store = useDiscoveryStore()
    await store.loadCandidates()

    await store.decide('like')

    expect(store.matched?.user_id).toBe(7)
    store.dismissMatched()
    expect(store.matched).toBeNull()
  })

  it('轻封禁(403)时停在当前卡并给出提示', async () => {
    mockCandidates([1])
    server.use(
      mswHttp.post('/api/v1/discovery/swipe', () =>
        HttpResponse.json(
          { code: 40301, message: '账号已被限制,暂时无法滑卡', request_id: 'r' },
          { status: 403 },
        ),
      ),
    )
    const store = useDiscoveryStore()
    await store.loadCandidates()

    await store.decide('like')

    expect(store.error).toBe('账号已被限制,暂时无法滑卡')
    expect(store.current?.user_id).toBe(1) // 没有前进
  })

  it('目标已不存在(404)时跳过该卡', async () => {
    mockCandidates([1, 2])
    server.use(
      mswHttp.post('/api/v1/discovery/swipe', () =>
        HttpResponse.json({ code: 40401, message: '目标用户不存在', request_id: 'r' }, { status: 404 }),
      ),
    )
    const store = useDiscoveryStore()
    await store.loadCandidates()

    await store.decide('like')

    expect(store.current?.user_id).toBe(2) // 前进到下一张
    expect(store.error).toBe('')
  })

  it('限流(429)按后端文案提示', async () => {
    mockCandidates([1])
    server.use(
      mswHttp.post('/api/v1/discovery/swipe', () =>
        HttpResponse.json(
          { code: 42902, message: '操作过于频繁,请稍后再试', request_id: 'r' },
          { status: 429 },
        ),
      ),
    )
    const store = useDiscoveryStore()
    await store.loadCandidates()

    await store.decide('like')

    expect(store.error).toBe('操作过于频繁,请稍后再试')
    expect(store.current?.user_id).toBe(1)
  })

  it('配对列表分页追加,不重置已有数据', async () => {
    const page1 = {
      count: 3,
      next: 'http://x/api/v1/matches?limit=2&offset=2',
      previous: null,
      results: [
        { user_id: 1, im_user_id: 'u1', nickname: 'A', avatar_url: null, matched_at: '2026-10-01T00:00:00Z' },
      ],
    }
    const page2 = {
      count: 3,
      next: null,
      previous: null,
      results: [
        { user_id: 2, im_user_id: 'u2', nickname: 'B', avatar_url: null, matched_at: '2026-10-02T00:00:00Z' },
      ],
    }
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/matches', () => {
        calls += 1
        return HttpResponse.json(calls === 1 ? page1 : page2)
      }),
    )
    const store = useDiscoveryStore()

    await store.loadMatches()
    await store.loadMatches()

    expect(store.matches.map((m) => m.user_id)).toEqual([1, 2])
    expect(store.matchesCount).toBe(3)
    expect(store.matchesLoaded).toBe(true)
  })

  it('unmatch 调 DELETE 并从本地列表移除', async () => {
    const page = {
      count: 1,
      next: null,
      previous: null,
      results: [
        { user_id: 8, im_user_id: 'u8', nickname: 'A', avatar_url: null, matched_at: '2026-10-01T00:00:00Z' },
      ],
    }
    let deleted = ''
    server.use(
      mswHttp.get('/api/v1/matches', () => HttpResponse.json(page)),
      mswHttp.delete('/api/v1/matches/8', () => {
        deleted = '8'
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const store = useDiscoveryStore()
    await store.loadMatches()

    await store.unmatch(8)

    expect(deleted).toBe('8')
    expect(store.matches).toEqual([])
    expect(store.matchesCount).toBe(0)
  })
})
