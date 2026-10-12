import { http } from './http'
import type { Comment, Page, Post, ReportType } from './types'

export async function fetchPosts(limit = 20, offset = 0): Promise<Page<Post>> {
  const { data } = await http.get('/posts', { params: { limit, offset } })
  return data as Page<Post>
}

export async function fetchMyPosts(limit = 20, offset = 0): Promise<Page<Post>> {
  const { data } = await http.get('/posts/mine', { params: { limit, offset } })
  return data as Page<Post>
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

export async function createComment(postId: number, text: string): Promise<Comment> {
  const { data } = await http.post(`/posts/${postId}/comments`, { text })
  return data as Comment
}

export async function reportPost(postId: number, type: ReportType, detail = ''): Promise<void> {
  await http.post(`/posts/${postId}/report`, { type, detail })
}
