import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { sessionEvents } from '@/api/session-events'
import { tokenStore } from '@/api/token-store'
import { useSessionStore } from '@/stores/session'
import { server } from '../support/server'

const meHandler = () =>
  mswHttp.get('/api/v1/users/me', () => HttpResponse.json({ id: 1, user_id: 5 }))

const unauthorized = () =>
  HttpResponse.json({ code: 40100, message: '未认证', request_id: 'r' }, { status: 401 })

const logoutHandler = () =>
  mswHttp.post('/api/v1/auth/logout', () => new HttpResponse(null, { status: 204 }))

describe('session store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    sessionEvents._reset()
  })

  it('初始状态是 loading(与 App 的 SessionLoading 对应)', () => {
    expect(useSessionStore().status).toBe('loading')
  })

  it('verify 成功后把 access 放内存、账号 id 落本地', async () => {
    server.use(
      mswHttp.post('/api/v1/auth/sms/verify', () =>
        HttpResponse.json({ access: 'a1', is_new_user: true, user_id: 9 }),
      ),
    )
    const store = useSessionStore()

    await store.verify('13800000001', '123456')

    expect(store.status).toBe('loggedIn')
    expect(store.userId).toBe(9)
    expect(tokenStore.access).toBe('a1')
    // 长期凭证由 HttpOnly Cookie 承载,JS 侧没有任何持久化令牌
    expect(localStorage.getItem('hb.access')).toBeNull()
    expect(localStorage.getItem('hb.refresh')).toBeNull()
  })

  it('verify 把 isNewUser 交给调用方(新用户要先去完善资料,与 App 一致)', async () => {
    server.use(
      mswHttp.post('/api/v1/auth/sms/verify', () =>
        HttpResponse.json({ access: 'a1', is_new_user: true, user_id: 9 }),
      ),
    )

    const result = await useSessionStore().verify('13800000001', '123456')

    expect(result.isNewUser).toBe(true)
  })

  it('verify 对老用户返回 isNewUser=false(不该被再拉去引导页)', async () => {
    server.use(
      mswHttp.post('/api/v1/auth/sms/verify', () =>
        HttpResponse.json({ access: 'a1', is_new_user: false, user_id: 9 }),
      ),
    )

    const result = await useSessionStore().verify('13800000001', '123456')

    expect(result.isNewUser).toBe(false)
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

  it('restore:没有 Cookie 也没有内存令牌 → loggedOut', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', unauthorized),
      mswHttp.post('/api/v1/auth/token/refresh', unauthorized),
    )
    const store = useSessionStore()

    await store.restore()

    expect(store.status).toBe('loggedOut')
  })

  it('restore:刷新成功后 /users/me 通 → loggedIn,user_id 取自接口', async () => {
    tokenStore.access = 'a'
    server.use(meHandler())
    const store = useSessionStore()

    await store.restore()

    expect(store.status).toBe('loggedIn')
    expect(store.userId).toBe(5)
  })

  it('logout 调接口清 Cookie 并回到 loggedOut', async () => {
    tokenStore.access = 'a'
    tokenStore.userId = 5
    server.use(meHandler(), logoutHandler())
    const store = useSessionStore()
    await store.restore()

    await store.logout()

    expect(store.status).toBe('loggedOut')
    expect(store.userId).toBeNull()
    expect(tokenStore.access).toBeNull()
  })

  it('logout 接口失败也要清本地,不能把用户卡在已登录态', async () => {
    tokenStore.access = 'a'
    server.use(
      mswHttp.post('/api/v1/auth/logout', () =>
        HttpResponse.json({ code: 500, message: '服务异常', request_id: 'r' }, { status: 500 }),
      ),
    )
    const store = useSessionStore()

    await store.logout()

    expect(store.status).toBe('loggedOut')
    expect(tokenStore.access).toBeNull()
  })

  it('被顶号事件把 kicked 置为 true 并清凭证', async () => {
    tokenStore.access = 'a'
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

  it('deleteAccount 只调接口,不自己清会话(清会话由页面编排)', async () => {
    tokenStore.access = 'a'
    tokenStore.userId = 5
    server.use(
      mswHttp.delete('/api/v1/users/me', () => new HttpResponse(null, { status: 204 })),
      logoutHandler(),
    )
    const store = useSessionStore()

    await store.deleteAccount('13800138000')

    expect(store.status).toBe('loading') // 未被自己改掉
    expect(tokenStore.access).toBe('a')
  })

  it('deleteAccount 失败向上抛(手机号不匹配)', async () => {
    server.use(
      mswHttp.delete('/api/v1/users/me', () =>
        HttpResponse.json(
          { code: 400, message: '手机号与当前账号不一致', request_id: 'r' },
          { status: 400 },
        ),
      ),
    )

    await expect(useSessionStore().deleteAccount('13900139000')).rejects.toMatchObject({
      code: 400,
    })
  })
})
