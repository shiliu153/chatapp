import { http } from './http'
import type { LoginResult } from './types'

/** 发送短信验证码;同号 60 秒内重发会被后端拒绝(42901,响应带 Retry-After)。 */
export async function sendCode(phone: string): Promise<void> {
  await http.post('/auth/sms/send', { phone })
}

/** 校验验证码并登录(未注册自动建号)。 */
export async function verify(phone: string, code: string): Promise<LoginResult> {
  const { data } = await http.post('/auth/sms/verify', { phone, code })
  return {
    access: data.access,
    refresh: data.refresh,
    isNewUser: Boolean(data.is_new_user),
    userId: Number(data.user_id),
  }
}
