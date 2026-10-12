import axios, { type AxiosError, type InternalAxiosRequestConfig } from 'axios'
import { ApiError, parseApiError } from './error'
import { sessionEvents } from './session-events'
import { tokenStore } from './token-store'

const baseURL = import.meta.env.VITE_API_BASE ?? '/api/v1'

export const http = axios.create({ baseURL, timeout: 15_000 })

/** 裸实例:刷新令牌本身不能走拦截器,否则 401 会递归 */
const bare = axios.create({ baseURL, timeout: 15_000 })

http.interceptors.request.use((config) => {
  const access = tokenStore.access
  if (access) config.headers.Authorization = `Bearer ${access}`
  return config
})

type RetriableConfig = InternalAxiosRequestConfig & { _retried?: boolean }

let refreshing: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  const refresh = tokenStore.refresh
  if (!refresh) throw new ApiError(401, '登录状态已失效,请重新登录')
  const { data } = await bare.post('/auth/token/refresh', { refresh })
  tokenStore.access = data.access
  tokenStore.refresh = data.refresh
  return data.access as string
}

http.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
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
