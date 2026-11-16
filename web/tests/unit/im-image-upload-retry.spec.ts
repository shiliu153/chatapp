/**
 * 图片上传的错误分类与退避(#410,口径对齐 PR #406 的 `voice-status.ts`)。
 *
 * 三条判据,与语音轮询同一套:
 * 1. **401 / 403 / 404 立刻冒泡** —— 令牌失效、被封禁、资源不在了,再问也一样;
 * 2. **429 退避不判死** —— 按服务端 `Retry-After` 等,等完再试;
 * 3. **网络抖动 / 5xx 退避** —— 断网与「服务端正在重启」都是一次性的,自己重试比让
 *    用户去点「重发」好;但次数有上限,试够了要老实把错误抛给 UI。
 *
 * 顺带钉住:4xx 里的校验类错误(400 像素超限 / 413 配额满)不重试,重复上传只会再错一次。
 * 第四条判据 `409` + `40901`(同 key 的上一次还在跑,可重试)与幂等键那一整套见
 * `upload-idempotency.spec.ts`(工单 #417):分类函数已挪到 `src/api/idempotency.ts`,
 * 三个上传入口共用一份。
 */
import { HttpResponse, http as mswHttp } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { uploadRetryDelay } from '@/api/idempotency'
import {
  CHAT_IMAGE_UPLOAD_ATTEMPTS,
  CHAT_IMAGE_UPLOAD_BASE_DELAY_MS,
  uploadChatImage,
} from '@/im/self/image'
import { server } from '../support/server'

const uploaded = {
  id: 12,
  url: 'https://cdn/media/chat/images/12.jpg?e=1&s=x',
  thumb_url: 'https://cdn/media/chat/images/12_thumb.jpg?e=1&s=x',
  width: 800,
  height: 600,
  size: 12345,
}

/** jsdom 里没有 canvas:`compressImage` 会原样返回 File,正好只测上传那一段。 */
const file = (): File => new File([new Uint8Array([1, 2, 3])], 'a.jpg', { type: 'image/jpeg' })

describe('uploadChatImage:抖动与限流退避重试', () => {
  it('5xx 一次后成功:重试一次就成功,退避用的是基础间隔', async () => {
    let calls = 0
    server.use(
      mswHttp.post('/api/v1/im/images', () => {
        calls += 1
        return calls === 1
          ? HttpResponse.json({ code: 500, message: '服务器开小差了' }, { status: 500 })
          : HttpResponse.json(uploaded, { status: 201 })
      }),
    )
    const sleep = vi.fn(async () => {})

    await expect(uploadChatImage(file(), { sleep })).resolves.toEqual(uploaded)

    expect(calls).toBe(2)
    expect(sleep).toHaveBeenCalledTimes(1)
    expect(sleep).toHaveBeenCalledWith(CHAT_IMAGE_UPLOAD_BASE_DELAY_MS)
  })

  it('429 带 Retry-After:按服务端给的时间退避,不判死', async () => {
    let calls = 0
    server.use(
      mswHttp.post('/api/v1/im/images', () => {
        calls += 1
        if (calls > 1) return HttpResponse.json(uploaded, { status: 201 })
        return HttpResponse.json(
          { code: 42901, message: '操作太频繁' },
          { status: 429, headers: { 'Retry-After': '2' } },
        )
      }),
    )
    const sleep = vi.fn(async () => {})

    await expect(uploadChatImage(file(), { sleep })).resolves.toEqual(uploaded)

    expect(calls).toBe(2)
    // Retry-After 是秒,内部换算成毫秒
    expect(sleep).toHaveBeenCalledWith(2000)
  })

  it('断网(请求没到服务端)也退避重试', async () => {
    let calls = 0
    server.use(
      mswHttp.post('/api/v1/im/images', () => {
        calls += 1
        return calls === 1 ? HttpResponse.error() : HttpResponse.json(uploaded, { status: 201 })
      }),
    )
    const sleep = vi.fn(async () => {})

    await expect(uploadChatImage(file(), { sleep })).resolves.toEqual(uploaded)

    expect(calls).toBe(2)
    expect(sleep).toHaveBeenCalledTimes(1)
  })

  it('一直 5xx:试满次数后把错误抛给 UI(退避不无限循环)', async () => {
    let calls = 0
    server.use(
      mswHttp.post('/api/v1/im/images', () => {
        calls += 1
        return HttpResponse.json({ code: 500, message: '服务器开小差了' }, { status: 500 })
      }),
    )
    const sleep = vi.fn(async () => {})

    await expect(uploadChatImage(file(), { sleep })).rejects.toThrow('服务器开小差了')

    expect(calls).toBe(CHAT_IMAGE_UPLOAD_ATTEMPTS)
    expect(sleep).toHaveBeenCalledTimes(CHAT_IMAGE_UPLOAD_ATTEMPTS - 1)
  })
})

describe('uploadChatImage:「再问也一样」的错误立刻冒泡', () => {
  it.each([
    [403, '当前账号已被限制使用'],
    [404, '资源不存在'],
    [400, '图片分辨率超限'],
    [413, '存储空间已满,请先删除部分照片'],
  ])('%i 只请求一次就上抛', async (status, message) => {
    let calls = 0
    server.use(
      mswHttp.post('/api/v1/im/images', () => {
        calls += 1
        return HttpResponse.json({ code: status, message }, { status })
      }),
    )
    const sleep = vi.fn(async () => {})

    await expect(uploadChatImage(file(), { sleep })).rejects.toThrow(message)

    expect(calls).toBe(1)
    expect(sleep).not.toHaveBeenCalled()
  })

  it('401 立刻冒泡,上传不重试(刷新通道由 http 层负责,不是上传自己重试)', async () => {
    let calls = 0
    server.use(
      mswHttp.post('/api/v1/im/images', () => {
        calls += 1
        return HttpResponse.json({ code: 40100, message: '未认证' }, { status: 401 })
      }),
      // 刷新也失败:这时上传必须把错误交出去,而不是自己再转一圈
      mswHttp.post('/api/v1/auth/token/refresh', () =>
        HttpResponse.json({ code: 40102, message: '登录已过期,请重新登录' }, { status: 401 }),
      ),
    )
    const sleep = vi.fn(async () => {})

    await expect(uploadChatImage(file(), { sleep })).rejects.toThrow('登录已过期')

    expect(calls).toBe(1)
    expect(sleep).not.toHaveBeenCalled()
  })
})

describe('uploadRetryDelay:分类判据本身(三个上传入口共用)', () => {
  it('没有 HTTP 状态码的本地错误(压缩失败)不重试', () => {
    expect(uploadRetryDelay(new Error('canvas 炸了'), 500)).toBeNull()
  })

  it('429 没给 Retry-After 时用退避值', () => {
    const error = Object.assign(new Error('操作太频繁'), {
      isAxiosError: true,
      response: { status: 429, headers: {}, data: { code: 42901, message: '操作太频繁' } },
    })
    expect(uploadRetryDelay(error, 800)).toBe(800)
  })

  it('401 / 403 / 404 一律返回 null(立刻冒泡)', () => {
    for (const status of [401, 403, 404]) {
      const error = Object.assign(new Error('nope'), {
        isAxiosError: true,
        response: { status, headers: {}, data: { code: status, message: 'nope' } },
      })
      expect(uploadRetryDelay(error, 500)).toBeNull()
    }
  })
})
