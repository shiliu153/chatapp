import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as usersApi from '@/api/users'
import { parseApiError } from '@/api/error'
import type { Preference, Profile, Tag } from '@/api/types'

/** 资料语音上传的落点:`ready` = 存好了;`absent` = 服务端查不到(404),按「未录制」渲染。 */
export type VoiceUploadOutcome = 'ready' | 'absent'

/** 缺项英文键 → 中文提示(顺序与后端 missing_fields 的返回顺序无关)。 */
const MISSING_LABELS: Record<string, string> = {
  nickname: '昵称',
  gender: '性别',
  birthday: '生日',
  city: '城市',
  bio: '简介',
  photos: '照片',
}

export const useProfileStore = defineStore('profile', () => {
  const profile = ref<Profile | null>(null)
  const tags = ref<Tag[]>([])
  const loading = ref(false)
  const error = ref('')
  /**
   * 语音自我介绍正在服务端转码(M-3):上传被 202 受理、正在按 `retry_after` 轮询。
   *
   * 卡片据此把行内文案换成「正在转码…」并锁住按钮 —— 这段时间旧语音已经下线,
   * 既没有可播地址、也不该让用户重复上传。
   */
  const voiceProcessing = ref(false)

  const isBannedHeavy = computed(() => profile.value?.status === 'banned_heavy')
  const isBannedLight = computed(() => profile.value?.status === 'banned_light')
  const isIncomplete = computed(() => profile.value?.status === 'incomplete')
  const missingFieldsText = computed(() =>
    (profile.value?.missing_fields ?? []).map((f) => MISSING_LABELS[f] ?? f).join('、'),
  )

  /**
   * 加载我的资料。**不抛异常** —— 失败信息进 `error`,状态留在 `profile`(null),
   * 由调用方(守卫/页面)读状态决定渲染,避免每个调用点都要 try/catch。
   */
  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      profile.value = await usersApi.fetchMe()
    } catch (e) {
      error.value = parseApiError(e).message
    } finally {
      loading.value = false
    }
  }

  async function loadTags(): Promise<void> {
    if (tags.value.length > 0) return // 标签池是静态数据,拉一次即可
    tags.value = await usersApi.fetchTags()
  }

  async function save(patch: Record<string, unknown>): Promise<void> {
    profile.value = await usersApi.patchMe(patch)
  }

  async function uploadPhoto(file: File): Promise<void> {
    const photo = await usersApi.uploadPhoto(file)
    if (profile.value) profile.value.photos = [...profile.value.photos, photo]
  }

  async function removePhoto(photoId: number): Promise<void> {
    await usersApi.deletePhoto(photoId)
    if (profile.value) profile.value.photos = profile.value.photos.filter((p) => p.id !== photoId)
  }

  async function savePreference(patch: Partial<Preference>): Promise<void> {
    const preference = await usersApi.patchPreference(patch)
    if (profile.value) profile.value.preference = preference
  }

  /**
   * 上传/覆盖语音自我介绍。
   *
   * 两条路(users.md §2.11):
   * - `201`:转码已完成,直接替换本地 `voice`(后端是覆盖式的,旧文件由服务端删);
   * - `202`:转码槽被占,服务端已受理并**立刻让旧语音下线**,所以先把本地 `voice`
   *   置 null,再按 `retry_after` 轮询 §2.13,拿到 `ready` 才填回播放地址。
   *
   * 转码失败(`failed`)会把服务端的中文原因抛出去 —— 页面据此提示,本地草稿仍留在
   * 页面上,再点一次「保存语音」就是重试(资料语音的重试同样是重新上传 Blob)。
   *
   * Args:
   *   blob: 刚录好、用户已确认要保存的音频。
   *
   * Returns:
   *   `ready`:存好了;`absent`:轮询回 404(服务端没有这段语音),页面**不能**提示「已保存」。
   *
   * Raises:
   *   Error: 转码失败 / 轮询超时 / 网络错误,`message` 可直接展示。
   */
  async function uploadVoice(blob: Blob): Promise<VoiceUploadOutcome> {
    const uploaded = await usersApi.uploadProfileVoice(blob)
    if (!uploaded.queued) {
      if (profile.value) profile.value.voice = uploaded.voice
      return 'ready'
    }
    // 受理即下线旧语音(users.md §2.11 的覆盖语义):别让页面继续放已经删掉的文件
    if (profile.value) profile.value.voice = null
    voiceProcessing.value = true
    try {
      const status = await usersApi.pollProfileVoiceStatus(uploaded.retryAfterSeconds)
      if (!status) return 'absent' // 404 = 没有语音,不是错误
      if (status.status === 'ready' && status.url) {
        if (profile.value) {
          profile.value.voice = {
            url: status.url,
            duration_ms: status.duration_ms ?? 0,
            status: 'ready',
          }
        }
        return 'ready'
      }
      throw new Error(status.message || '语音转码失败，请重录')
    } finally {
      voiceProcessing.value = false
    }
  }

  /** 删除语音自我介绍(幂等;成功后本地置 null,页面据此隐藏播放条)。 */
  async function removeVoice(): Promise<void> {
    await usersApi.deleteProfileVoice()
    if (profile.value) profile.value.voice = null
  }

  return {
    profile,
    tags,
    loading,
    error,
    voiceProcessing,
    isBannedHeavy,
    isBannedLight,
    isIncomplete,
    missingFieldsText,
    load,
    loadTags,
    save,
    uploadPhoto,
    removePhoto,
    savePreference,
    uploadVoice,
    removeVoice,
  }
})
