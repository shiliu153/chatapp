import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { sessionEvents } from '@/api/session-events'
import { LAST_ACTIVE_NEVER, useDevicesStore } from '@/stores/devices'
import { server } from '../support/server'

/**
 * 用**本地时间**构造 ISO,期望文案在任何时区下都成立
 * (store 按本地时区渲染,`toISOString()` 转出去再转回来就是同一个墙上时间)。
 */
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

describe('devices store', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('列表映射:端展示名 + 首次登录 + 最近活跃(本地时间到分钟)', async () => {
    server.use(mswHttp.get('/api/v1/devices', () => listOf([appDevice(), webDevice()])))
    const store = useDevicesStore()

    await store.load()

    expect(store.devices).toHaveLength(2)
    const [app, web] = store.devices
    expect(app.clientType).toBe('app')
    expect(app.label).toBe('App')
    expect(app.firstLoginText).toBe('首次登录 2026-11-09 10:20')
    expect(app.lastActiveText).toBe('最近活跃 2026-11-09 10:55')
    expect(web.clientType).toBe('web')
    expect(web.label).toBe('网页端')
    expect(store.loading).toBe(false)
  })

  it('last_active_at 为 null 时显示「尚未在此端刷新过」,不出现 null / 空白', async () => {
    server.use(
      mswHttp.get('/api/v1/devices', () => listOf([appDevice({ last_active_at: null })])),
    )
    const store = useDevicesStore()

    await store.load()

    expect(store.devices[0].lastActiveText).toBe(LAST_ACTIVE_NEVER)
    expect(store.devices[0].lastActiveText).not.toContain('null')
    expect(store.devices[0].firstLoginText).toContain('首次登录')
  })

  it('current 分支:本机不给下线按钮,current 指向该行', async () => {
    server.use(mswHttp.get('/api/v1/devices', () => listOf([appDevice(), webDevice()])))
    const store = useDevicesStore()

    await store.load()

    expect(store.devices.map((item) => item.canLogout)).toEqual([true, false])
    expect(store.current?.clientType).toBe('web')
  })

  it('下线另一端点 DELETE /devices/{client_type},成功后该行从列表移除', async () => {
    let deleted = ''
    server.use(
      mswHttp.get('/api/v1/devices', () => listOf([appDevice(), webDevice()])),
      mswHttp.delete('/api/v1/devices/:clientType', ({ request }) => {
        deleted = new URL(request.url).pathname
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const store = useDevicesStore()
    await store.load()

    await store.logout('app')

    expect(deleted).toBe('/api/v1/devices/app')
    expect(store.devices.map((item) => item.clientType)).toEqual(['web'])
  })

  it('下线失败时抛错且该行保留', async () => {
    server.use(
      mswHttp.get('/api/v1/devices', () => listOf([appDevice(), webDevice()])),
      mswHttp.delete('/api/v1/devices/app', () =>
        HttpResponse.json(
          { code: 40004, message: '客户端类型不合法,只能是 app 或 web', request_id: 'r' },
          { status: 400 },
        ),
      ),
    )
    const store = useDevicesStore()
    await store.load()

    await expect(store.logout('app')).rejects.toMatchObject({ code: 40004 })
    expect(store.devices.map((item) => item.clientType)).toEqual(['app', 'web'])
  })

  it('下线当前端(防御分支)时走既有「清凭证回登录页」通道', async () => {
    server.use(
      mswHttp.get('/api/v1/devices', () => listOf([appDevice(), webDevice()])),
      mswHttp.delete('/api/v1/devices/web', () => new HttpResponse(null, { status: 204 })),
    )
    const onExpired = vi.fn()
    sessionEvents.onSessionExpired(onExpired)
    const store = useDevicesStore()
    await store.load()

    await store.logout('web')

    expect(onExpired).toHaveBeenCalledTimes(1)
    expect(store.devices.map((item) => item.clientType)).toEqual(['app'])
  })
})
