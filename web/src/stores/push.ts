import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as pushApi from '@/api/push'
import type { PushPreferences } from '@/api/push'
import { parseApiError } from '@/api/error'

/** 通知偏好:账号级,网页端改了对 App 生效。 */
export const usePushStore = defineStore('push', () => {
  const prefs = ref<PushPreferences | null>(null)
  const loading = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      prefs.value = await pushApi.getPushPreferences()
    } catch (e) {
      error.value = parseApiError(e).message
    } finally {
      loading.value = false
    }
  }

  /** 乐观更新;失败回滚到切换前的值并把错误写进 error。 */
  async function toggle(key: keyof PushPreferences, value: boolean): Promise<void> {
    const current = prefs.value
    if (!current) return
    prefs.value = { ...current, [key]: value }
    error.value = ''
    try {
      prefs.value = await pushApi.updatePushPreferences({ [key]: value })
    } catch (e) {
      prefs.value = current
      error.value = parseApiError(e).message
    }
  }

  return { prefs, loading, error, load, toggle }
})
