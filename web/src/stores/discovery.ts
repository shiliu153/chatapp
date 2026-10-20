import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as discoveryApi from '@/api/discovery'
import { parseApiError } from '@/api/error'
import type { Candidate, MatchSummary } from '@/api/types'

const MATCHES_PAGE_SIZE = 20

export const useDiscoveryStore = defineStore('discovery', () => {
  const candidates = ref<Candidate[]>([])
  const index = ref(0)
  const matched = ref<Candidate | null>(null)
  const matches = ref<MatchSummary[]>([])
  const matchesCount = ref(0)
  const matchesOffset = ref(0)
  /** 配对列表至少成功拉过一次:聊天页据此判断「不在列表里 = 已被解除」 */
  const matchesLoaded = ref(false)
  const loading = ref(false)
  const submitting = ref(false)
  const error = ref('')

  const current = computed<Candidate | null>(() => candidates.value[index.value] ?? null)
  const exhausted = computed(() => !loading.value && current.value === null)

  async function loadCandidates(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      candidates.value = await discoveryApi.fetchCandidates()
      index.value = 0
    } catch (e) {
      error.value = parseApiError(e).message
    } finally {
      loading.value = false
    }
  }

  async function decide(action: 'like' | 'pass'): Promise<void> {
    const target = current.value
    if (!target || submitting.value) return
    submitting.value = true
    error.value = ''
    try {
      const result = await discoveryApi.swipe(target.user_id, action)
      index.value += 1
      if (result.matched) matched.value = target
    } catch (e) {
      const apiError = parseApiError(e)
      if (apiError.status === 404) {
        // 目标不存在/已不可见:跳过这张卡,不打扰用户(discovery.md §3.2)
        index.value += 1
      } else {
        // 403 轻封禁 / 429 限流:停住当前卡并展示后端文案
        error.value = apiError.message
      }
    } finally {
      submitting.value = false
    }
  }

  function dismissMatched(): void {
    matched.value = null
  }

  /** 配对列表;`reset` 用于下拉首刷,否则按 offset 追加。 */
  async function loadMatches(reset = false): Promise<void> {
    if (reset) {
      matches.value = []
      matchesOffset.value = 0
    }
    const page = await discoveryApi.fetchMatches(MATCHES_PAGE_SIZE, matchesOffset.value)
    matches.value = [...matches.value, ...page.results]
    matchesCount.value = page.count
    matchesOffset.value += page.results.length
    matchesLoaded.value = true
  }

  /** 解除配对:后端软删除 + 双向拉黑;本地立刻从配对列表移除。 */
  async function unmatch(userId: number): Promise<void> {
    await discoveryApi.unmatch(userId)
    matches.value = matches.value.filter((item) => item.user_id !== userId)
    matchesCount.value = Math.max(matchesCount.value - 1, 0)
  }

  return {
    candidates,
    index,
    matched,
    matches,
    matchesCount,
    matchesLoaded,
    loading,
    submitting,
    error,
    current,
    exhausted,
    loadCandidates,
    decide,
    dismissMatched,
    loadMatches,
    unmatch,
  }
})
