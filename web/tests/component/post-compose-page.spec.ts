import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'
import PostComposePage from '@/features/square/PostComposePage.vue'
import { server } from '../support/server'

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div/>' } },
      { path: '/home/square', name: 'square', component: { template: '<div/>' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  const w = mount(PostComposePage, { global: { plugins: [createPinia(), router] } })
  await flushPromises()
  return { w, router }
}

describe('PostComposePage', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('正文与图片都为空时不允许提交', async () => {
    const { w } = await mountPage()
    await w.find('.post-compose__submit').trigger('click')
    await flushPromises()

    expect(w.text()).toContain('写点文字或选张图片吧')
  })

  it('提交成功跳回广场', async () => {
    server.use(
      mswHttp.post('/api/v1/posts', () =>
        HttpResponse.json({
          id: 9,
          author: { user_id: 3, nickname: '小雨', avatar_url: null },
          text: 'hi',
          images: [],
          like_count: 0,
          comment_count: 0,
          liked_by_me: false,
          created_at: '2026-10-01T10:00:00Z',
        }),
      ),
    )
    const { w, router } = await mountPage()
    await w.find('textarea').setValue('hi')
    await w.find('.post-compose__submit').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/home/square')
  })

  it('单张超过 5MB 被前端拦下', async () => {
    const { w } = await mountPage()
    const big = new File([new Uint8Array(6 * 1024 * 1024)], 'big.jpg', { type: 'image/jpeg' })
    const input = w.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [big] })
    await input.trigger('change')
    await flushPromises()

    expect(w.text()).toContain('单张图片不能超过 5MB')
  })

  it('超过 9 张被前端拦下', async () => {
    const { w } = await mountPage()
    const files = Array.from(
      { length: 10 },
      (_, i) => new File(['x'], `${i}.jpg`, { type: 'image/jpeg' }),
    )
    const input = w.find('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: files })
    await input.trigger('change')
    await flushPromises()

    expect(w.text()).toContain('最多 9 张图片')
  })
})
