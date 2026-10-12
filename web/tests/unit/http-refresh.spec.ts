import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { http } from '@/api/http'
import { sessionEvents } from '@/api/session-events'
import { tokenStore } from '@/api/token-store'
import { server } from '../support/server'

const unauthorized = () =>
  HttpResponse.json({ code: 40100, message: '未认证', request_id: 'r' }, { status: 401 })

/** 只在带新令牌时才放行的受保护接口 */
function guardedMe() {
  return mswHttp.get('/api/v1/users/me', ({ request }) =>
    request.headers.get('Authorization') === 'Bearer new-access'
      ? HttpResponse.json({ id: 1, nickname: '小雨' })
      : unauthorized(),
  )
}

describe('401 刷新通道', () => {
  beforeEach(() => {
    // 每个用例的监听器互相隔离
    sessionEvents._reset()
    tokenStore.access = 'expired'
    tokenStore.refresh = 'refresh-1'
  })

  it('刷新成功后重放原请求,并轮换两个令牌', async () => {
    let refreshCalls = 0
    server.use(
      guardedMe(),
      mswHttp.post('/api/v1/auth/token/refresh', () => {
        refreshCalls += 1
        return HttpResponse.json({ access: 'new-access', refresh: 'refresh-2' })
      }),
    )

    const res = await http.get('/users/me')

    expect(res.data).toEqual({ id: 1, nickname: '小雨' })
    expect(refreshCalls).toBe(1)
    expect(tokenStore.access).toBe('new-access')
    expect(tokenStore.refresh).toBe('refresh-2')
  })

  it('并发两个 401 只刷新一次', async () => {
    let refreshCalls = 0
    server.use(
      guardedMe(),
      mswHttp.post('/api/v1/auth/token/refresh', async () => {
        refreshCalls += 1
        await new Promise((r) => setTimeout(r, 20)) // 制造并发窗口
        return HttpResponse.json({ access: 'new-access', refresh: 'refresh-2' })
      }),
    )

    const [a, b] = await Promise.all([http.get('/users/me'), http.get('/users/me')])

    expect(a.status).toBe(200)
    expect(b.status).toBe(200)
    expect(refreshCalls).toBe(1)
  })

  it('刷新失败时清空凭证并通知会话过期', async () => {
    const expired = vi.fn()
    sessionEvents.onSessionExpired(expired)
    server.use(
      mswHttp.get('/api/v1/users/me', unauthorized),
      mswHttp.post('/api/v1/auth/token/refresh', unauthorized),
    )

    await expect(http.get('/users/me')).rejects.toMatchObject({ code: 40100 })

    expect(expired).toHaveBeenCalledTimes(1)
    expect(tokenStore.access).toBeNull()
    expect(tokenStore.refresh).toBeNull()
  })

  it('40101 被顶号:不刷新,直接通知被顶下线', async () => {
    const kicked = vi.fn()
    sessionEvents.onKickedOffline(kicked)
    let refreshCalls = 0
    server.use(
      mswHttp.get('/api/v1/users/me', () =>
        HttpResponse.json(
          { code: 40101, message: '账号已在其他设备登录', request_id: 'r' },
          { status: 401 },
        ),
      ),
      mswHttp.post('/api/v1/auth/token/refresh', () => {
        refreshCalls += 1
        return HttpResponse.json({ access: 'x', refresh: 'y' })
      }),
    )

    await expect(http.get('/users/me')).rejects.toMatchObject({ code: 40101 })

    expect(refreshCalls).toBe(0)
    expect(kicked).toHaveBeenCalledTimes(1)
    expect(tokenStore.access).toBeNull()
  })

  it('请求带上 Bearer 令牌', async () => {
    let seen: string | null = null
    server.use(
      mswHttp.get('/api/v1/users/me', ({ request }) => {
        seen = request.headers.get('Authorization')
        return HttpResponse.json({ id: 1 })
      }),
    )

    await http.get('/users/me')

    expect(seen).toBe('Bearer expired')
  })

  it('非 401 错误原样抛出为 ApiError', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () =>
        HttpResponse.json({ code: 50002, message: '服务器开小差了', request_id: 'r' }, { status: 500 }),
      ),
    )

    await expect(http.get('/users/me')).rejects.toMatchObject({ code: 50002 })
  })
})
