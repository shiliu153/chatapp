import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import PreferencePage from '@/features/profile/PreferencePage.vue'
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
  bio: '',
  status: 'complete',
  ban_reason: '',
  missing_fields: [],
  tags: [],
  photos: [],
  preference: { target_gender: null, age_min: 18, age_max: 99, city: '' },
}

describe('PreferencePage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('不限性别用 null 提交', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)),
      mswHttp.patch('/api/v1/users/me/preference', async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json(me.preference)
      }),
    )
    const pinia = freshPinia()
    const store = useProfileStore()
    await store.load()
    const w = mount(PreferencePage, { global: { plugins: [pinia], stubs: { RouterLink: true } } })
    await flushPromises()

    await w.find('.preference__gender button').trigger('click') // 第一个是「不限」
    await w.find('.preference__submit').trigger('click')
    await flushPromises()

    expect(body).toMatchObject({ target_gender: null })
  })

  it('后端拒绝时展示后端文案', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)),
      mswHttp.patch('/api/v1/users/me/preference', () =>
        HttpResponse.json(
          { code: 40002, message: '最小年龄不能小于 18', request_id: 'r' },
          { status: 400 },
        ),
      ),
    )
    const pinia = freshPinia()
    const store = useProfileStore()
    await store.load()
    const w = mount(PreferencePage, { global: { plugins: [pinia], stubs: { RouterLink: true } } })
    await flushPromises()

    await w.find('.preference__submit').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('最小年龄不能小于 18')
  })
})
