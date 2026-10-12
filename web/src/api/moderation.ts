import { http } from './http'
import type { Page, ReportType } from './types'

export interface BlockedUser {
  user_id: number
  nickname: string
  avatar_url: string | null
  blocked_at: string
}

export async function fetchBlocks(limit = 20, offset = 0): Promise<Page<BlockedUser>> {
  const { data } = await http.get('/blocks', { params: { limit, offset } })
  return data as Page<BlockedUser>
}

export async function blockUser(targetUserId: number): Promise<void> {
  await http.post('/blocks', { target_user_id: targetUserId })
}

export async function unblockUser(userId: number): Promise<void> {
  await http.delete(`/blocks/${userId}`)
}

export async function reportUser(
  targetUserId: number,
  type: ReportType,
  detail = '',
): Promise<void> {
  await http.post('/reports', { target_user_id: targetUserId, type, detail })
}
