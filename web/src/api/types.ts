/** 与后端接口一一对应的出入参类型;字段以 docs/api/ 为准,不臆造。 */

export interface LoginResult {
  access: string
  isNewUser: boolean
  userId: number
}

export type Gender = 'male' | 'female'
export type ProfileStatus = 'incomplete' | 'complete' | 'banned_light' | 'banned_heavy'
export type PhotoStatus = 'pending' | 'approved' | 'rejected'

export interface Tag {
  id: number
  name: string
  icon: string
}

export interface Photo {
  id: number
  url: string
  status: PhotoStatus
  order: number
}

export interface Preference {
  /** null = 不限 */
  target_gender: Gender | null
  age_min: number
  age_max: number
  /** 空字符串 = 不限 */
  city: string
}

export interface Profile {
  /** 资料表主键(不是账号 ID,跨接口引用用户一律用 user_id) */
  id: number
  user_id: number
  phone: string
  nickname: string
  gender: Gender | ''
  /** YYYY-MM-DD */
  birthday: string | null
  age: number | null
  city: string
  bio: string
  status: ProfileStatus
  ban_reason: string
  /** nickname / gender / birthday / city / bio / photos */
  missing_fields: string[]
  tags: Tag[]
  photos: Photo[]
  preference: Preference
}

export interface PublicProfile {
  user_id: number
  nickname: string
  gender: Gender | ''
  age: number | null
  city: string
  bio: string
  tags: Tag[]
  photos: Photo[]
}

/** 所有列表接口统一的分页信封(conventions.md) */
export interface Page<T> {
  count: number
  next: string | null
  previous: string | null
  results: T[]
}

export interface Candidate {
  user_id: number
  nickname: string
  gender: Gender | ''
  age: number | null
  city: string
  bio: string
  tags: Tag[]
  /** 只含已过审(discovery.md §3.1) */
  photos: Photo[]
}

export interface MatchSummary {
  user_id: number
  /** 形如 u9,聊天时用它 */
  im_user_id: string
  nickname: string
  avatar_url: string | null
  /** ISO 8601 */
  matched_at: string
}

/** 「喜欢我的人」列表项:公开资料 + 喜欢时间(discovery.md §3.4)。 */
export interface LikeReceived extends Candidate {
  /** ISO 8601 */
  liked_at: string
}

export interface PostAuthor {
  user_id: number
  nickname: string
  avatar_url: string | null
}

export interface Post {
  id: number
  author: PostAuthor
  text: string
  /** 完整 URL,最多 9 张 */
  images: string[]
  like_count: number
  comment_count: number
  liked_by_me: boolean
  /** ISO 8601 */
  created_at: string
}

export interface ReplyTo {
  user_id: number
  nickname: string
}

export interface Comment {
  id: number
  author: PostAuthor
  text: string
  /** 顶级评论为 null;回复为所属顶级评论 ID */
  parent_id: number | null
  /** 被回复者;顶级评论为 null */
  reply_to: ReplyTo | null
  /** 该楼层的可见回复总数(回复对象恒为 0) */
  reply_count: number
  /** 内嵌的前 2 条回复(回复对象恒为空) */
  replies: Comment[]
  created_at: string
}

export type ReportType = 'harassment' | 'porn' | 'fraud' | 'other'
