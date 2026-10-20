import { flushPromises, mount } from '@vue/test-utils'
import { HttpResponse, http as mswHttp } from 'msw'
import { describe, expect, it } from 'vitest'
import NotificationSettingsPage from '@/features/settings/NotificationSettingsPage.vue'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

const prefs = (overrides: Record<string, boolean> = {}) => ({
  likes: true,
  matches: true,
  system: true,
  ...overrides,
})

function mountPage() {
  return mount(NotificationSettingsPage, {
    global: {
      plugins: [freshPinia()],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
}

describe('NotificationSettingsPage', () => {
  it('按后端偏好渲染三个开关与网页端说明', async () => {
    server.use(
      mswHttp.get('/api/v1/push/preferences', () => HttpResponse.json(prefs({ system: false }))),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.text()).toContain('新的喜欢')
    expect(w.text()).toContain('配对成功')
    expect(w.text()).toContain('系统通知')
    expect(w.text()).toContain('网页端不接收推送')

    const switches = w.findAll('[role="switch"]')
    expect(switches).toHaveLength(3)
    expect(switches[2].attributes('aria-checked')).toBe('false')
  })

  it('切换开关时调用接口并更新状态', async () => {
    let received: unknown = null
    server.use(
      mswHttp.get('/api/v1/push/preferences', () => HttpResponse.json(prefs())),
      mswHttp.patch('/api/v1/push/preferences', async ({ request }) => {
        received = await request.json()
        return HttpResponse.json(prefs({ likes: false }))
      }),
    )
    const w = mountPage()
    await flushPromises()

    await w.findAll('[role="switch"]')[0].trigger('click')
    await flushPromises()

    expect(received).toEqual({ likes: false })
    expect(w.findAll('[role="switch"]')[0].attributes('aria-checked')).toBe('false')
  })

  it('接口失败时回滚并提示', async () => {
    server.use(
      mswHttp.get('/api/v1/push/preferences', () => HttpResponse.json(prefs())),
      mswHttp.patch('/api/v1/push/preferences', () =>
        HttpResponse.json(
          { code: 50002, message: '服务器开小差了', request_id: 'r' },
          { status: 500 },
        ),
      ),
    )
    const w = mountPage()
    await flushPromises()

    await w.findAll('[role="switch"]')[0].trigger('click')
    await flushPromises()

    expect(w.findAll('[role="switch"]')[0].attributes('aria-checked')).toBe('true')
    expect(w.text()).toContain('服务器开小差了')
  })
})
