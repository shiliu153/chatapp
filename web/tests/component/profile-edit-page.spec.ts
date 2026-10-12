import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import ProfileEditPage from '@/features/profile/ProfileEditPage.vue'
import { useProfileStore } from '@/stores/profile'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

const me = {
  id: 11,
  user_id: 9,
  phone: '13800000001',
  nickname: '小雨',
  gender: 'female',
  birthday: '2000-01-01',
  age: 26,
  city: '上海',
  bio: '你好',
  status: 'complete',
  ban_reason: '',
  missing_fields: [],
  tags: [],
  photos: [],
  preference: { target_gender: null, age_min: 18, age_max: 99, city: '' },
}

async function mountPage() {
  server.use(mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)))
  const pinia = freshPinia() // 预置状态的 pinia 必须与挂载时用的是同一个
  const store = useProfileStore()
  await store.load()
  const w = mount(ProfileEditPage, {
    global: { plugins: [pinia], stubs: { RouterLink: true } },
  })
  await flushPromises()
  return w
}

describe('ProfileEditPage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('用现有资料预填表单', async () => {
    const w = await mountPage()
    expect((w.find('input[type="text"]').element as HTMLInputElement).value).toBe('小雨')
  })

  it('提交后调用 PATCH 并展示成功反馈', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)),
      mswHttp.patch('/api/v1/users/me', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ ...me, nickname: '阿泽' })
      }),
    )
    const pinia = freshPinia()
    const store = useProfileStore()
    await store.load()
    const w = mount(ProfileEditPage, { global: { plugins: [pinia], stubs: { RouterLink: true } } })
    await flushPromises()

    await w.find('input[type="text"]').setValue('阿泽')
    await w.find('.profile-edit__submit').trigger('click')
    await flushPromises()

    expect(body).toMatchObject({ nickname: '阿泽' })
    expect(w.text()).toContain('已保存')
  })

  it('未满 18 岁时展示后端文案', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)),
      mswHttp.patch('/api/v1/users/me', () =>
        HttpResponse.json(
          { code: 40001, message: '未满 18 周岁不能使用本服务', request_id: 'r' },
          { status: 400 },
        ),
      ),
    )
    const pinia = freshPinia()
    const store = useProfileStore()
    await store.load()
    const w = mount(ProfileEditPage, { global: { plugins: [pinia], stubs: { RouterLink: true } } })
    await flushPromises()

    await w.find('.profile-edit__submit').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('未满 18 周岁不能使用本服务')
  })
})
