import { flushPromises, mount } from '@vue/test-utils'
import { HttpResponse, http as mswHttp } from 'msw'
import { describe, expect, it } from 'vitest'
import PostLikesPage from '@/features/square/PostLikesPage.vue'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

const liker = (userId: number, nickname = `小雨${userId}`) => ({
  user_id: userId,
  nickname,
  avatar_url: null,
  liked_at: new Date().toISOString(),
})

const page = (results: unknown[], overrides = {}) => ({
  count: results.length,
  next_cursor: null,
  has_more: false,
  results,
  ...overrides,
})

/** RouterLink 桩:保留 `to`,好断言点行去哪。 */
const RouterLinkStub = {
  props: ['to'],
  template: '<a :data-to="JSON.stringify(to)"><slot /></a>',
}

function mountPage(id = '5') {
  return mount(PostLikesPage, {
    props: { id },
    global: { plugins: [freshPinia()], stubs: { RouterLink: RouterLinkStub } },
  })
}

describe('PostLikesPage', () => {
  it('按路由里的 id 拉点赞列表,展示昵称与时间', async () => {
    const paths: string[] = []
    server.use(
      mswHttp.get('/api/v1/posts/:id/likes', ({ request }) => {
        paths.push(new URL(request.url).pathname)
        return HttpResponse.json(page([liker(8), liker(9, '')]))
      }),
    )
    const w = mountPage('5')
    await flushPromises()

    expect(paths).toEqual(['/api/v1/posts/5/likes'])
    expect(w.findAll('.post-likes__row')).toHaveLength(2)
    expect(w.text()).toContain('小雨8')
    expect(w.text()).toContain('刚刚')
    // 昵称为空时退化成「用户{id}」,不出现空白行
    expect(w.text()).toContain('用户9')
    expect(w.text()).toContain('共 2 人点赞')
  })

  it('点某人一行去他的资料页', async () => {
    server.use(
      mswHttp.get('/api/v1/posts/5/likes', () => HttpResponse.json(page([liker(8)]))),
    )
    const w = mountPage('5')
    await flushPromises()

    const link = w.find('.post-likes__person')
    expect(link.attributes('data-to')).toContain('"name":"user-profile"')
    expect(link.attributes('data-to')).toContain('"id":8')
  })

  it('没人点赞时展示空态(200 + 空列表,不是错误)', async () => {
    server.use(mswHttp.get('/api/v1/posts/5/likes', () => HttpResponse.json(page([]))))
    const w = mountPage('5')
    await flushPromises()

    expect(w.find('.app-empty').exists()).toBe(true)
    expect(w.text()).toContain('还没有人点赞')
    expect(w.findAll('.post-likes__row')).toHaveLength(0)
  })

  it('动态不可见(404)时展示错误态给文案', async () => {
    server.use(
      mswHttp.get('/api/v1/posts/5/likes', () =>
        HttpResponse.json({ code: 40401, message: '动态不存在', request_id: 'r' }, { status: 404 }),
      ),
    )
    const w = mountPage('5')
    await flushPromises()

    expect(w.text()).toContain('动态不存在')
  })

  it('还有下一页时展示「加载更多」并带上游标', async () => {
    const queries: string[] = []
    server.use(
      mswHttp.get('/api/v1/posts/5/likes', ({ request }) => {
        const url = new URL(request.url)
        queries.push(url.search)
        return HttpResponse.json(
          queries.length === 1
            ? page([liker(8)], { count: 2, next_cursor: 'c2', has_more: true })
            : page([liker(9)], { count: 2 }),
        )
      }),
    )
    const w = mountPage('5')
    await flushPromises()

    await w.find('.post-likes__more').trigger('click')
    await flushPromises()

    expect(queries[1]).toContain('before=c2')
    expect(w.findAll('.post-likes__row')).toHaveLength(2)
  })
})
