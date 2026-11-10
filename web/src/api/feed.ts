import { http } from './http'
import type { Comment, CursorPage, Page, Post, PostLiker, ReportType } from './types'

/** 动态流:游标分页(首页 cursor 传 null,之后传上一页的 next_cursor)。 */
export async function fetchPosts(limit = 20, cursor: string | null = null): Promise<CursorPage<Post>> {
  const { data } = await http.get('/posts', { params: { limit, before: cursor ?? undefined } })
  return data as CursorPage<Post>
}

export async function fetchMyPosts(
  limit = 20,
  cursor: string | null = null,
): Promise<CursorPage<Post>> {
  const { data } = await http.get('/posts/mine', { params: { limit, before: cursor ?? undefined } })
  return data as CursorPage<Post>
}

/**
 * 关注流(批次 I,feed.md §5.15):只含我关注的人的动态,不含自己。
 * 分页协议与广场一致(游标),可见性口径也一致(排除双向拉黑与重封禁作者)。
 */
export async function fetchFollowing(
  limit = 20,
  cursor: string | null = null,
): Promise<CursorPage<Post>> {
  const { data } = await http.get('/feed/following', {
    params: { limit, before: cursor ?? undefined },
  })
  return data as CursorPage<Post>
}

export async function fetchPost(id: number): Promise<Post> {
  const { data } = await http.get(`/posts/${id}`)
  return data as Post
}

/** 图片字段名固定为 images,同一字段名重复追加(feed.md §5.2)。 */
export async function createPost(text: string, images: File[]): Promise<Post> {
  const form = new FormData()
  if (text) form.append('text', text)
  images.forEach((file) => form.append('images', file))
  const { data } = await http.post('/posts', form)
  return data as Post
}

export async function deletePost(id: number): Promise<void> {
  await http.delete(`/posts/${id}`)
}

export async function likePost(id: number): Promise<void> {
  await http.post(`/posts/${id}/like`)
}

export async function unlikePost(id: number): Promise<void> {
  await http.delete(`/posts/${id}/like`)
}

/**
 * 点赞列表(feed.md §5.16):谁点了这条动态,按点赞时间倒序。
 *
 * 与动态上显示的 `like_count` **不是同一个口径** —— 这里的 `count` 是过滤掉
 * 「双向拉黑 / 作者被重封禁」之后的可见人数,所以可能比 `like_count` 小。
 */
export async function fetchPostLikes(
  postId: number,
  limit = 20,
  cursor: string | null = null,
): Promise<CursorPage<PostLiker>> {
  const { data } = await http.get(`/posts/${postId}/likes`, {
    params: { limit, before: cursor ?? undefined },
  })
  return data as CursorPage<PostLiker>
}

/**
 * 收藏 / 取消收藏(feed.md §5.17、§5.18):两个都是**恒 204 的幂等写**。
 *
 * 因为不返回「是不是第一次」,客户端只做乐观翻转;返回 204 就当作成功,
 * 不要靠响应体判断状态。
 */
export async function favoritePost(id: number): Promise<void> {
  await http.post(`/posts/${id}/favorite`)
}

export async function unfavoritePost(id: number): Promise<void> {
  await http.delete(`/posts/${id}/favorite`)
}

/**
 * 我的收藏(feed.md §5.19):**按收藏时间倒序**,不是发帖时间。
 *
 * 响应与广场动态流逐字段一致(含 `is_favorited`),所以能直接复用 `PostCard`。
 */
export async function fetchFavorites(
  limit = 20,
  cursor: string | null = null,
): Promise<CursorPage<Post>> {
  const { data } = await http.get('/feed/favorites', {
    params: { limit, before: cursor ?? undefined },
  })
  return data as CursorPage<Post>
}

export async function fetchComments(postId: number, limit = 20, offset = 0): Promise<Page<Comment>> {
  const { data } = await http.get(`/posts/${postId}/comments`, { params: { limit, offset } })
  return data as Page<Comment>
}

export async function createComment(
  postId: number,
  text: string,
  parentId?: number,
): Promise<Comment> {
  const body = parentId === undefined ? { text } : { text, parent_id: parentId }
  const { data } = await http.post(`/posts/${postId}/comments`, body)
  return data as Comment
}

export async function fetchReplies(
  postId: number,
  commentId: number,
  limit = 100,
  offset = 0,
): Promise<Page<Comment>> {
  const { data } = await http.get(`/posts/${postId}/comments/${commentId}/replies`, {
    params: { limit, offset },
  })
  return data as Page<Comment>
}

export async function deleteComment(postId: number, commentId: number): Promise<void> {
  await http.delete(`/posts/${postId}/comments/${commentId}`)
}

export async function reportPost(postId: number, type: ReportType, detail = ''): Promise<void> {
  await http.post(`/posts/${postId}/report`, { type, detail })
}
