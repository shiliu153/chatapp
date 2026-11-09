import { http } from './http'
import type { MyStats, StatsPeriod } from './types'

/**
 * 我的使用报告(stats.md §1.1)。
 *
 * 只读聚合,没有副作用;`period` 缺省时后端按 `week` 处理,前端每次都显式带上,
 * 让「当前看的是哪个周期」只有 store 一处事实来源。
 */
export async function fetchMyStats(period: StatsPeriod): Promise<MyStats> {
  const { data } = await http.get('/stats/me', { params: { period } })
  return data as MyStats
}
