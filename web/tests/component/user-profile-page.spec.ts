import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import UserProfilePage from '@/features/profile/UserProfilePage.vue'
import { server } from '../support/server'

/** 播放走全局单例,这里只验「点了会把 voice.url 送进播放器」 */
const playVoice = vi.fn((_url: string, onEnd: () => void) => onEnd())

vi.mock('@/im/voicePlayer', () => ({
  playVoice: (url: string, onEnd: () => void) => playVoice(url, onEnd),
  stopVoice: () => {},
}))

const profile = {
  user_id: 8,
  nickname: '小雨',
  gender: 'female',
  age: 26,
  city: '上海',
  bio: '喜欢爬山',
  tags: [{ id: 1, name: '旅行', icon: 'plane' }],
  photos: [{ id: 1, url: 'https://cdn/a.jpg', status: 'approved', order: 0 }],
  shared_tags: [],
  voice: null,
  is_followed: false,
  follower_count: 3,
  following_count: 5,
}

function mountPage(id = '8') {
  return mount(UserProfilePage, {
    props: { id },
    global: { plugins: [createPinia()], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
}

describe('UserProfilePage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('展示公开资料', async () => {
    server.use(mswHttp.get('/api/v1/users/8', () => HttpResponse.json(profile)))
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('小雨')
    expect(w.text()).toContain('喜欢爬山')
  })

  it('没录过语音时整块不渲染(voice == null 不留空占位)', async () => {
    server.use(mswHttp.get('/api/v1/users/8', () => HttpResponse.json(profile)))
    const w = mountPage()
    await flushPromises()

    expect(w.find('.user-profile__voice').exists()).toBe(false)
  })

  it('有语音时渲染播放条,点了播放公开的 voice.url(不拼 API_BASE)', async () => {
    playVoice.mockClear()
    server.use(
      mswHttp.get('/api/v1/users/8', () =>
        HttpResponse.json({
          ...profile,
          voice: { url: 'https://cdn.example.com/media/voices/abc.m4a', duration_ms: 12_400 },
        }),
      ),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.user-profile__voice').exists()).toBe(true)
    expect(w.text()).toContain('语音自我介绍')
    expect(w.text()).toContain('12″')

    await w.find('.user-profile__voice button').trigger('click')
    expect(playVoice).toHaveBeenCalledWith(
      'https://cdn.example.com/media/voices/abc.m4a',
      expect.any(Function),
    )
  })

  it('404(已拉黑/重封禁)展示不可见提示且不重试', async () => {
    server.use(
      mswHttp.get('/api/v1/users/8', () =>
        HttpResponse.json({ code: 40403, message: '用户不存在', request_id: 'r' }, { status: 404 }),
      ),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('用户不存在')
    expect(w.find('.app-error button').exists()).toBe(false) // 不给重试
  })

  it('举报提交后展示受理提示', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      mswHttp.get('/api/v1/users/8', () => HttpResponse.json(profile)),
      mswHttp.post('/api/v1/reports', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ id: 1, type: 'harassment', status: 'pending' })
      }),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.user-profile__report').trigger('click')
    await flushPromises()
    await w.findAll('.report-dialog__reason')[0].trigger('click')
    await w.find('.report-dialog__submit').trigger('click')
    await flushPromises()

    expect(body).toMatchObject({ target_user_id: 8, type: 'harassment' })
    expect(w.text()).toContain('已收到举报')
  })

  it('拉黑需二次确认,确认后调用接口', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    let called = false
    server.use(
      mswHttp.get('/api/v1/users/8', () => HttpResponse.json(profile)),
      mswHttp.post('/api/v1/blocks', () => {
        called = true
        return new HttpResponse(null, { status: 201 })
      }),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.user-profile__block').trigger('click')
    await flushPromises()

    expect(confirmSpy).toHaveBeenCalled()
    expect(called).toBe(true)
    expect(w.text()).toContain('已拉黑')
  })

  it('关注:点按钮 → POST,按钮变「已关注」且粉丝数 +1,并刷新关注流', async () => {
    let called = false
    let feedRefreshed = 0
    server.use(
      mswHttp.get('/api/v1/users/8', () => HttpResponse.json(profile)),
      mswHttp.post('/api/v1/users/8/follow', () => {
        called = true
        return new HttpResponse(null, { status: 204 })
      }),
      // 关注成功后必须让广场「关注」tab 的列表失效(1.0.9 记录的已知限制)
      mswHttp.get('/api/v1/feed/following', () => {
        feedRefreshed += 1
        return HttpResponse.json({ count: 0, next_cursor: null, has_more: false, results: [] })
      }),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.user-profile__follow-button').text()).toBe('关注')
    expect(w.find('.user-profile__follow').text()).toContain('3 粉丝')

    await w.find('.user-profile__follow-button').trigger('click')
    await flushPromises()

    expect(called).toBe(true)
    expect(feedRefreshed).toBeGreaterThan(0)
    expect(w.find('.user-profile__follow-button').text()).toBe('已关注')
    expect(w.find('.user-profile__follow').text()).toContain('4 粉丝')
  })

  it('已关注:再点走 DELETE,回到「关注」', async () => {
    let called = false
    server.use(
      mswHttp.get('/api/v1/users/8', () =>
        HttpResponse.json({ ...profile, is_followed: true, follower_count: 4 }),
      ),
      mswHttp.delete('/api/v1/users/8/follow', () => {
        called = true
        return new HttpResponse(null, { status: 204 })
      }),
      mswHttp.get('/api/v1/feed/following', () =>
        HttpResponse.json({ count: 0, next_cursor: null, has_more: false, results: [] }),
      ),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.user-profile__follow-button').text()).toBe('已关注')

    await w.find('.user-profile__follow-button').trigger('click')
    await flushPromises()

    expect(called).toBe(true)
    expect(w.find('.user-profile__follow-button').text()).toBe('关注')
    expect(w.find('.user-profile__follow').text()).toContain('3 粉丝')
  })

  it('关注失败:乐观态回滚并提示', async () => {
    server.use(
      mswHttp.get('/api/v1/users/8', () => HttpResponse.json(profile)),
      mswHttp.post('/api/v1/users/8/follow', () =>
        HttpResponse.json(
          { code: 50002, message: '服务器开小差了', request_id: 'r' },
          { status: 500 },
        ),
      ),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.user-profile__follow-button').trigger('click')
    await flushPromises()

    expect(w.find('.user-profile__follow-button').text()).toBe('关注')
    expect(w.find('.user-profile__follow').text()).toContain('3 粉丝')
    expect(w.text()).toContain('服务器开小差了')
  })
})
