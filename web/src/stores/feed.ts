import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as feedApi from '@/api/feed'
import { parseApiError } from '@/api/error'
import type { Post } from '@/api/types'

const PAGE_SIZE = 20

type Fetcher = (limit: number, offset: number) => Promise<{ count: number; results: Post[] }>

export const useFeedStore = defineStore('feed', () => {
  const posts = ref<Post[]>([])
  const count = ref(0)
  const offset = ref(0)
  const loading = ref(false)
  const loadingMore = ref(false)
  const error = ref('')

  const hasMore = computed(() => posts.value.length < count.value)

  async function loadPage(fetcher: Fetcher, reset: boolean): Promise<void> {
    if (reset) {
      posts.value = []
      offset.value = 0
    }
    if (posts.value.length === 0) loading.value = true
    else loadingMore.value = true
    error.value = ''
    try {
      const page = await fetcher(PAGE_SIZE, offset.value)
      posts.value = [...posts.value, ...page.results]
      count.value = page.count
      offset.value += page.results.length
    } catch (e) {
      error.value = parseApiError(e).message
    } finally {
      loading.value = false
      loadingMore.value = false
    }
  }

  const load = (reset = false) => loadPage(feedApi.fetchPosts as Fetcher, reset)
  const loadMine = (reset = false) => loadPage(feedApi.fetchMyPosts as Fetcher, reset)

  /** 乐观更新:先改界面,失败回滚(点赞是点缀信息,失败不打断浏览)。 */
  async function toggleLike(target: Post): Promise<void> {
    const index = posts.value.findIndex((p) => p.id === target.id)
    if (index < 0) return
    const before = { ...posts.value[index] }
    posts.value[index] = {
      ...before,
      liked_by_me: !before.liked_by_me,
      like_count: before.like_count + (before.liked_by_me ? -1 : 1),
    }
    try {
      if (before.liked_by_me) await feedApi.unlikePost(before.id)
      else await feedApi.likePost(before.id)
    } catch {
      posts.value[index] = before
    }
  }

  async function removePost(id: number): Promise<void> {
    await feedApi.deletePost(id)
    posts.value = posts.value.filter((p) => p.id !== id)
    count.value = Math.max(0, count.value - 1)
  }

  function prepend(post: Post): void {
    posts.value = [post, ...posts.value]
    count.value += 1
  }

  async function create(text: string, images: File[]): Promise<Post> {
    const post = await feedApi.createPost(text, images)
    prepend(post)
    return post
  }

  return {
    posts,
    count,
    loading,
    loadingMore,
    error,
    hasMore,
    load,
    loadMine,
    toggleLike,
    removePost,
    prepend,
    create,
  }
})
