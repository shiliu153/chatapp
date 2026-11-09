import { flushPromises, mount } from '@vue/test-utils'
import { HttpResponse, http as mswHttp } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import DevicesPage from '@/features/settings/DevicesPage.vue'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

const at = (month: number, day: number, hour: number, minute: number): string =>
  new Date(2026, month - 1, day, hour, minute).toISOString()

const appDevice = (over: Record<string, unknown> = {}) => ({
  client_type: 'app',
  client_label: 'App',
  current: false,
  created_at: at(11, 9, 10, 20),
  last_active_at: at(11, 9, 10, 55),
  ...over,
})

const webDevice = (over: Record<string, unknown> = {}) => ({
  client_type: 'web',
  client_label: '网页端',
  current: true,
  created_at: at(11, 9, 11, 38),
  last_active_at: at(11, 9, 11, 38),
  ...over,
})

const listOf = (results: unknown[]) => HttpResponse.json({ results })

function mountPage() {
  return mount(DevicesPage, { global: { plugins: [freshPinia()] } })
}

describe('DevicesPage', () => {
  afterEach(() => vi.restoreAllMocks())

  it('一行一个端:端名 + 首次登录 + 最近活跃', async () => {
    server.use(mswHttp.get('/api/v1/devices', () => listOf([appDevice(), webDevice()])))
    const w = mountPage()
    await flushPromises()

    expect(w.findAll('.devices__item')).toHaveLength(2)
    const first = w.findAll('.devices__item')[0]
    expect(first.find('.devices__label').text()).toContain('App')
    expect(first.text()).toContain('首次登录 2026-11-09 10:20')
    expect(first.text()).toContain('最近活跃 2026-11-09 10:55')
  })

  it('当前端标「本机」且没有下线按钮,另一端有按钮', async () => {
    server.use(mswHttp.get('/api/v1/devices', () => listOf([appDevice(), webDevice()])))
    const w = mountPage()
    await flushPromises()

    const rows = w.findAll('.devices__item')
    expect(rows[1].find('.devices__current').text()).toBe('本机')
    expect(rows[1].find('.devices__logout').exists()).toBe(false)
    expect(rows[0].find('.devices__current').exists()).toBe(false)
    expect(rows[0].find('.devices__logout').exists()).toBe(true)
    expect(w.findAll('.devices__logout')).toHaveLength(1)
  })

  it('last_active_at 为 null 时显示「尚未在此端刷新过」,不显示 null 或空白', async () => {
    server.use(
      mswHttp.get('/api/v1/devices', () =>
        listOf([appDevice({ last_active_at: null }), webDevice()]),
      ),
    )
    const w = mountPage()
    await flushPromises()

    const text = w.findAll('.devices__item')[0].text()
    expect(text).toContain('尚未在此端刷新过')
    expect(text).not.toContain('null')
    expect(text).not.toContain('最近活跃 null')
  })

  it('二次确认取消时不发 DELETE,该行保留', async () => {
    let called = false
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    server.use(
      mswHttp.get('/api/v1/devices', () => listOf([appDevice(), webDevice()])),
      mswHttp.delete('/api/v1/devices/:clientType', () => {
        called = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.devices__logout').trigger('click')
    await flushPromises()

    expect(confirm).toHaveBeenCalledTimes(1)
    expect(confirm.mock.calls[0][0]).toContain('确定下线')
    expect(called).toBe(false)
    expect(w.findAll('.devices__item')).toHaveLength(2)
  })

  it('确认后 DELETE 该端,该行消失并给出提示', async () => {
    let deleted = ''
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    server.use(
      mswHttp.get('/api/v1/devices', () => listOf([appDevice(), webDevice()])),
      mswHttp.delete('/api/v1/devices/:clientType', ({ request }) => {
        deleted = new URL(request.url).pathname
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.devices__logout').trigger('click')
    await flushPromises()

    expect(deleted).toBe('/api/v1/devices/app')
    expect(w.findAll('.devices__item')).toHaveLength(1)
    expect(w.findAll('.devices__item')[0].text()).toContain('网页端')
    expect(w.find('.app-toast').text()).toContain('已下线')
  })

  it('下线失败按统一错误处理(显示后端文案,行保留)', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    server.use(
      mswHttp.get('/api/v1/devices', () => listOf([appDevice(), webDevice()])),
      mswHttp.delete('/api/v1/devices/app', () =>
        HttpResponse.json(
          { code: 50002, message: '服务器开小差了', request_id: 'r' },
          { status: 500 },
        ),
      ),
    )
    const w = mountPage()
    await flushPromises()

    await w.find('.devices__logout').trigger('click')
    await flushPromises()

    expect(w.find('.devices__error').text()).toContain('服务器开小差了')
    expect(w.findAll('.devices__item')).toHaveLength(2)
  })

  it('加载失败显示统一错误文案(401 走刷新通道,刷新失败才算真失败)', async () => {
    server.use(
      mswHttp.get('/api/v1/devices', () =>
        HttpResponse.json({ code: 401, message: '登录已过期', request_id: 'r' }, { status: 401 }),
      ),
      mswHttp.post('/api/v1/auth/token/refresh', () =>
        HttpResponse.json({ code: 401, message: '登录已过期', request_id: 'r' }, { status: 401 }),
      ),
    )
    const w = mountPage()
    await flushPromises()

    expect(w.find('.devices__error').text()).toContain('登录已过期')
    expect(w.findAll('.devices__item')).toHaveLength(0)
  })
})
