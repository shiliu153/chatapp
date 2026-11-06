import { http } from './http'
import type { Comment, CursorPage, Page, Post, ReportType } from './types'

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
