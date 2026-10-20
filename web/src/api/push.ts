import { http } from './http'

export interface PushPreferences {
  likes: boolean
  matches: boolean
  system: boolean
}

/** 读取账号级通知偏好(默认全开)。 */
export async function getPushPreferences(): Promise<PushPreferences> {
  const { data } = await http.get<PushPreferences>('/push/preferences')
  return data
}

/** 局部更新通知偏好,返回更新后的完整对象。 */
export async function updatePushPreferences(
  patch: Partial<PushPreferences>,
): Promise<PushPreferences> {
  const { data } = await http.patch<PushPreferences>('/push/preferences', patch)
  return data
}
