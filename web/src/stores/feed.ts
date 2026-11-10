import { defineStore } from 'pinia'
import { computed, ref, type Ref } from 'vue'
import * as feedApi from '@/api/feed'
import { parseApiError } from '@/api/error'
import type { CursorPage, Post, PostLiker } from '@/api/types'

const PAGE_SIZE = 20

type Fetcher<T> = (limit: number, cursor: string | null) => Promise<CursorPage<T>>

/**
 * 一个游标分页列表的全部状态与分页行为。
 *
 * 广场「推荐」/「关注」两个 tab、我的收藏、点赞列表的数据链路完全一致,只差一个接口;
 * 抽成工厂后各处的「首屏/翻页追加/错误态」只写一份,不抽的话改一处忘一处是这类列表
 * 最常见的 bug。
 *
 * 元素类型是泛型:动态流与收藏是 `Post`,点赞列表是 `PostLiker` —— 它们只有 `results`
 * 的元素不同,分页协议(`count` / `next_cursor` / `has_more`)完全一样。
 */
function createFeedState<T>() {
  /** 列表元素(动态 / 点赞者,由泛型决定;不叫 posts 是因为点赞列表里不是动态) */
  const items = ref([]) as Ref<T[]>
  const count = ref(0)
  /** 下一页游标:null = 没有下一页(后端 next_cursor 原样存,回传时原样带上) */
  const cursor = ref<string | null>(null)
  const loading = ref(false)
  const loadingMore = ref(false)
  const error = ref('')

  const hasMore = computed(() => cursor.value !== null)

  async function loadPage(fetcher: Fetcher<T>, reset: boolean): Promise<void> {
    if (reset) {
      items.value = []
      cursor.value = null
    }
    if (items.value.length === 0) loading.value = true
    else loadingMore.value = true
    error.value = ''
    try {
      const page = await fetcher(PAGE_SIZE, cursor.value)
      items.value = [...items.value, ...page.results]
      count.value = page.count
      cursor.value = page.next_cursor
    } catch (e) {
      error.value = parseApiError(e).message
    } finally {
      loading.value = false
      loadingMore.value = false
    }
  }

  return { items, count, cursor, loading, loadingMore, error, hasMore, loadPage }
}

/** 乐观更新:先改界面,失败回滚(点赞是点缀信息,失败不打断浏览)。 */
async function toggleLikeIn(items: Ref<Post[]>, target: Post): Promise<void> {
  const index = items.value.findIndex((p) => p.id === target.id)
  if (index < 0) return
  const before = { ...items.value[index] }
  items.value[index] = {
    ...before,
    liked_by_me: !before.liked_by_me,
    like_count: before.like_count + (before.liked_by_me ? -1 : 1),
  }
  try {
    if (before.liked_by_me) await feedApi.unlikePost(before.id)
    else await feedApi.likePost(before.id)
  } catch {
    items.value[index] = before
  }
}

/**
 * 收藏的乐观更新:只翻 `is_favorited`,失败回滚。
 *
 * 收藏接口恒 204、不告诉客户端「是不是第一次」,所以这里不看响应体(与 `toggleLikeIn`
 * 同款:先改界面,失败把整条还原)。取消收藏**不把卡片从「我的收藏」里摘掉**:留着才能
 * 「手滑取消 → 再点回来」,重新进页面时后端自然不会再返回它。
 */
async function toggleFavoriteIn(items: Ref<Post[]>, target: Post): Promise<void> {
  const index = items.value.findIndex((p) => p.id === target.id)
  if (index < 0) return
  const before = { ...items.value[index] }
  items.value[index] = { ...before, is_favorited: !before.is_favorited }
  try {
    if (before.is_favorited) await feedApi.unfavoritePost(before.id)
    else await feedApi.favoritePost(before.id)
  } catch {
    items.value[index] = before
  }
}

/** 删除后本地移除并减计数(作者自删)。 */
async function removePostIn(
  items: Ref<Post[]>,
  count: Ref<number>,
  id: number,
): Promise<void> {
  await feedApi.deletePost(id)
  items.value = items.value.filter((p) => p.id !== id)
  count.value = Math.max(0, count.value - 1)
}

/** 广场「推荐」tab(全站可见动态)+ 我的动态 + 发布。 */
export const useFeedStore = defineStore('feed', () => {
  const state = createFeedState<Post>()
  const { items, count, loading, loadingMore, error, hasMore, loadPage } = state

  const load = (reset = false) => loadPage(feedApi.fetchPosts, reset)
  const loadMine = (reset = false) => loadPage(feedApi.fetchMyPosts, reset)
  const toggleLike = (target: Post) => toggleLikeIn(items, target)
  const toggleFavorite = (target: Post) => toggleFavoriteIn(items, target)
  const removePost = (id: number) => removePostIn(items, count, id)

  function prepend(post: Post): void {
    items.value = [post, ...items.value]
    count.value += 1
  }

  async function create(text: string, images: File[]): Promise<Post> {
    const post = await feedApi.createPost(text, images)
    prepend(post)
    return post
  }

  return {
    items,
    count,
    loading,
    loadingMore,
    error,
    hasMore,
    load,
    loadMine,
    toggleLike,
    toggleFavorite,
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
  const state = createFeedState<Post>()
  const { items, count, loading, loadingMore, error, hasMore, loadPage } = state

  const load = (reset = false) => loadPage(feedApi.fetchFollowing, reset)
  const toggleLike = (target: Post) => toggleLikeIn(items, target)
  const toggleFavorite = (target: Post) => toggleFavoriteIn(items, target)
  const removePost = (id: number) => removePostIn(items, count, id)

  return {
    items,
    count,
    loading,
    loadingMore,
    error,
    hasMore,
    load,
    toggleLike,
    toggleFavorite,
    removePost,
  }
})

/**
 * 我的收藏(批次 U,feed.md §5.19):按收藏时间倒序。
 *
 * 与广场、关注流各用一份 `createFeedState` 实例:三个列表必须互不覆盖。
 * 可见性由后端负责(收藏了但已不可见的动态既不返回也不计入 `count`)。
 */
export const useFavoritesStore = defineStore('favorites', () => {
  const state = createFeedState<Post>()
  const { items, count, loading, loadingMore, error, hasMore, loadPage } = state

  const load = (reset = false) => loadPage(feedApi.fetchFavorites, reset)
  const toggleLike = (target: Post) => toggleLikeIn(items, target)
  const toggleFavorite = (target: Post) => toggleFavoriteIn(items, target)

  return { items, count, loading, loadingMore, error, hasMore, load, toggleLike, toggleFavorite }
})

/**
 * 点赞列表(批次 U,feed.md §5.16):某条动态「谁点了赞」,按点赞时间倒序。
 *
 * 元素是 `PostLiker` 而不是 `Post`,所以只复用分页骨架,没有点赞/收藏这类写操作。
 * 先 `load(postId, true)` 进页面,`loadMore()` 翻页;`count` 是**过滤后**的可见人数,
 * 可能小于动态上的 `like_count`。
 */
export const usePostLikesStore = defineStore('post-likes', () => {
  const state = createFeedState<PostLiker>()
  const { items, count, loading, loadingMore, error, hasMore, loadPage } = state
  const currentId = ref<number | null>(null)

  const fetchPage: Fetcher<PostLiker> = (limit, cursor) =>
    feedApi.fetchPostLikes(currentId.value ?? 0, limit, cursor)

  async function load(postId: number, reset = false): Promise<void> {
    currentId.value = postId
    await loadPage(fetchPage, reset)
  }

  /** 翻下一页;还没进过页面(没有 postId)时不动 */
  async function loadMore(): Promise<void> {
    if (currentId.value === null) return
    await loadPage(fetchPage, false)
  }

  return { items, count, loading, loadingMore, error, hasMore, load, loadMore }
})
