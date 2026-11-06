import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as notificationsApi from '@/api/notifications'
import { parseApiError } from '@/api/error'
import type { AppNotification } from '@/api/types'

const PAGE_SIZE = 20

/**
 * 站内通知 store:列表(游标分页)、未读角标、标记已读。
 *
 * 标记已读后**本地先改状态**再刷新角标,避免用户回到消息页还看到旧角标;
 * 角标与列表同口径(后端只返回 90 天内、只返回自己的)。
 */
export const useNotificationsStore = defineStore('notifications', () => {
  const items = ref<AppNotification[]>([])
  const count = ref(0)
  /** 下一页游标:null = 没有下一页 */
  const cursor = ref<string | null>(null)
  const loading = ref(false)
  const error = ref('')
  const unread = ref(0)

  async function load(reset = false): Promise<void> {
    if (reset) {
      items.value = []
      cursor.value = null
    }
    loading.value = true
    error.value = ''
    try {
      const page = await notificationsApi.fetchNotifications(PAGE_SIZE, cursor.value)
      items.value = [...items.value, ...page.results]
      count.value = page.count
      cursor.value = page.next_cursor
    } catch (e) {
      error.value = parseApiError(e).message
      throw e
    } finally {
      loading.value = false
    }
  }

  /** 只拉未读数(消息页入口角标用)。 */
  async function loadUnread(): Promise<void> {
    unread.value = await notificationsApi.fetchUnreadCount()
  }

  /** 标记单条已读;已经读过的直接返回(不重复请求)。 */
  async function markOne(item: AppNotification): Promise<void> {
    if (item.is_read) return
    await notificationsApi.markRead([item.id])
    item.is_read = true
    await loadUnread()
  }

  /** 全部标记已读。 */
  async function markAll(): Promise<void> {
    await notificationsApi.markRead(undefined, true)
    for (const item of items.value) item.is_read = true
    unread.value = 0
  }

  return {
    items,
    count,
    cursor,
    loading,
    error,
    unread,
    load,
    loadUnread,
    markOne,
    markAll,
  }
})
