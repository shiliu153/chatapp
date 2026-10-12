import axios from 'axios'

/** 后端统一错误信封解析结果(形状见 CLAUDE.md「错误契约」)。 */
export class ApiError extends Error {
  constructor(
    readonly code: number,
    message: string,
    readonly requestId?: string,
    readonly status?: number,
    /** 限流时后端给的 Retry-After(秒);登录页倒计时用它,不硬编码 60 */
    readonly retryAfter?: number,
  ) {
    super(message)
    this.name = 'ApiError'
  }

  /** 普通未认证:走刷新通道 */
  get isUnauthorized(): boolean {
    return this.status === 401 && this.code !== 40101
  }

  /** 被顶号(单设备登录):清凭证 + 全屏提示,不刷新 */
  get isKickedOffline(): boolean {
    return this.code === 40101
  }

  /** 封禁(banned_light / banned_heavy 均由后端 403 表达) */
  get isBanned(): boolean {
    return this.status === 403
  }

  get isThrottled(): boolean {
    return this.status === 429
  }
}

type Envelope = { code?: unknown; message?: unknown; request_id?: unknown }

function asEnvelope(data: unknown): Envelope | null {
  return data && typeof data === 'object' ? (data as Envelope) : null
}

export function parseApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error

  if (axios.isAxiosError(error)) {
    const response = error.response
    if (!response) return new ApiError(0, '网络连接失败,请检查网络后重试')

    const envelope = asEnvelope(response.data)
    const code = typeof envelope?.code === 'number' ? envelope.code : response.status
    const message =
      typeof envelope?.message === 'string' && envelope.message
        ? envelope.message
        : '服务器开小差了,请稍后再试'
    const requestId = typeof envelope?.request_id === 'string' ? envelope.request_id : undefined
    const retryAfterRaw = response.headers?.['retry-after']
    const retryAfter = Number(retryAfterRaw)
    return new ApiError(
      code,
      message,
      requestId,
      response.status,
      Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : undefined,
    )
  }

  if (error instanceof Error) return new ApiError(0, error.message)
  return new ApiError(0, '未知错误')
}
