import { http } from './http'
import type { LoginResult } from './types'

/** 发送短信验证码;同号 60 秒内重发会被后端拒绝(42901,响应带 Retry-After)。 */
export async function sendCode(phone: string): Promise<void> {
  await http.post('/auth/sms/send', { phone })
}

/**
 * 校验验证码并登录(未注册自动建号)。
 * 浏览器不带 `refresh`:它在 HttpOnly Cookie 里,JS 读不到。
 */
export async function verify(phone: string, code: string): Promise<LoginResult> {
  const { data } = await http.post('/auth/sms/verify', { phone, code })
  return {
    access: data.access,
    isNewUser: Boolean(data.is_new_user),
    userId: Number(data.user_id),
  }
}

/** 注销:拉黑 refresh 并清除 Cookie。幂等,重复调用也返回 204。 */
export async function logout(): Promise<void> {
  await http.post('/auth/logout', {})
}
