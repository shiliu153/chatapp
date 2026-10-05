import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { sessionEvents } from '@/api/session-events'
import { tokenStore } from '@/api/token-store'
import { useSessionStore } from '@/stores/session'
import { server } from '../support/server'

const meHandler = () => mswHttp.get('/api/v1/users/me', () => HttpResponse.json({ id: 1 }))

describe('session store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionEvents._reset()
  })

  it('初始状态是 loading(与 App 的 SessionLoading 对应)', () => {
    expect(useSessionStore().status).toBe('loading')
  })

  it('verify 成功后写入令牌与账号 id', async () => {
    server.use(
      mswHttp.post('/api/v1/auth/sms/verify', () =>
        HttpResponse.json({ access: 'a1', refresh: 'r1', is_new_user: true, user_id: 9 }),
      ),
    )
    const store = useSessionStore()

    await store.verify('13800000001', '123456')

    expect(store.status).toBe('loggedIn')
    expect(store.userId).toBe(9)
    expect(tokenStore.access).toBe('a1')
    expect(tokenStore.refresh).toBe('r1')
  })

  it('verify 失败时不改变登录态', async () => {
    server.use(
      mswHttp.post('/api/v1/auth/sms/verify', () =>
        HttpResponse.json({ code: 40003, message: '验证码错误', request_id: 'r' }, { status: 400 }),
      ),
    )
    const store = useSessionStore()

    await expect(store.verify('13800000001', '000000')).rejects.toMatchObject({ code: 40003 })

    expect(store.status).toBe('loading')
    expect(tokenStore.access).toBeNull()
  })

  it('restore:本地无令牌 → loggedOut', async () => {
    const store = useSessionStore()
    await store.restore()
    expect(store.status).toBe('loggedOut')
  })

  it('restore:有令牌且 /users/me 通 → loggedIn', async () => {
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
    tokenStore.userId = 5
    server.use(meHandler())
    const store = useSessionStore()

    await store.restore()

    expect(store.status).toBe('loggedIn')
    expect(store.userId).toBe(5)
  })

  it('logout 清凭证并回到 loggedOut', async () => {
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
    tokenStore.userId = 5
    server.use(meHandler())
    const store = useSessionStore()
    await store.restore()

    store.logout()

    expect(store.status).toBe('loggedOut')
    expect(store.userId).toBeNull()
    expect(tokenStore.access).toBeNull()
  })

  it('被顶号事件把 kicked 置为 true 并清凭证', async () => {
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
    server.use(meHandler())
    const store = useSessionStore()
    await store.restore()

    sessionEvents.emitKickedOffline()

    expect(store.kicked).toBe(true)
    expect(store.status).toBe('loggedOut')
    expect(tokenStore.access).toBeNull()
  })

  it('会话过期(刷新失败)只退出登录,不置 kicked', async () => {
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
    server.use(meHandler())
    const store = useSessionStore()
    await store.restore()

    sessionEvents.emitSessionExpired()

    expect(store.kicked).toBe(false)
    expect(store.status).toBe('loggedOut')
    expect(tokenStore.access).toBeNull()
  })

  it('acknowledgeKicked 关掉全屏提示', async () => {
    const store = useSessionStore()
    sessionEvents.emitKickedOffline()
    expect(store.kicked).toBe(true)

    store.acknowledgeKicked()

    expect(store.kicked).toBe(false)
  })
})
