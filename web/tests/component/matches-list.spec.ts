import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import MatchesList from '@/features/discovery/MatchesList.vue'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

const page = {
  count: 3,
  next_cursor: null,
  has_more: false,
  results: [
    {
      user_id: 1,
      im_user_id: 'u1',
      nickname: 'A',
      avatar_url: null,
      matched_at: '2026-10-01T00:00:00Z',
      shared_tags: [],
    },
    {
      user_id: 2,
      im_user_id: 'u2',
      nickname: 'B',
      avatar_url: 'https://cdn/b.jpg',
      matched_at: '2026-10-02T00:00:00Z',
      shared_tags: [
        { id: 1, name: '运动', icon: 'sports' },
        { id: 3, name: '电影', icon: 'movie' },
        { id: 5, name: '音乐', icon: 'music' },
      ],
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

  it('还有下一页时展示「加载更多」,点后按 next_cursor 追加', async () => {
    let calls = 0
    let secondQuery = ''
    server.use(
      mswHttp.get('/api/v1/matches', ({ request }) => {
        calls += 1
        if (calls > 1) secondQuery = new URL(request.url).search
        return HttpResponse.json(
          calls === 1
            ? { ...page, next_cursor: 'matches-page-2', has_more: true }
            : {
                count: 3,
                next_cursor: null,
                has_more: false,
                results: [
                  {
                    user_id: 3,
                    im_user_id: 'u3',
                    nickname: 'C',
                    avatar_url: null,
                    matched_at: '2026-10-03T00:00:00Z',
                    shared_tags: [],
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
    expect(secondQuery).toContain('before=matches-page-2')   // 游标,不是 offset
  })

  it('一个配对都没有时不渲染区块', async () => {
    server.use(
      mswHttp.get('/api/v1/matches', () =>
        HttpResponse.json({ count: 0, next_cursor: null, has_more: false, results: [] }),
      ),
    )
    const w = mountList()
    await flushPromises()

    expect(w.find('.matches-list').exists()).toBe(false)
  })

  it('共同标签最多展示 2 个 chip;没有共同标签的人不占位', async () => {
    server.use(mswHttp.get('/api/v1/matches', () => HttpResponse.json(page)))
    const w = mountList()
    await flushPromises()

    const items = w.findAll('.matches-list__item')
    expect(items[0].find('.matches-list__tags').exists()).toBe(false)   // A 无共同标签
    expect(items[1].findAll('.matches-list__tag').map((chip) => chip.text())).toEqual([
      '运动',
      '电影',
    ])
  })
})
