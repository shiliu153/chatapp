import { http } from './http'
import { parseApiError } from './error'
import {
  newIdempotencyKey,
  type UploadRetryOptions,
  withUploadRetries,
} from './idempotency'
import { pollVoiceStatus } from './voice-status'
import type {
  Page,
  Photo,
  Preference,
  Profile,
  ProfileVoice,
  PublicProfile,
  Tag,
  VoiceQueued,
  VoiceStatus,
} from './types'

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

/** 资料语音的上传结果:201 转码完成,或 202 受理(转码槽被占,M-3)等轮询。 */
export type ProfileVoiceUpload =
  | { queued: false; voice: ProfileVoice }
  | { queued: true; id: number; retryAfterSeconds: number }

/**
 * 构造一次资料语音的 multipart 请求体(`file` 一个字段;契约 users.md §2.11)。
 *
 * **每次尝试都要新建**:`FormData` 发出去就被浏览器标脏,重试复用同一个对象会丢文件。
 * 重新包一层 Blob 是为了把 type 钉成白名单值:part 的 Content-Type 取的就是 `Blob.type`。
 */
function profileVoiceForm(blob: Blob): FormData {
  const type = profileVoicePartType(blob.type)
  const form = new FormData()
  form.append('file', new Blob([blob], { type }), `intro.${VOICE_SUFFIX[type] ?? 'm4a'}`)
  return form
}

/**
 * 上传/覆盖语音自我介绍(multipart 字段 `file`;users.md §2.11)。
 *
 * 两条路:抢到转码槽 → `201` + 签名 `url`;抢不到 → `202` + `{id, status:"pending",
 * retry_after}`,此时**旧语音已经下线**,必须轮询 `GET /users/me/voice` 等新的转码结果。
 *
 * **幂等键**(`docs/api/conventions.md` §幂等键):一次「用户点保存」生成一个 key,本次上传的
 * 所有自动重试复用同一个;网络抖动 / `429` / `5xx` / `409` + `40901` 都退避后**同 key** 再打,
 * 不会因为响应丢了重发而多转码一次。`400`(格式 / 时长)与 `413`(配额满)立刻冒泡。
 *
 * Args:
 *   blob: 用户确认要保存的录音。
 *   options: 重试参数(单测注入点),缺省 3 次 + 500ms 起翻倍退避。
 *
 * Returns:
 *   201 → `{queued:false, voice}`;202 → `{queued:true, id, retryAfterSeconds}`。
 *
 * Raises:
 *   ApiError: 不可重试的 4xx,或重试次数用尽仍失败。
 */
export async function uploadProfileVoice(
  blob: Blob,
  options: UploadRetryOptions = {},
): Promise<ProfileVoiceUpload> {
  const idempotencyKey = newIdempotencyKey()
  return withUploadRetries(async () => {
    const response = await http.post('/users/me/voice', profileVoiceForm(blob), {
      headers: { 'Idempotency-Key': idempotencyKey },
      // 401 刷新后重放同一次上传:请求体重建,key 不变
      rebuildBody: () => profileVoiceForm(blob),
    })
    if (response.status === 202) {
      const queued = response.data as VoiceQueued
      return { queued: true as const, id: queued.id, retryAfterSeconds: queued.retry_after }
    }
    return { queued: false as const, voice: response.data as ProfileVoice }
  }, options)
}

/**
 * 查资料语音的转码状态(`GET /users/me/voice`,users.md §2.13)。
 *
 * **404 不是错误**:它表示「还没录过语音」,返回 `null` 交给页面按「未录制」渲染。
 * 其它错误(401 / 403 / 429 / 5xx)照常抛出。
 *
 * Returns:
 *   三态状态;服务端没有这条语音(404)时是 `null`。
 */
export async function fetchProfileVoiceStatus(): Promise<VoiceStatus | null> {
  try {
    const { data } = await http.get('/users/me/voice')
    return data as VoiceStatus
  } catch (error) {
    const apiError = parseApiError(error)
    if (apiError.status === 404) return null
    throw apiError
  }
}

/**
 * 轮询资料语音的转码状态,直到三态落定。
 *
 * Args:
 *   retryAfterSeconds: 202 响应里的 `retry_after`(秒),缺省由轮询器取 5 秒。
 *
 * Returns:
 *   落定状态(`ready` / `failed`);服务端 404(没有语音)时是 `null`。
 */
export function pollProfileVoiceStatus(retryAfterSeconds?: number): Promise<VoiceStatus | null> {
  return pollVoiceStatus(fetchProfileVoiceStatus, { retryAfterSeconds })
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
