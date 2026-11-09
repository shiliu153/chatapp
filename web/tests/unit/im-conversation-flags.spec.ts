import { HttpResponse, http as mswHttp } from 'msw'
import { describe, expect, it } from 'vitest'
import { ApiError } from '@/api/error'
import { SelfImClient } from '@/im/self/client'
import type { ImBootstrap } from '@/im/types'
import { server } from '../support/server'

/**
 * 会话偏好写入(批次 N):`POST /im/api/conversations/flags`。
 *
 * 三条最容易写错的地方,这里逐个钉住:
 * 1) **缺省字段不上行** —— 服务端语义是「没传 = 不改」,把 `muted: false` 顺手带上
 *    会把免打扰一起取消掉;
 * 2) 失败要抛**统一** `ApiError`(带 imserver 的业务码),否则调用方没法把
 *    `40401`(会话不存在)与 `42901`(限流)分开处理;
 * 3) 成功要按服务端**回读的真值**返回,不能回显请求参数。
 */

const bootstrap: ImBootstrap = {
  token: 'tok-flags',
  wsUrl: 'ws://test/im/ws',
  // 用 127.0.0.1 而不是 `http://test/...`:MSW 的 cookie jar 会在 `test` 这个
  // 特殊用途顶级域上抛「public suffix」异常,handler 根本不会被调用。
  httpUrl: 'http://127.0.0.1:9101/im/api',
  imUserId: 'u41',
}

const FLAGS_URL = 'http://127.0.0.1:9101/im/api/conversations/flags'

async function client(): Promise<SelfImClient> {
  const instance = new SelfImClient()
  await instance.init(bootstrap)
  return instance
}

describe('SelfImClient.setConversationFlags', () => {
  it('只上行要改的那一项,并按服务端回读值返回', async () => {
    let body: Record<string, unknown> | null = null
    let authorization = ''
    let method = ''
    server.use(
      mswHttp.post(FLAGS_URL, async ({ request }) => {
        method = request.method
        authorization = request.headers.get('authorization') ?? ''
        body = (await request.json()) as Record<string, unknown>
        // 服务端回的是实库真值:本次只改了置顶,免打扰保持原值 true
        return HttpResponse.json({ pinned: true, muted: true })
      }),
    )

    const result = await (await client()).setConversationFlags('u9', { pinned: true })

    expect(method).toBe('POST')
    expect(authorization).toBe('Bearer tok-flags')
    // ⚠️ 只有 peer + pinned:muted 缺省不能出现在 body 里
    expect(body).toEqual({ peer: 'u9', pinned: true })
    expect(result).toEqual({ pinned: true, muted: true })
  })

  it('两个开关一起改时都上行', async () => {
    let body: Record<string, unknown> | null = null
    server.use(
      mswHttp.post(FLAGS_URL, async ({ request }) => {
        body = (await request.json()) as Record<string, unknown>
        return HttpResponse.json({ pinned: false, muted: false })
      }),
    )

    await (await client()).setConversationFlags('u9', { pinned: false, muted: false })

    expect(body).toEqual({ peer: 'u9', pinned: false, muted: false })
  })

  it('会话不存在(404 + 40401)抛带业务码的 ApiError', async () => {
    server.use(
      mswHttp.post(FLAGS_URL, () =>
        HttpResponse.json({ code: 40401, message: '会话不存在' }, { status: 404 }),
      ),
    )

    const error = await (await client()).setConversationFlags('u9', { pinned: true }).catch(
      (e: unknown) => e,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).code).toBe(40401)
    expect((error as ApiError).status).toBe(404)
    expect((error as ApiError).message).toBe('会话不存在')
  })

  it('限流(429 + 42901)抛 isThrottled 的 ApiError', async () => {
    server.use(
      mswHttp.post(FLAGS_URL, () =>
        HttpResponse.json({ code: 42901, message: '操作过于频繁,请稍后再试' }, { status: 429 }),
      ),
    )

    const error = await (await client()).setConversationFlags('u9', { muted: true }).catch(
      (e: unknown) => e,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).isThrottled).toBe(true)
    expect((error as ApiError).code).toBe(42901)
  })

  it('非 JSON 错误体(网关 502)也要有可读文案,不抛原始 JSON 解析错', async () => {
    server.use(
      mswHttp.post(FLAGS_URL, () => new HttpResponse('<html>bad gateway</html>', { status: 502 })),
    )

    const error = await (await client()).setConversationFlags('u9', { pinned: true }).catch(
      (e: unknown) => e,
    )

    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(502)
    expect((error as ApiError).message).toBe('IM HTTP 502')
  })
})
