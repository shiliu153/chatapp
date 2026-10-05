import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import SettingsPage from '@/features/settings/SettingsPage.vue'
import { tokenStore } from '@/api/token-store'
import { setImClientFactory } from '@/im/client'
import type { ImClient } from '@/im/types'

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
  })

  it('列出全部设置入口', async () => {
    stubIm()
    const { w } = await mountPage()
    for (const label of ['编辑资料', '想找的人', '黑名单', '我的动态', '用户协议', '隐私政策']) {
      expect(w.text()).toContain(label)
    }
  })

  it('确认后退出登录:先登出 IM,再清凭证并跳登录页', async () => {
    const im = stubIm()
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
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
})
