import { flushPromises, mount } from '@vue/test-utils'
import { HttpResponse, http as mswHttp } from 'msw'
import { createMemoryHistory, createRouter } from 'vue-router'
import { describe, expect, it } from 'vitest'
import FeedbackPage from '@/features/settings/FeedbackPage.vue'
import { server } from '../support/server'

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div/>' } },
      { path: '/settings', name: 'settings', component: { template: '<div/>' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  const w = mount(FeedbackPage, {
    global: {
      plugins: [router],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
  await flushPromises()
  return { w, router }
}

describe('FeedbackPage', () => {
  it('内容不足 10 字时提交禁用', async () => {
    const { w } = await mountPage()

    expect(w.find('.feedback__submit').attributes('disabled')).toBeDefined()
    await w.find('.feedback__content').setValue('太短了')
    expect(w.find('.feedback__submit').attributes('disabled')).toBeDefined()
  })

  it('选类型 + 填内容 + 提交成功后切成功态', async () => {
    let body: unknown = null
    server.use(
      mswHttp.post('/api/v1/feedback', async ({ request }) => {
        body = await request.json()
        return HttpResponse.json({ id: 1 }, { status: 201 })
      }),
    )
    const { w } = await mountPage()

    await w.findAll('.feedback__type')[1].trigger('click')
    await w.find('.feedback__content').setValue('消息偶尔重复出现两次')
    await w.find('.feedback__contact input').setValue('a@b.com')
    await w.find('.feedback__submit').trigger('click')
    await flushPromises()

    expect(body).toEqual({
      type: 'bug',
      content: '消息偶尔重复出现两次',
      contact: 'a@b.com',
    })
    expect(w.find('.feedback--done').exists()).toBe(true)
    expect(w.text()).toContain('已收到你的反馈')
  })

  it('提交失败展示后端文案并保留输入', async () => {
    server.use(
      mswHttp.post('/api/v1/feedback', () =>
        HttpResponse.json(
          { code: 429, message: '操作太快了', request_id: 'r' },
          { status: 429 },
        ),
      ),
    )
    const { w } = await mountPage()

    await w.find('.feedback__content').setValue('消息偶尔重复出现两次')
    await w.find('.feedback__submit').trigger('click')
    await flushPromises()

    expect(w.find('.feedback__error').text()).toContain('操作太快了')
    expect((w.find('.feedback__content').element as HTMLTextAreaElement).value).toBe(
      '消息偶尔重复出现两次',
    )
  })
})
