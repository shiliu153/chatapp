/** 与后端接口一一对应的出入参类型;字段以 docs/api/ 为准,不臆造。 */

export interface LoginResult {
  access: string
  refresh: string
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
