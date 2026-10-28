import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createAppRouter } from '@/router'
import { tokenStore } from '@/api/token-store'
import { server } from '../support/server'

vi.mock('@/composables/useDevice', () => ({ isMobileDevice: () => false }))

const bannedHeavy = {
  id: 11,
  user_id: 9,
  phone: '13800000001',
  nickname: '小雨',
  gender: 'female',
  birthday: '2000-01-01',
  age: 26,
  city: '上海',
  bio: '',
  status: 'banned_heavy',
  ban_reason: '发布违规内容',
  missing_fields: [],
  tags: [],
  photos: [],
  preference: { target_gender: null, age_min: 18, age_max: 99, city: '' },
}

describe('封禁守卫', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    localStorage.setItem('hb.legalAgreed', '1')
    tokenStore.access = 'a'
  })

  it('banned_heavy 用户被送到 /banned', async () => {
    server.use(mswHttp.get('/api/v1/users/me', () => HttpResponse.json(bannedHeavy)))
    const router = createAppRouter()
    await router.push('/home/discovery')
    expect(router.currentRoute.value.path).toBe('/banned')
  })

  it('正常用户留在发现页', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () =>
        HttpResponse.json({ ...bannedHeavy, status: 'complete', ban_reason: '' }),
      ),
    )
    const router = createAppRouter()
    await router.push('/home/discovery')
    expect(router.currentRoute.value.path).toBe('/home/discovery')
  })
})
