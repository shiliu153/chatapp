import { http } from './http'
import type { Page, Photo, Preference, Profile, PublicProfile, Tag } from './types'

export async function fetchMe(): Promise<Profile> {
  const { data } = await http.get('/users/me')
  return data as Profile
}

/** 只需传要改的字段;tag_ids 是全量替换。 */
export async function patchMe(patch: Record<string, unknown>): Promise<Profile> {
  const { data } = await http.patch('/users/me', patch)
  return data as Profile
}

export async function fetchTags(): Promise<Tag[]> {
  const { data } = await http.get('/users/tags')
  return data as Tag[]
}

export async function uploadPhoto(file: File): Promise<Photo> {
  const form = new FormData()
  form.append('file', file) // 字段名固定为 file(users.md §2.4)
  const { data } = await http.post('/users/me/photos', form)
  return data as Photo
}

export async function deletePhoto(photoId: number): Promise<void> {
  await http.delete(`/users/me/photos/${photoId}`)
}

export async function fetchPreference(): Promise<Preference> {
  const { data } = await http.get('/users/me/preference')
  return data as Preference
}

export async function patchPreference(patch: Partial<Preference>): Promise<Preference> {
  const { data } = await http.patch('/users/me/preference', patch)
  return data as Preference
}

export async function fetchUserProfile(userId: number): Promise<PublicProfile> {
  const { data } = await http.get(`/users/${userId}`)
  return data as PublicProfile
}

/** 注销账号(不可恢复)。后端要求带上当前账号的完整手机号做二次确认。 */
export async function deleteAccount(phone: string): Promise<void> {
  await http.delete('/users/me', { data: { phone } })
}

export type { Page }
