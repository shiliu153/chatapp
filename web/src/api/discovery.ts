import { http } from './http'
import type {
  Candidate,
  CursorPage,
  DailyCandidates,
  DiscoveryFilters,
  LikeReceived,
  MatchSummary,
  ProfileVisit,
  SwipeQuota,
  SwipeUndoResult,
  Tag,
} from './types'

/** 「今日精选」固定 6 张(discovery.md §3.11:默认 6、上限 12)。 */
export const DAILY_LIMIT = 6

/**
 * 把筛选对象翻译成**查询参数**:只发用户真正改过的字段。
 *
 * 后端对缺省字段沿用「想找的人」偏好(discovery.md §3.1),所以空串 / 空数组 / undefined
 * 一律不进请求 —— 「只改城市」时年龄区间不会顺带被钉死成面板里的默认值。
 * 抽成纯函数是为了让 store 能直接用它判断「当前是否处于筛选态」。
 */
export function filtersToParams(filters: DiscoveryFilters): Record<string, string | number> {
  const params: Record<string, string | number> = {}
  if (filters.age_min !== undefined) params.age_min = filters.age_min
  if (filters.age_max !== undefined) params.age_max = filters.age_max
  const city = filters.city?.trim()
  if (city) params.city = city
  if (filters.tag_ids && filters.tag_ids.length > 0) params.tag_ids = [...filters.tag_ids].join(',')
  return params
}

/**
 * 候选卡(discovery.md §3.1);响应是**裸数组**。
 *
 * `filters` 里的字段**覆盖**偏好,缺省的字段继续按偏好筛 —— 不传就是改动前的行为。
 */
export async function fetchCandidates(
  limit = 10,
  filters: DiscoveryFilters = {},
): Promise<Candidate[]> {
  const { data } = await http.get('/discovery/candidates', {
    params: { limit, ...filtersToParams(filters) },
  })
  return data as Candidate[]
}

/**
 * 「今日精选」(discovery.md §3.11)。
 *
 * 响应是**包装对象** `{date, candidates}` —— 不是 `candidates` 接口那种裸数组,
 * 按数组解析会直接拿到 `undefined`。
 */
export async function fetchDaily(limit = DAILY_LIMIT): Promise<DailyCandidates> {
  const { data } = await http.get('/discovery/daily', { params: { limit } })
  return {
    date: String(data?.date ?? ''),
    candidates: (data?.candidates ?? []) as Candidate[],
  }
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

/**
 * 撤销最近一次滑卡(discovery.md §3.9):不需要请求体。
 *
 * 能不能撤销由后端判定(30 秒内 / 未产生配对 / 还有记录),失败一律 `400` + `40003`,
 * 客户端不要自己重试;`target_user_id` 是那张卡的主人,**按它把卡放回卡堆**。
 */
export async function undoSwipe(): Promise<SwipeUndoResult> {
  const { data } = await http.post('/discovery/swipe/undo')
  return {
    undone: Boolean(data.undone),
    target_user_id: Number(data.target_user_id),
  }
}

/**
 * 每日喜欢额度(discovery.md §3.10)。
 *
 * `like_limit = 0` 表示不限(`likes_remaining` 为 `null`),此时页面**不显示**任何额度文案。
 * 接口无额外限流,但也不必每次滑卡都调:成功 like 时本地递减、撤销 like 时退回,
 * 页面挂载与额度封禁到期时再各对账一次。
 */
export async function fetchQuota(): Promise<SwipeQuota> {
  const { data } = await http.get('/discovery/quota')
  return data as SwipeQuota
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
