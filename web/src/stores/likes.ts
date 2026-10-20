import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as discoveryApi from '@/api/discovery'
import { parseApiError } from '@/api/error'
import type { Candidate, LikeReceived } from '@/api/types'

const PAGE_SIZE = 20

export const useLikesStore = defineStore('likes', () => {
  const items = ref<LikeReceived[]>([])
  const count = ref(0)
  const offset = ref(0)
  const loading = ref(false)
  const error = ref('')
  const busyUserId = ref<number | null>(null)
  const matched = ref<Candidate | null>(null)

  async function load(reset = false): Promise<void> {
    if (reset) {
      items.value = []
      offset.value = 0
    }
    loading.value = true
    error.value = ''
    try {
      const page = await discoveryApi.fetchLikesReceived(PAGE_SIZE, offset.value)
      items.value = [...items.value, ...page.results]
      count.value = page.count
      offset.value += page.results.length
    } catch (e) {
      error.value = parseApiError(e).message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function loadCount(): Promise<void> {
    count.value = await discoveryApi.fetchLikesReceivedCount()
  }

  async function accept(userId: number): Promise<void> {
    const target = items.value.find((item) => item.user_id === userId)
    busyUserId.value = userId
    error.value = ''
    try {
      const result = await discoveryApi.swipe(userId, 'like')
      items.value = items.value.filter((item) => item.user_id !== userId)
      count.value = Math.max(0, count.value - 1)
      if (result.matched && target) matched.value = target
    } catch (e) {
      error.value = parseApiError(e).message
      throw e
    } finally {
      busyUserId.value = null
    }
  }

  function dismissMatched(): void {
    matched.value = null
  }

  return {
    items,
    count,
    loading,
    error,
    busyUserId,
    matched,
    load,
    loadCount,
    accept,
    dismissMatched,
  }
})
