import { HttpResponse, http as mswHttp } from 'msw'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { tokenStore } from '@/api/token-store'
import { createAppRouter } from '@/router'
import { server } from '../support/server'

// 移动端判定由 Task 3.2 提供;本文件固定为「桌面」,移动端另有用例
vi.mock('@/composables/useDevice', () => ({ isMobileDevice: () => false }))

const meHandler = () => mswHttp.get('/api/v1/users/me', () => HttpResponse.json({ id: 1 }))

function loginLocally() {
  tokenStore.access = 'a'
  tokenStore.refresh = 'r'
  tokenStore.userId = 5
}

describe('路由守卫(桌面)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    localStorage.setItem('hb.legalAgreed', '1')
  })

  it('未登录访问 /home 被送到 /login', async () => {
    const router = createAppRouter()
    await router.push('/home')
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('未登录可以访问协议全文(公开路由)', async () => {
    const router = createAppRouter()
    await router.push('/legal/privacy')
    expect(router.currentRoute.value.path).toBe('/legal/privacy')
  })

  it('已登录访问 /login 被送回首页发现页', async () => {
    loginLocally()
    server.use(meHandler())
    const router = createAppRouter()
    await router.push('/login')
    expect(router.currentRoute.value.path).toBe('/home/discovery')
  })

  it('已登录访问 /home 落在发现页(默认子路由)', async () => {
    loginLocally()
    server.use(meHandler())
    const router = createAppRouter()
    await router.push('/home')
    expect(router.currentRoute.value.path).toBe('/home/discovery')
  })
})

describe('路由守卫(移动端)', () => {
  it('移动端浏览器一律进引导页', async () => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.resetModules()
    vi.doMock('@/composables/useDevice', () => ({ isMobileDevice: () => true }))
    const { createAppRouter: make } = await import('@/router')
    const router = make()
    await router.push('/')
    expect(router.currentRoute.value.path).toBe('/mobile-guard')
    vi.doUnmock('@/composables/useDevice')
  })
})
