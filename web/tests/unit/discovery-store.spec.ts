import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { UNDO_WINDOW_MS, useDiscoveryStore } from '@/stores/discovery'
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

  it('配对成功时记录共同标签;关掉配对动效即清空', async () => {
    mockCandidates([7])
    server.use(
      mswHttp.post('/api/v1/discovery/swipe', () =>
        HttpResponse.json({
          matched: true,
          shared_tags: [
            { id: 1, name: '运动', icon: 'sports' },
            { id: 3, name: '电影', icon: 'movie' },
          ],
        }),
      ),
    )
    const store = useDiscoveryStore()
    await store.loadCandidates()

    await store.decide('like')

    expect(store.matchedSharedTags.map((tag) => tag.name)).toEqual(['运动', '电影'])
    store.dismissMatched()
    expect(store.matchedSharedTags).toEqual([])
  })

  it('未配对时共同标签保持为空', async () => {
    mockCandidates([7])
    server.use(mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: false })))
    const store = useDiscoveryStore()
    await store.loadCandidates()

    await store.decide('pass')

    expect(store.matchedSharedTags).toEqual([])
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

  it('配对列表按游标翻页追加,不重置已有数据', async () => {
    const page1 = {
      count: 3,
      next_cursor: 'matches-page-2',
      has_more: true,
      results: [
        { user_id: 1, im_user_id: 'u1', nickname: 'A', avatar_url: null, matched_at: '2026-10-01T00:00:00Z' },
      ],
    }
    const page2 = {
      count: 3,
      next_cursor: null,
      has_more: false,
      results: [
        { user_id: 2, im_user_id: 'u2', nickname: 'B', avatar_url: null, matched_at: '2026-10-02T00:00:00Z' },
      ],
    }
    let calls = 0
    let secondQuery = ''
    server.use(
      mswHttp.get('/api/v1/matches', ({ request }) => {
        calls += 1
        if (calls > 1) secondQuery = new URL(request.url).search
        return HttpResponse.json(calls === 1 ? page1 : page2)
      }),
    )
    const store = useDiscoveryStore()

    await store.loadMatches()
    await store.loadMatches()

    expect(store.matches.map((m) => m.user_id)).toEqual([1, 2])
    expect(store.matchesCount).toBe(3)
    expect(store.matchesLoaded).toBe(true)
    expect(secondQuery).toContain('before=matches-page-2')
  })

  it('unmatch 调 DELETE 并从本地列表移除', async () => {
    const page = {
      count: 1,
      next_cursor: null,
      has_more: false,
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

/**
 * 批次 O:撤销上一次滑卡(§3.9)与每日喜欢额度(§3.10)。
 *
 * 契约要点:撤销只有「30 秒内的最近一次、且未产生配对」才成立,失败一律 `400` + `40003`;
 * 额度 `like_limit = 0` 表示不限,页面整块不显示。
 */
describe('discovery store:撤销与每日额度', () => {
  beforeEach(() => setActivePinia(createPinia()))

  const unlimited = { like_limit: 0, likes_used: 0, likes_remaining: null }

  function mockQuota(quota: {
    like_limit: number
    likes_used: number
    likes_remaining: number | null
  }): void {
    server.use(mswHttp.get('/api/v1/discovery/quota', () => HttpResponse.json(quota)))
  }

  function mockSwipeOk(): void {
    server.use(mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: false })))
  }

  it('额度开启时给出「今日还可喜欢 N 次」', async () => {
    mockCandidates([1])
    mockQuota({ like_limit: 10, likes_used: 3, likes_remaining: 7 })
    const store = useDiscoveryStore()

    await store.loadQuota()

    expect(store.quotaVisible).toBe(true)
    expect(store.likesRemaining).toBe(7)
    expect(store.quotaText).toBe('今日还可喜欢 7 次')
    expect(store.likeBlocked).toBe(false)
  })

  it('like_limit = 0(不限)时整块不显示', async () => {
    mockCandidates([1])
    mockQuota(unlimited)
    const store = useDiscoveryStore()

    await store.loadQuota()

    expect(store.quotaVisible).toBe(false)
    expect(store.likesRemaining).toBeNull()
    expect(store.quotaText).toBe('')
    expect(store.likeBlocked).toBe(false)
  })

  it('额度接口拿不到时不显示、也不挡滑卡', async () => {
    mockCandidates([1])
    server.use(
      mswHttp.get('/api/v1/discovery/quota', () =>
        HttpResponse.json({ code: 50002, message: '服务器开小差了', request_id: 'r' }, { status: 500 }),
      ),
    )
    const store = useDiscoveryStore()

    await store.loadQuota()

    expect(store.quota).toBeNull()
    expect(store.quotaVisible).toBe(false)
    expect(store.likeBlocked).toBe(false)
  })

  it('成功 like 本地递减一次,不额外多打额度接口', async () => {
    mockCandidates([1])
    mockSwipeOk()
    mockQuota({ like_limit: 10, likes_used: 3, likes_remaining: 7 })
    let quotaCalls = 0
    server.use(
      mswHttp.get('/api/v1/discovery/quota', () => {
        quotaCalls += 1
        return HttpResponse.json({ like_limit: 10, likes_used: 3, likes_remaining: 7 })
      }),
    )
    const store = useDiscoveryStore()
    await store.loadCandidates()
    await store.loadQuota()

    await store.decide('like')

    expect(store.likesRemaining).toBe(6)
    expect(store.quota?.likes_used).toBe(4)
    expect(quotaCalls).toBe(1) // 只在挂载时对了一次账
  })

  it('跳过(pass)不消耗额度,也不递减', async () => {
    mockCandidates([1])
    mockSwipeOk()
    mockQuota({ like_limit: 10, likes_used: 3, likes_remaining: 7 })
    const store = useDiscoveryStore()
    await store.loadCandidates()
    await store.loadQuota()

    await store.decide('pass')

    expect(store.likesRemaining).toBe(7)
  })

  it('撤销成功:把他放回卡堆顶部,并退回一次喜欢额度', async () => {
    mockCandidates([1, 2])
    mockSwipeOk()
    mockQuota({ like_limit: 10, likes_used: 3, likes_remaining: 7 })
    let undoneFor = 0
    server.use(
      mswHttp.post('/api/v1/discovery/swipe/undo', () => {
        undoneFor = 1
        return HttpResponse.json({ undone: true, target_user_id: 1 })
      }),
    )
    const store = useDiscoveryStore()
    await store.loadCandidates()
    await store.loadQuota()
    await store.decide('like')
    expect(store.current?.user_id).toBe(2)

    const ok = await store.undo()

    expect(undoneFor).toBe(1)
    expect(ok).toBe(true)
    expect(store.current?.user_id).toBe(1) // 回到刚划掉的那张
    expect(store.likesRemaining).toBe(7) // 退回了那一次
    expect(store.undoVisible).toBe(false) // 没有可撤销的了
    expect(store.canUndo).toBe(false)
    expect(store.error).toBe('')
  })

  it('撤销成功时若卡片已被换批次刷掉,兜底插回卡堆顶部', async () => {
    mockCandidates([1])
    mockSwipeOk()
    server.use(
      mswHttp.post('/api/v1/discovery/swipe/undo', () =>
        HttpResponse.json({ undone: true, target_user_id: 1 }),
      ),
    )
    const store = useDiscoveryStore()
    await store.loadCandidates()
    await store.decide('pass')
    expect(store.exhausted).toBe(true)
    // 模拟「候选池里已经没有这张卡了」:撤销响应仍要把他放回来
    store.candidates = []

    await store.undo()

    expect(store.current?.user_id).toBe(1)
    expect(store.exhausted).toBe(false)
  })

  it('撤销被拒(400 + 40003)时提示并收起按钮,不重试', async () => {
    mockCandidates([1, 2])
    mockSwipeOk()
    let calls = 0
    server.use(
      mswHttp.post('/api/v1/discovery/swipe/undo', () => {
        calls += 1
        return HttpResponse.json(
          { code: 40003, message: '没有可撤销的滑卡', request_id: 'r' },
          { status: 400 },
        )
      }),
    )
    const store = useDiscoveryStore()
    await store.loadCandidates()
    await store.decide('pass')

    const ok = await store.undo()

    expect(ok).toBe(false)
    expect(calls).toBe(1)
    expect(store.error).toBe('没有可撤销的操作')
    expect(store.undoVisible).toBe(false)
  })

  it('撤销遇限流(429)时按后端文案提示,按钮留着让用户稍后再试', async () => {
    mockCandidates([1, 2])
    mockSwipeOk()
    server.use(
      mswHttp.post('/api/v1/discovery/swipe/undo', () =>
        HttpResponse.json(
          { code: 42901, message: '操作过于频繁,请稍后再试', request_id: 'r' },
          { status: 429, headers: { 'Retry-After': '30' } },
        ),
      ),
    )
    const store = useDiscoveryStore()
    await store.loadCandidates()
    await store.decide('pass')

    const ok = await store.undo()

    expect(ok).toBe(false)
    expect(store.error).toBe('操作过于频繁,请稍后再试')
    expect(store.undoVisible).toBe(true)
    expect(store.canUndo).toBe(true)
  })

  it('30 秒内可撤销,倒计时归零后置灰但仍显示', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
    try {
      vi.setSystemTime(new Date('2026-11-09T10:00:00+08:00'))
      mockCandidates([1, 2])
      mockSwipeOk()
      const store = useDiscoveryStore()
      await store.loadCandidates()

      await store.decide('pass')
      expect(store.undoVisible).toBe(true)
      expect(store.canUndo).toBe(true)
      expect(store.undoSecondsLeft).toBe(UNDO_WINDOW_MS / 1000)
      expect(store.undoProgress).toBe(1)

      vi.advanceTimersByTime(10_000)
      expect(store.undoSecondsLeft).toBe(20)
      expect(store.canUndo).toBe(true)

      vi.advanceTimersByTime(25_000)
      expect(store.undoSecondsLeft).toBe(0)
      expect(store.canUndo).toBe(false)
      expect(store.undoProgress).toBe(0)
      expect(store.undoVisible).toBe(true) // 过期只是置灰,不是消失

      // 过期后再点等于不发请求
      const ok = await store.undo()
      expect(ok).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })

  it('配对成功不挂撤销窗口(§3.9 已配对一律拒绝)', async () => {
    mockCandidates([1])
    server.use(
      mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: true })),
    )
    const store = useDiscoveryStore()
    await store.loadCandidates()

    await store.decide('like')

    expect(store.matched?.user_id).toBe(1)
    expect(store.undoVisible).toBe(false)
    expect(store.canUndo).toBe(false)
    store.dismissMatched()
  })

  it('额度用完(429 + 42904)时停住当前卡、给出固定文案并挡住「喜欢」', async () => {
    mockCandidates([1, 2])
    server.use(
      mswHttp.post('/api/v1/discovery/swipe', () =>
        HttpResponse.json(
          { code: 42904, message: '今天的喜欢次数已用完', request_id: 'r' },
          { status: 429, headers: { 'Retry-After': '3600' } },
        ),
      ),
    )
    const store = useDiscoveryStore()
    await store.loadCandidates()
    await store.loadQuota()

    await store.decide('like')

    expect(store.error).toBe('今日喜欢次数已用完,明天再来')
    expect(store.likeBlocked).toBe(true)
    expect(store.current?.user_id).toBe(1) // 没有前进
    expect(store.undoVisible).toBe(false) // 没有成功的滑卡
  })

  it('额度用完后「跳过」仍不受限', async () => {
    mockCandidates([1, 2])
    mockQuota({ like_limit: 5, likes_used: 5, likes_remaining: 0 })
    server.use(
      mswHttp.post('/api/v1/discovery/swipe', () => HttpResponse.json({ matched: false })),
    )
    const store = useDiscoveryStore()
    await store.loadCandidates()
    await store.loadQuota()
    expect(store.likeBlocked).toBe(true) // 剩余 0 = 额度已用完

    await store.decide('pass')

    expect(store.current?.user_id).toBe(2) // pass 照常前进
    expect(store.error).toBe('')
  })
})
