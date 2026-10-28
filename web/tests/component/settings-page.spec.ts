import { flushPromises, mount } from '@vue/test-utils'
import { HttpResponse, http as mswHttp } from 'msw'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from '@/features/settings/SettingsPage.vue'
import { tokenStore } from '@/api/token-store'
import { setImClientFactory } from '@/im/client'
import type { ImClient } from '@/im/types'
import { server } from '../support/server'

/** 退出登录要先登出 IM,这里给个最小假客户端(否则会去连真腾讯云)。 */
function stubIm() {
  const logout = vi.fn(async () => {})
  setImClientFactory(
    () =>
      ({
        onEvent: () => {},
        init: () => {},
        login: async () => {},
        logout,
        fetchConversations: async () => [],
        fetchHistory: async () => [],
        sendText: async () => ({}) as never,
        sendImage: async () => ({}) as never,
        deleteMessage: async () => {},
        markConversationRead: async () => {},
        deleteConversation: async () => {},
      }) as unknown as ImClient,
  )
  return { logout }
}

async function mountPage() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div/>' } },
      { path: '/login', name: 'login', component: { template: '<div/>' } },
    ],
  })
  await router.push('/')
  await router.isReady()
  const w = mount(SettingsPage, {
    global: {
      plugins: [createPinia(), router],
      stubs: { RouterLink: { template: '<a><slot /></a>' } },
    },
  })
  await flushPromises()
  return { w, router }
}

describe('SettingsPage', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    // 退出/注销都会调一次 /auth/logout 清 HttpOnly Cookie;MSW 未铺的请求会直接抛
    server.use(mswHttp.post('/api/v1/auth/logout', () => new HttpResponse(null, { status: 204 })))
  })

  it('列出全部设置入口', async () => {
    stubIm()
    const { w } = await mountPage()
    for (const label of [
      '编辑资料',
      '想找的人',
      '黑名单',
      '我的动态',
      '通知设置',
      '意见反馈',
      '关于',
      '用户协议',
      '隐私政策',
    ]) {
      expect(w.text()).toContain(label)
    }
  })

  it('确认后退出登录:先登出 IM,再清凭证并跳登录页', async () => {
    const im = stubIm()
    tokenStore.access = 'a'
    tokenStore.userId = 9
    vi.spyOn(window, 'confirm').mockReturnValue(true)

    const { w, router } = await mountPage()
    await w.find('.settings__logout').trigger('click')
    await flushPromises()

    expect(im.logout).toHaveBeenCalled()
    expect(tokenStore.access).toBeNull()
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('取消则不退出', async () => {
    stubIm()
    tokenStore.access = 'a'
    vi.spyOn(window, 'confirm').mockReturnValue(false)

    const { w } = await mountPage()
    await w.find('.settings__logout').trigger('click')
    await flushPromises()

    expect(tokenStore.access).toBe('a')
  })

  it('注销账号:两步确认后清会话并跳登录页', async () => {
    const im = stubIm()
    tokenStore.access = 'a'
    tokenStore.userId = 9
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    server.use(mswHttp.delete('/api/v1/users/me', () => new HttpResponse(null, { status: 204 })))

    const { w, router } = await mountPage()

    await w.find('.settings__delete').trigger('click')
    await flushPromises()

    // 弹窗:先填错 → 提交按钮禁用;填对 → 可提交
    const input = w.find('.delete-dialog__input input')
    const submit = w.find('.delete-dialog__confirm')
    expect(submit.attributes('disabled')).toBeDefined()

    await input.setValue('138')
    expect(submit.attributes('disabled')).toBeDefined()

    await input.setValue('13800138000')
    expect(submit.attributes('disabled')).toBeUndefined()

    await submit.trigger('click')
    await flushPromises()

    expect(im.logout).toHaveBeenCalled()
    expect(tokenStore.access).toBeNull()
    expect(router.currentRoute.value.path).toBe('/login')
  })

  it('注销失败(后端 400)留在设置页并显示错误', async () => {
    stubIm()
    tokenStore.access = 'a'
    tokenStore.userId = 9
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    // ⚠️ support/server.ts 是 onUnhandledRequest: 'error',未铺的请求会直接抛,
    // 所以必须显式铺一条 400 的 handler,不能靠「没铺 = 失败」。
    server.use(
      mswHttp.delete('/api/v1/users/me', () =>
        HttpResponse.json(
          { code: 400, message: '手机号与当前账号不一致', request_id: 'r' },
          { status: 400 },
        ),
      ),
    )

    const { w, router } = await mountPage()
    await w.find('.settings__delete').trigger('click')
    await flushPromises()
    await w.find('.delete-dialog__input input').setValue('13900139000')
    await w.find('.delete-dialog__confirm').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.path).toBe('/') // 没跳登录页
    expect(tokenStore.access).toBe('a') // 凭证没被清
    expect(w.find('.settings__error').text()).toContain('手机号与当前账号不一致')
  })
})
