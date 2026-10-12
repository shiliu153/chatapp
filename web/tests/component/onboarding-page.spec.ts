import { flushPromises, mount } from '@vue/test-utils'
import { HttpResponse, http as mswHttp } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import OnboardingPage from '@/features/onboarding/OnboardingPage.vue'
import { useProfileStore } from '@/stores/profile'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

const emptyMe = {
  id: 11,
  user_id: 9,
  phone: '13800000001',
  nickname: '',
  gender: '',
  birthday: null,
  age: null,
  city: '',
  bio: '',
  status: 'incomplete',
  ban_reason: '',
  missing_fields: ['nickname', 'gender', 'birthday', 'city', 'photos'],
  tags: [],
  photos: [],
  preference: { target_gender: null, age_min: 18, age_max: 99, city: '' },
}

/** 页面会 router.push,组件测试里用假的 router 记录跳转目标。 */
const push = vi.fn()
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))

const tags = [
  { id: 1, name: '旅行', icon: 'plane' },
  { id: 2, name: '电影', icon: 'film' },
]

async function mountPage(me: Record<string, unknown> = emptyMe) {
  server.use(
    mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)),
    // 页面里嵌了 TagPicker,它会拉标签池
    mswHttp.get('/api/v1/users/tags', () => HttpResponse.json(tags)),
  )
  const pinia = freshPinia()
  const store = useProfileStore()
  const w = mount(OnboardingPage, { global: { plugins: [pinia] } })
  await flushPromises()
  return { w, store }
}

const nicknameInput = (w: Awaited<ReturnType<typeof mountPage>>['w']) =>
  w.findAll('input[type="text"]')[0]

describe('OnboardingPage', () => {
  it('已有资料时预填表单(重进引导页不该丢已填内容)', async () => {
    const { w } = await mountPage({ ...emptyMe, nickname: '小雨', city: '上海' })

    expect((nicknameInput(w).element as HTMLInputElement).value).toBe('小雨')
    expect((w.findAll('input[type="text"]')[1].element as HTMLInputElement).value).toBe('上海')
  })

  it('提交后 PATCH 全量字段并跳到发现页', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(emptyMe)),
      mswHttp.get('/api/v1/users/tags', () => HttpResponse.json(tags)),
      mswHttp.patch('/api/v1/users/me', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...emptyMe, nickname: '阿泽', status: 'complete' })
      }),
    )
    const pinia = freshPinia()
    const w = mount(OnboardingPage, { global: { plugins: [pinia] } })
    await flushPromises()

    await nicknameInput(w).setValue('阿泽')
    await w.find('.onboarding__chip').trigger('click') // 女生
    await w.find('.app-button').trigger('click')
    await flushPromises()

    expect(body).toMatchObject({ nickname: '阿泽', gender: 'female' })
    expect(push).toHaveBeenCalledWith({ name: 'discovery' })
  })

  it('提交失败时显示后端文案,且不跳转', async () => {
    push.mockClear()
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(emptyMe)),
      mswHttp.get('/api/v1/users/tags', () => HttpResponse.json(tags)),
      mswHttp.patch('/api/v1/users/me', () =>
        HttpResponse.json(
          { code: 40001, message: '未满 18 岁不能使用', request_id: 'r' },
          { status: 400 },
        ),
      ),
    )
    const pinia = freshPinia()
    const w = mount(OnboardingPage, { global: { plugins: [pinia] } })
    await flushPromises()

    await w.find('.app-button').trigger('click')
    await flushPromises()

    expect(w.find('.app-input__error').text()).toContain('未满 18 岁不能使用')
    expect(push).not.toHaveBeenCalled()
  })
})
