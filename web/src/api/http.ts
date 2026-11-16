import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { rememberRequestId } from './clientErrors'
import { parseApiError } from './error'
import { sessionEvents } from './session-events'
import { tokenStore } from './token-store'

const baseURL = import.meta.env.VITE_API_BASE ?? '/api/v1'

/**
 * Web 客户端标识:后端据此把 refresh 放进 HttpOnly Cookie,而不是响应体。
 * 自定义头跨域会触发预检,生产 CORS 白名单为空,第三方站点发不出来。
 */
const WEB_CLIENT_HEADERS = { 'X-Client': 'web' }

export const http = axios.create({ baseURL, timeout: 15_000, withCredentials: true })

/** 裸实例:刷新令牌本身不能走拦截器,否则 401 会递归 */
const bare = axios.create({ baseURL, timeout: 15_000, withCredentials: true })

http.interceptors.request.use((config) => {
  config.headers['X-Client'] = 'web'
  const access = tokenStore.access
  if (access) config.headers.Authorization = `Bearer ${access}`
  return config
})

declare module 'axios' {
  interface AxiosRequestConfig {
    /**
     * 上传请求的重放钩子:401 刷新后用新令牌重发**同一次上传**时,用它重新构造 multipart 请求体。
     *
     * 为什么需要:已经发出去的 `FormData` 会被浏览器标脏,直接重发同一个对象会丢文件 / 丢字段。
     * 只有上传类请求会传它(见 `src/api/idempotency.ts`),普通 JSON 请求不带。
     */
    rebuildBody?: () => FormData
  }
}

type RetriableConfig = InternalAxiosRequestConfig & { _retried?: boolean }

let refreshing: Promise<string> | null = null

/**
 * 用 Cookie 里的 refresh 换一个新的 access。
 * 请求体为空:refresh 由浏览器自动携带,JS 读不到也不该读。
 */
async function refreshAccessToken(): Promise<string> {
  const { data } = await bare.post('/auth/token/refresh', {}, { headers: WEB_CLIENT_HEADERS })
  tokenStore.access = data.access
  return data.access as string
}

http.interceptors.response.use(
  (response) => {
    // 记下服务端追踪 ID:前端错误上报会带上它,前后端日志才能按同一个 id 对上
    rememberRequestId(response.headers?.['x-request-id'] as string | undefined)
    return response
  },
  async (error: AxiosError) => {
    rememberRequestId(error.response?.headers?.['x-request-id'] as string | undefined)
    const apiError = parseApiError(error)

    if (apiError.isKickedOffline) {
      tokenStore.clear()
      sessionEvents.emitKickedOffline()
      return Promise.reject(apiError)
    }

    const config = error.config as RetriableConfig | undefined
    if (apiError.isUnauthorized && config && !config._retried) {
      config._retried = true
      // 并发去重:同一时刻只发一次刷新请求
      refreshing ??= refreshAccessToken().finally(() => {
        refreshing = null
      })
      try {
        const access = await refreshing
        config.headers.Authorization = `Bearer ${access}`
        // 同一次上传的重放:multipart 请求体必须重建(已发送的 FormData 会被浏览器标脏)
        if (config.rebuildBody) config.data = config.rebuildBody()
        return await http.request(config)
      } catch (refreshError) {
        tokenStore.clear()
        sessionEvents.emitSessionExpired()
        return Promise.reject(parseApiError(refreshError))
      }
    }

    return Promise.reject(apiError)
  },
)
