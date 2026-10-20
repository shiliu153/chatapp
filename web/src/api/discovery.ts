import { http } from './http'
import type { Candidate, LikeReceived, MatchSummary, Page } from './types'

export async function fetchCandidates(limit = 10): Promise<Candidate[]> {
  const { data } = await http.get('/discovery/candidates', { params: { limit } })
  return data as Candidate[]
}

/** 幂等:重复提交同一目标,matched 返回值不变。 */
export async function swipe(
  targetUserId: number,
  action: 'like' | 'pass',
): Promise<{ matched: boolean }> {
  const { data } = await http.post('/discovery/swipe', {
    target_user_id: targetUserId,
    action,
  })
  return { matched: Boolean(data.matched) }
}

export async function fetchMatches(limit = 20, offset = 0): Promise<Page<MatchSummary>> {
  const { data } = await http.get('/matches', { params: { limit, offset } })
  return data as Page<MatchSummary>
}

export async function fetchLikesReceived(
  limit = 20,
  offset = 0,
): Promise<Page<LikeReceived>> {
  const { data } = await http.get('/discovery/likes', { params: { limit, offset } })
  return data as Page<LikeReceived>
}

export async function fetchLikesReceivedCount(): Promise<number> {
  const { data } = await http.get('/discovery/likes/count')
  return Number(data.count)
}
