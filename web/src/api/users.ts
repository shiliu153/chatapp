import { http } from './http'
import type { Page, Photo, Preference, Profile, ProfileVoice, PublicProfile, Tag } from './types'

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

/**
 * 资料语音的 MIME 白名单,与后端 `users.serializers.ALLOWED_AUDIO_CONTENT_TYPES` 一致。
 *
 * 为什么前端要管这个:multipart part 的 `Content-Type` 就是 Blob 的 `type`;留空
 * (或浏览器给出别的容器)时 Django 收到的是 `application/octet-stream`,后端白名单
 * 不含它 → **必定 400「只支持 M4A/AAC/WebM/OGG 音频」**。App 侧同一个坑(2026-11-09
 * 真机实测)记在 `bfff120` 的提交说明里。
 */
export const PROFILE_VOICE_MIME_TYPES = [
  'audio/webm',
  'audio/mp4',
  'audio/m4a',
  'audio/x-m4a',
  'audio/aac',
  'audio/ogg',
] as const

/** 主类型 → 上传文件名后缀(文件名只影响可读性;服务端按 Content-Type 选容器)。 */
const VOICE_SUFFIX: Record<string, string> = {
  'audio/webm': 'webm',
  'audio/ogg': 'ogg',
  'audio/mp4': 'm4a',
  'audio/m4a': 'm4a',
  'audio/x-m4a': 'm4a',
  'audio/aac': 'aac',
}

/**
 * 把录音 Blob 的 type 归一成白名单里的主类型(去掉 `;codecs=opus` 这类参数)。
 *
 * 认不出来时兜底 `audio/webm` —— 宁可让服务端按 webm 试解码(ffmpeg 自己会嗅探真实容器),
 * 也不要送 `application/octet-stream` 吃一个必然的 400。
 */
export function profileVoicePartType(blobType: string): string {
  const main = (blobType || '').split(';')[0].trim().toLowerCase()
  return (PROFILE_VOICE_MIME_TYPES as readonly string[]).includes(main) ? main : 'audio/webm'
}

/** 上传/覆盖语音自我介绍(multipart 字段 `file`;users.md §2.6)。返回公开绝对地址与实测时长。 */
export async function uploadProfileVoice(blob: Blob): Promise<ProfileVoice> {
  const type = profileVoicePartType(blob.type)
  const form = new FormData()
  // 重新包一层 Blob 是为了把 type 钉成白名单值:part 的 Content-Type 取的就是 Blob.type
  form.append('file', new Blob([blob], { type }), `intro.${VOICE_SUFFIX[type] ?? 'm4a'}`)
  const { data } = await http.post('/users/me/voice', form)
  return data as ProfileVoice
}

/** 删除语音自我介绍(幂等 204;没录过也成功)。 */
export async function deleteProfileVoice(): Promise<void> {
  await http.delete('/users/me/voice')
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

/** 关注某人(幂等 204;重复关注不报错,feed.md §5.13)。 */
export async function followUser(userId: number): Promise<void> {
  await http.post(`/users/${userId}/follow`)
}

/** 取消关注(幂等 204;没关注过也成功,feed.md §5.14)。 */
export async function unfollowUser(userId: number): Promise<void> {
  await http.delete(`/users/${userId}/follow`)
}

/** 注销账号(不可恢复)。后端要求带上当前账号的完整手机号做二次确认。 */
export async function deleteAccount(phone: string): Promise<void> {
  await http.delete('/users/me', { data: { phone } })
}

export type { Page }
