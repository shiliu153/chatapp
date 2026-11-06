import { http } from './http'
import type { AppNotification, CursorPage } from './types'

/** 站内通知列表:游标分页(首页 cursor 传 null,之后传上一页的 next_cursor)。 */
export async function fetchNotifications(
  limit = 20,
  cursor: string | null = null,
): Promise<CursorPage<AppNotification>> {
  const { data } = await http.get('/notifications', {
    params: { limit, before: cursor ?? undefined },
  })
  return data as CursorPage<AppNotification>
}

/** 未读数(消息页铃铛角标);与列表同口径(自己的、90 天内)。 */
export async function fetchUnreadCount(): Promise<number> {
  const { data } = await http.get('/notifications/unread_count')
  return Number(data.unread)
}

/**
 * 标记已读:`ids` 只标指定几条,`all: true` 标全部未读。
 *
 * 后端只影响自己的通知,别人的 id 会被静默过滤,仍返回 204。
 */
export async function markRead(ids?: number[], all = false): Promise<void> {
  await http.post('/notifications/read', {
    ...(ids ? { ids } : {}),
    ...(all ? { all: true } : {}),
  })
}
