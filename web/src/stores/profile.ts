import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import * as usersApi from '@/api/users'
import { parseApiError } from '@/api/error'
import type { Preference, Profile, Tag } from '@/api/types'

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

  return {
    profile,
    tags,
    loading,
    error,
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
  }
})
