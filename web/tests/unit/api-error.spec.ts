import { AxiosError, AxiosHeaders } from 'axios'
import { describe, expect, it } from 'vitest'
import { parseApiError } from '@/api/error'

function axiosErrorWith(status: number, data: unknown, headers: Record<string, string> = {}) {
  const config = { headers: new AxiosHeaders() }
  return new AxiosError('failed', 'ERR_BAD_REQUEST', config as never, null, {
    status,
    statusText: '',
    data,
    headers,
    config: config as never,
  })
}

describe('parseApiError', () => {
  it('解析后端的错误信封(含 request_id)', () => {
    const e = parseApiError(
      axiosErrorWith(400, { code: 40003, message: '验证码错误', request_id: 'req-1' }),
    )
    expect(e.code).toBe(40003)
    expect(e.message).toBe('验证码错误')
    expect(e.requestId).toBe('req-1')
    expect(e.status).toBe(400)
  })

  it('不是信封形状时降级为服务器异常文案', () => {
    const e = parseApiError(axiosErrorWith(502, '<html>Bad Gateway</html>'))
    expect(e.code).toBe(502)
    expect(e.message).toBe('服务器开小差了,请稍后再试')
  })

  it('无响应(网络/超时)视为网络异常,code 为 0', () => {
    const e = parseApiError(new AxiosError('timeout', 'ECONNABORTED'))
    expect(e.code).toBe(0)
    expect(e.message).toBe('网络连接失败,请检查网络后重试')
  })

  it('401 与 40101 语义区分开', () => {
    const normal = parseApiError(axiosErrorWith(401, { code: 40100, message: '未认证' }))
    const kicked = parseApiError(axiosErrorWith(401, { code: 40101, message: '已在其他设备登录' }))
    expect(normal.isUnauthorized).toBe(true)
    expect(normal.isKickedOffline).toBe(false)
    expect(kicked.isKickedOffline).toBe(true)
    expect(kicked.isUnauthorized).toBe(false)
  })

  it('403 与 429 判定', () => {
    expect(parseApiError(axiosErrorWith(403, { code: 40302, message: '账号已被封禁' })).isBanned).toBe(
      true,
    )
    expect(
      parseApiError(axiosErrorWith(429, { code: 42901, message: '发送过于频繁' })).isThrottled,
    ).toBe(true)
  })

  it('限流时解析 Retry-After 供倒计时使用', () => {
    const withHeader = axiosErrorWith(
      429,
      { code: 42901, message: '发送过于频繁' },
      { 'retry-after': '45' },
    )
    expect(parseApiError(withHeader).retryAfter).toBe(45)
    expect(
      parseApiError(axiosErrorWith(429, { code: 42901, message: 'x' })).retryAfter,
    ).toBeUndefined()
  })

  it('已是 ApiError 时原样返回', () => {
    const original = parseApiError(axiosErrorWith(400, { code: 1, message: 'x' }))
    expect(parseApiError(original)).toBe(original)
  })

  it('普通 Error 也兜得住', () => {
    expect(parseApiError(new Error('boom')).message).toBe('boom')
    expect(parseApiError('字符串').code).toBe(0)
  })
})
