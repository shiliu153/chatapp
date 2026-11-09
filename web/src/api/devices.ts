import { http } from './http'
import type { LoginDevice } from './types'

/**
 * 登录设备列表(auth.md §1.6)。
 *
 * `X-Client: web` 由 `http.ts` 的请求拦截器统一带,页面/store 都不手写这个头 ——
 * 后端据此把 `current` 落在网页端那行。
 */
export async function fetchDevices(): Promise<LoginDevice[]> {
  const { data } = await http.get('/devices')
  return (data as { results: LoginDevice[] }).results
}

/**
 * 把某一端下线(auth.md §1.7):该端令牌立即失效,另一端不受影响。
 *
 * **幂等**:该端没有会话行、或重复调用,后端都返回 204。
 */
export async function logoutDevice(clientType: string): Promise<void> {
  await http.delete(`/devices/${encodeURIComponent(clientType)}`)
}
