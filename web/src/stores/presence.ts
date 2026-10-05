import { defineStore } from 'pinia'
import { onScopeDispose, ref } from 'vue'
import { http } from '@/api/http'
import { HEARTBEAT_INTERVAL_MS } from '@/constants'

/**
 * 在线状态。**轮询本身就是心跳** —— 后端口径是「120 秒内有认证请求即在线」,
 * 所以这里 45 秒拉一次 `GET /presence` 既取回别人是否在线,也把自己标记成在线
 * (与 App 的 presence_controller.dart 完全一致,没有单独的「心跳接口」)。
 *
 * Web 差异(spec §8):`document.hidden` 时停止轮询,重新可见立刻补一次。
 */

/** 后端单次查询上限(chatapp/users/presence.py::PRESENCE_MAX_IDS)。 */
const BATCH_SIZE = 100

export interface PresenceItem {
  user_id: number
  online: boolean
  last_active_at: string | null
}

export const usePresenceStore = defineStore('presence', () => {
  const online = ref<Map<number, boolean>>(new Map())
  /** 各页面登记自己关心的人:合并去重后一轮只发一次请求 */
  const owners = new Map<string, number[]>()
  let timer: number | undefined
  let scheduled = false

  function track(owner: string, ids: number[]): void {
    const current = owners.get(owner)
    if (current && current.length === ids.length && ids.every((id) => current.includes(id))) return
    owners.set(owner, [...ids])
    startTimer()
    scheduleFetch()
  }

  /** 同一轮内的多次 track 合并成一次请求(微任务合并) */
  function scheduleFetch(): void {
    if (scheduled) return
    scheduled = true
    queueMicrotask(async () => {
      scheduled = false
      await refresh()
    })
  }

  async function refresh(): Promise<void> {
    if (document.hidden) return // 页面不可见时不轮询
    const ids = [...new Set([...owners.values()].flat())]
    if (ids.length === 0) return
    try {
      const next = new Map(online.value)
      for (let start = 0; start < ids.length; start += BATCH_SIZE) {
        const chunk = ids.slice(start, start + BATCH_SIZE)
        const { data } = await http.get('/presence', { params: { user_ids: chunk.join(',') } })
        for (const item of (data.results ?? []) as PresenceItem[]) {
          next.set(item.user_id, item.online)
        }
      }
      online.value = next
    } catch {
      // 网络抖动:保留旧值,下个周期再试(点缀信息,不打扰用户)
    }
  }

  function startTimer(): void {
    if (timer !== undefined) return
    timer = window.setInterval(() => {
      void refresh()
    }, HEARTBEAT_INTERVAL_MS)
  }

  function stop(): void {
    if (timer !== undefined) window.clearInterval(timer)
    timer = undefined
  }

  function start(): void {
    startTimer()
    void refresh()
  }

  function onVisibilityChange(): void {
    if (document.hidden) {
      stop()
      return
    }
    startTimer()
    void refresh() // 重新可见立即补一次
  }

  document.addEventListener('visibilitychange', onVisibilityChange)

  // 全局监听与定时器必须随 store 一起回收(Pinia setup 跑在 effectScope 里):
  // 否则重复创建 store(测试、退出后重新登录)会留下幽灵监听,一起抢着打请求。
  onScopeDispose(() => {
    stop()
    document.removeEventListener('visibilitychange', onVisibilityChange)
  })

  function isOnline(userId: number): boolean {
    return online.value.get(userId) ?? false
  }

  return { online, track, refresh, isOnline, start, stop }
})
