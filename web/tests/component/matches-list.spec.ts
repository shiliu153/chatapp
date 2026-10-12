import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import MatchesList from '@/features/discovery/MatchesList.vue'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

const page = {
  count: 3,
  next: null,
  previous: null,
  results: [
    { user_id: 1, im_user_id: 'u1', nickname: 'A', avatar_url: null, matched_at: '2026-10-01T00:00:00Z' },
    {
      user_id: 2,
      im_user_id: 'u2',
      nickname: 'B',
      avatar_url: 'https://cdn/b.jpg',
      matched_at: '2026-10-02T00:00:00Z',
    },
  ],
}

function mountList() {
  return mount(MatchesList, {
    global: {
      plugins: [freshPinia()],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
}

describe('MatchesList', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('挂载即拉取并渲染配对头像', async () => {
    server.use(mswHttp.get('/api/v1/matches', () => HttpResponse.json(page)))
    const w = mountList()
    await flushPromises()

    expect(w.findAll('.matches-list__item')).toHaveLength(2)
    expect(w.text()).toContain('A')
  })

  it('还有下一页时展示「加载更多」,点后追加', async () => {
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/matches', () => {
        calls += 1
        return HttpResponse.json(
          calls === 1
            ? { ...page, next: 'http://x/api/v1/matches?offset=2' }
            : {
                count: 3,
                next: null,
                previous: null,
                results: [
                  {
                    user_id: 3,
                    im_user_id: 'u3',
                    nickname: 'C',
                    avatar_url: null,
                    matched_at: '2026-10-03T00:00:00Z',
                  },
                ],
              },
        )
      }),
    )
    const w = mountList()
    await flushPromises()

    await w.find('.matches-list__more').trigger('click')
    await flushPromises()

    expect(w.findAll('.matches-list__item')).toHaveLength(3)
  })

  it('一个配对都没有时不渲染区块', async () => {
    server.use(
      mswHttp.get('/api/v1/matches', () =>
        HttpResponse.json({ count: 0, next: null, previous: null, results: [] }),
      ),
    )
    const w = mountList()
    await flushPromises()

    expect(w.find('.matches-list').exists()).toBe(false)
  })
})
