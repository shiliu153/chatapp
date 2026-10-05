import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { useBlocksStore } from '@/stores/blocks'
import { server } from '../support/server'

const page = (results: unknown[]) => ({
  count: results.length,
  next: null,
  previous: null,
  results,
})
const blocked = (id: number) => ({
  user_id: id,
  nickname: `用户${id}`,
  avatar_url: null,
  blocked_at: '2026-10-01T00:00:00Z',
})

describe('blocks store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('拉取黑名单', async () => {
    server.use(mswHttp.get('/api/v1/blocks', () => HttpResponse.json(page([blocked(1)]))))
    const store = useBlocksStore()

    await store.load(true)

    expect(store.blocks).toHaveLength(1)
    expect(store.count).toBe(1)
  })

  it('解除拉黑后从列表移除(幂等,删除不存在的也返回成功)', async () => {
    server.use(
      mswHttp.get('/api/v1/blocks', () => HttpResponse.json(page([blocked(1), blocked(2)]))),
      mswHttp.delete('/api/v1/blocks/1', () => new HttpResponse(null, { status: 204 })),
    )
    const store = useBlocksStore()
    await store.load(true)

    await store.unblock(1)

    expect(store.blocks.map((b) => b.user_id)).toEqual([2])
    expect(store.count).toBe(1)
  })

  it('拉黑某人后写入后端并可重新拉取', async () => {
    let created = false
    server.use(
      mswHttp.get('/api/v1/blocks', () => HttpResponse.json(page(created ? [blocked(5)] : []))),
      mswHttp.post('/api/v1/blocks', () => {
        created = true
        return new HttpResponse(null, { status: 201 })
      }),
    )
    const store = useBlocksStore()
    await store.load(true)

    await store.block(5)
    await store.load(true)

    expect(store.blocks.map((b) => b.user_id)).toEqual([5])
  })
})
