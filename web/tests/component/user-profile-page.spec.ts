import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import UserProfilePage from '@/features/profile/UserProfilePage.vue'
import { server } from '../support/server'

const profile = {
  user_id: 8,
  nickname: '小雨',
  gender: 'female',
  age: 26,
  city: '上海',
  bio: '喜欢爬山',
  tags: [{ id: 1, name: '旅行', icon: 'plane' }],
  photos: [{ id: 1, url: 'https://cdn/a.jpg', status: 'approved', order: 0 }],
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
})
