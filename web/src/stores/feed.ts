import { defineStore } from 'pinia'
import { computed, ref, type Ref } from 'vue'
import * as feedApi from '@/api/feed'
import { parseApiError } from '@/api/error'
import type { CursorPage, Post } from '@/api/types'

const PAGE_SIZE = 20

type Fetcher = (limit: number, cursor: string | null) => Promise<CursorPage<Post>>

/**
 * 一个动态流列表的全部状态与分页行为。
 *
 * 广场「推荐」与「关注」两个 tab 的数据链路完全一致,只差一个接口
 * (`/posts` vs `/feed/following`);抽成工厂后两边的「首屏/翻页追加/错误态」
 * 只写一份,不抽的话改一处忘一处是这类列表最常见的 bug。
 */
function createFeedState() {
  const posts = ref<Post[]>([])
  const count = ref(0)
  /** 下一页游标:null = 没有下一页(后端 next_cursor 原样存,回传时原样带上) */
  const cursor = ref<string | null>(null)
  const loading = ref(false)
  const loadingMore = ref(false)
  const error = ref('')

  const hasMore = computed(() => cursor.value !== null)

  async function loadPage(fetcher: Fetcher, reset: boolean): Promise<void> {
    if (reset) {
      posts.value = []
      cursor.value = null
    }
    if (posts.value.length === 0) loading.value = true
    else loadingMore.value = true
    error.value = ''
    try {
      const page = await fetcher(PAGE_SIZE, cursor.value)
      posts.value = [...posts.value, ...page.results]
      count.value = page.count
      cursor.value = page.next_cursor
    } catch (e) {
      error.value = parseApiError(e).message
    } finally {
      loading.value = false
      loadingMore.value = false
    }
  }

  return { posts, count, cursor, loading, loadingMore, error, hasMore, loadPage }
}

/** 乐观更新:先改界面,失败回滚(点赞是点缀信息,失败不打断浏览)。 */
async function toggleLikeIn(posts: Ref<Post[]>, target: Post): Promise<void> {
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

/** 删除后本地移除并减计数(作者自删)。 */
async function removePostIn(
  posts: Ref<Post[]>,
  count: Ref<number>,
  id: number,
): Promise<void> {
  await feedApi.deletePost(id)
  posts.value = posts.value.filter((p) => p.id !== id)
  count.value = Math.max(0, count.value - 1)
}

/** 广场「推荐」tab(全站可见动态)+ 我的动态 + 发布。 */
export const useFeedStore = defineStore('feed', () => {
  const state = createFeedState()
  const { posts, count, loading, loadingMore, error, hasMore, loadPage } = state

  const load = (reset = false) => loadPage(feedApi.fetchPosts, reset)
  const loadMine = (reset = false) => loadPage(feedApi.fetchMyPosts, reset)
  const toggleLike = (target: Post) => toggleLikeIn(posts, target)
  const removePost = (id: number) => removePostIn(posts, count, id)

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

/**
 * 广场「关注」tab(批次 I):只含我关注的人的动态,不含自己。
 *
 * 独立 store 而不是复用 `useFeedStore`:两个 tab 的列表必须互不覆盖,
 * 否则切一下 tab 就串数据。
 */
export const useFollowingFeedStore = defineStore('following-feed', () => {
  const state = createFeedState()
  const { posts, count, loading, loadingMore, error, hasMore, loadPage } = state

  const load = (reset = false) => loadPage(feedApi.fetchFollowing, reset)
  const toggleLike = (target: Post) => toggleLikeIn(posts, target)
  const removePost = (id: number) => removePostIn(posts, count, id)

  return { posts, count, loading, loadingMore, error, hasMore, load, toggleLike, removePost }
})
