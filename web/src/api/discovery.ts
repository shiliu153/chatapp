import { http } from './http'
import type {
  Candidate,
  CursorPage,
  LikeReceived,
  MatchSummary,
  ProfileVisit,
  Tag,
} from './types'

export async function fetchCandidates(limit = 10): Promise<Candidate[]> {
  const { data } = await http.get('/discovery/candidates', { params: { limit } })
  return data as Candidate[]
}

/**
 * 幂等:重复提交同一目标,matched 返回值不变。
 * 配对成功时后端直接带回 `shared_tags`,用来渲染「配对那一刻」的破冰文案 ——
 * 不要再为了它去拉 `GET /users/{id}`,那会被记成一次访客访问(discovery.md §3.2)。
 */
export async function swipe(
  targetUserId: number,
  action: 'like' | 'pass',
): Promise<{ matched: boolean; shared_tags: Tag[] }> {
  const { data } = await http.post('/discovery/swipe', {
    target_user_id: targetUserId,
    action,
  })
  return {
    matched: Boolean(data.matched),
    shared_tags: (data.shared_tags ?? []) as Tag[],
  }
}

/** 配对列表:游标分页(首页 cursor 传 null,之后传上一页的 next_cursor)。 */
export async function fetchMatches(
  limit = 20,
  cursor: string | null = null,
): Promise<CursorPage<MatchSummary>> {
  const { data } = await http.get('/matches', { params: { limit, before: cursor ?? undefined } })
  return data as CursorPage<MatchSummary>
}

/** 解除配对:幂等(没配对也 204);解除后双方 IM 互相拉黑。 */
export async function unmatch(userId: number): Promise<void> {
  await http.delete(`/matches/${userId}`)
}

export async function fetchLikesReceived(
  limit = 20,
  cursor: string | null = null,
): Promise<CursorPage<LikeReceived>> {
  const { data } = await http.get('/discovery/likes', {
    params: { limit, before: cursor ?? undefined },
  })
  return data as CursorPage<LikeReceived>
}

export async function fetchLikesReceivedCount(): Promise<number> {
  const { data } = await http.get('/discovery/likes/count')
  return Number(data.count)
}

export async function fetchVisits(
  limit = 20,
  cursor: string | null = null,
): Promise<CursorPage<ProfileVisit>> {
  const { data } = await http.get('/discovery/visits', {
    params: { limit, before: cursor ?? undefined },
  })
  return data as CursorPage<ProfileVisit>
}

export async function fetchVisitsCount(): Promise<number> {
  const { data } = await http.get('/discovery/visits/count')
  return Number(data.count)
}
