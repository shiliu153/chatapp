import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as statsApi from '@/api/stats'
import { parseApiError } from '@/api/error'
import type { MyStats, StatsPeriod } from '@/api/types'

/** 周期分段控件的三态(stats.md §1.1);默认周,与 App 侧一致。 */
export const STATS_PERIODS: readonly { value: StatsPeriod; label: string }[] = [
  { value: 'week', label: '周' },
  { value: 'month', label: '月' },
  { value: 'year', label: '年' },
]

/** 七张数字卡的业务键:既是 `MyStats` 的字段名,也是模板里的 `key`。 */
type StatKey =
  | 'matches'
  | 'likes_given'
  | 'likes_received'
  | 'visits'
  | 'posts'
  | 'post_likes'
  | 'new_followers'

/** 七项数字的展示顺序与中文标签(顺序即页面上的摆版顺序)。 */
export const STAT_CARDS: readonly { key: StatKey; label: string }[] = [
  { key: 'matches', label: '新的配对' },
  { key: 'likes_given', label: '喜欢给出' },
  { key: 'likes_received', label: '喜欢收到' },
  { key: 'visits', label: '访客' },
  { key: 'posts', label: '动态' },
  { key: 'post_likes', label: '动态获赞' },
  { key: 'new_followers', label: '新粉丝' },
]

/** 一张数字卡的展示模型:数字 + 中文标签。 */
export interface StatCard {
  key: StatKey
  label: string
  /** 0 是有效值,页面必须原样显示 `0`(不是空白) */
  value: number
}

export const useStatsStore = defineStore('stats', () => {
  /** 当前周期;默认 `week`(验收口径:默认周) */
  const period = ref<StatsPeriod>('week')
  /** 最近一次成功的报告;周期切换时先清空,避免旧数字与新区间标签混搭 */
  const report = ref<MyStats | null>(null)
  const loading = ref(false)
  const error = ref('')

  /**
   * 请求序号:快速连点周期时,先发后到的旧响应必须被丢弃,
   * 否则界面会显示「月」的选中态配「周」的数字。
   */
  let seq = 0

  /** 统计范围文案,如「2026-11-09 ~ 2026-11-15」;没有数据时为空串。 */
  const rangeText = computed<string>(() =>
    report.value ? `${report.value.start} ~ ${report.value.end}` : '',
  )

  /** 七张卡(固定顺序、固定标签);没有数据时按 0 兜底,页面对应分支不会渲染它。 */
  const cards = computed<StatCard[]>(() =>
    STAT_CARDS.map(({ key, label }) => ({ key, label, value: report.value?.[key] ?? 0 })),
  )

  /**
   * 拉取当前周期的报告。
   *
   * 失败**不吞**:`error` 给页面展示,同时向上抛,调用方按需 `.catch()`。
   */
  async function load(): Promise<void> {
    const id = ++seq
    loading.value = true
    error.value = ''
    try {
      const data = await statsApi.fetchMyStats(period.value)
      if (id !== seq) return
      report.value = data
    } catch (e) {
      if (id === seq) error.value = parseApiError(e).message
      throw e
    } finally {
      if (id === seq) loading.value = false
    }
  }

  /**
   * 切换周期并重新请求。同值不重复请求(分段控件也已在同值时不发事件)。
   */
  async function setPeriod(next: StatsPeriod): Promise<void> {
    if (next === period.value) return
    period.value = next
    report.value = null
    await load()
  }

  return { period, report, loading, error, rangeText, cards, load, setPeriod }
})
