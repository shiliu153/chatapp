import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as authApi from '@/api/auth'
import { http } from '@/api/http'
import { sessionEvents } from '@/api/session-events'
import { tokenStore } from '@/api/token-store'

export type SessionStatus = 'loading' | 'loggedOut' | 'loggedIn'

export const useSessionStore = defineStore('session', () => {
  const status = ref<SessionStatus>('loading')
  const userId = ref<number | null>(tokenStore.userId)
  const kicked = ref(false)

  /** 被顶号 / 刷新失败:清凭证回登录态。kicked 只在被顶号时为 true。 */
  function resetSession(isKicked: boolean): void {
    tokenStore.clear()
    userId.value = null
    status.value = 'loggedOut'
    if (isKicked) kicked.value = true
  }

  // http 层只发事件,不反向依赖 store
  sessionEvents.onKickedOffline(() => resetSession(true))
  sessionEvents.onSessionExpired(() => resetSession(false))

  async function sendCode(phone: string): Promise<void> {
    await authApi.sendCode(phone)
  }

  async function verify(phone: string, code: string): Promise<void> {
    const result = await authApi.verify(phone, code)
    tokenStore.access = result.access
    tokenStore.refresh = result.refresh
    tokenStore.userId = result.userId
    userId.value = result.userId
    status.value = 'loggedIn'
  }

  function logout(): void {
    resetSession(false)
  }

  async function restore(): Promise<void> {
    if (!tokenStore.access || !tokenStore.refresh) {
      status.value = 'loggedOut'
      return
    }
    try {
      await http.get('/users/me')
      userId.value = tokenStore.userId
      status.value = 'loggedIn'
    } catch {
      // 拦截器已按 401 / 40101 分支清理过凭证;这里只兜底成未登录态
      status.value = tokenStore.access ? 'loggedIn' : 'loggedOut'
    }
  }

  function acknowledgeKicked(): void {
    kicked.value = false
  }

  return { status, userId, kicked, sendCode, verify, logout, restore, acknowledgeKicked }
})
