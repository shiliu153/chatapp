import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import PhotoGrid from '@/features/profile/PhotoGrid.vue'
import { useProfileStore } from '@/stores/profile'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

function profileWithPhotos(count: number) {
  return {
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
    photos: Array.from({ length: count }, (_, i) => ({
      id: i + 1,
      url: `https://cdn/${i}.jpg`,
      status: 'approved',
      order: i,
    })),
    preference: { target_gender: null, age_min: 18, age_max: 99, city: '' },
  }
}

/** 预置照片的 pinia 与挂载时传入的必须是同一个,否则组件里读到的是空 store。 */
async function mountGrid(count: number) {
  server.use(mswHttp.get('/api/v1/users/me', () => HttpResponse.json(profileWithPhotos(count))))
  const pinia = freshPinia()
  const store = useProfileStore()
  await store.load()
  const w = mount(PhotoGrid, { global: { plugins: [pinia] } })
  await flushPromises()
  return { w, store }
}

describe('PhotoGrid', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('渲染已有照片与审核徽标', async () => {
    const { w } = await mountGrid(2)
    expect(w.findAll('.photo-grid__item')).toHaveLength(2)
    expect(w.findAll('.photo-grid__badge')[0].text()).toBe('已通过')
  })

  it('超过 5MB 的文件被前端拦下并给提示', async () => {
    const { w } = await mountGrid(0)
    const big = new File([new Uint8Array(6 * 1024 * 1024)], 'big.jpg', { type: 'image/jpeg' })
    const input = w.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [big] })
    await input.trigger('change')
    await flushPromises()

    expect(w.text()).toContain('单张照片不能超过 5MB')
  })

  it('已有 6 张时不再允许上传', async () => {
    const { w } = await mountGrid(6)
    expect(w.find('input[type="file"]').exists()).toBe(false)
    expect(w.text()).toContain('最多 6 张')
  })

  it('删除调用后端并从网格移除', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(profileWithPhotos(2))),
      mswHttp.delete('/api/v1/users/me/photos/1', () => new HttpResponse(null, { status: 204 })),
    )
    const pinia = freshPinia()
    const store = useProfileStore()
    await store.load()
    const w = mount(PhotoGrid, { global: { plugins: [pinia] } })
    await flushPromises()

    await w.findAll('.photo-grid__remove')[0].trigger('click')
    await flushPromises()

    expect(store.profile?.photos).toHaveLength(1)
  })
})
