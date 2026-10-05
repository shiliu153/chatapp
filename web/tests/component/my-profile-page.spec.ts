import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import MyProfilePage from '@/features/profile/MyProfilePage.vue'
import { useProfileStore } from '@/stores/profile'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

const incomplete = {
  id: 11,
  user_id: 9,
  phone: '13800000001',
  nickname: '小雨',
  gender: 'female',
  birthday: '2000-01-01',
  age: 26,
  city: '上海',
  bio: '你好',
  status: 'incomplete',
  ban_reason: '',
  missing_fields: ['photos'],
  tags: [{ id: 1, name: '旅行', icon: 'plane' }],
  photos: [],
  preference: { target_gender: null, age_min: 18, age_max: 99, city: '' },
}

async function mountPage(status: string, missing: string[]) {
  server.use(
    mswHttp.get('/api/v1/users/me', () =>
      HttpResponse.json({ ...incomplete, status, missing_fields: missing }),
    ),
  )
  const pinia = freshPinia()
  const store = useProfileStore()
  await store.load()
  const w = mount(MyProfilePage, {
    global: { plugins: [pinia], stubs: { RouterLink: { template: '<a><slot /></a>' } } },
  })
  await flushPromises()
  return w
}

describe('MyProfilePage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('资料不完整时展示缺项与完善入口', async () => {
    const w = await mountPage('incomplete', ['photos'])

    expect(w.text()).toContain('还差:照片')
    expect(w.find('.my-profile__complete').exists()).toBe(true)
  })

  it('资料完整时不展示完善入口', async () => {
    const w = await mountPage('complete', [])

    expect(w.find('.my-profile__complete').exists()).toBe(false)
  })
})
