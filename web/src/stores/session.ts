import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as authApi from '@/api/auth'
import { http } from '@/api/http'
import { sessionEvents } from '@/api/session-events'
import { tokenStore } from '@/api/token-store'
import * as usersApi from '@/api/users'

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

  /**
   * 校验验证码并登录。**返回 `isNewUser`** —— 新用户要先去 `/onboarding` 完善资料
   * (与 App 的 `login_page.dart` 一致:新号不完善资料就永远进不了别人的候选卡)。
   */
  async function verify(phone: string, code: string): Promise<{ isNewUser: boolean }> {
    const result = await authApi.verify(phone, code)
    tokenStore.access = result.access
    tokenStore.refresh = result.refresh
    tokenStore.userId = result.userId
    userId.value = result.userId
    status.value = 'loggedIn'
    return { isNewUser: result.isNewUser }
  }

  function logout(): void {
    resetSession(false)
  }

  /**
   * 注销账号:**只调接口**,失败向上抛。
   * 清会话与跳转留在页面编排(与 onLogout 同一条路径:先断 IM 再清会话)。
   */
  async function deleteAccount(phone: string): Promise<void> {
    await usersApi.deleteAccount(phone)
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

  return { status, userId, kicked, sendCode, verify, deleteAccount, logout, restore, acknowledgeKicked }
})
