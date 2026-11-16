/**
 * 上传类接口的幂等键(工单 #417,契约 `docs/api/conventions.md` §幂等键)。
 *
 * 要钉住的是四条**行为契约**,不是「有没有发请求」:
 *
 * 1. **一次上传的所有重试复用同一个 key** —— 服务端据此才认得出「这是同一次上传的重试」,
 *    否则重试会多落一份文件 / 多建一条语音(白吃存储配额,而且没人会注意到);
 * 2. **换一张图 / 重新录一段 = 换新 key** —— 不该把两次不同的上传认成同一次;
 * 3. **`409` + `40901` 是可重试**(同 key 的上一次还在跑):退避 1–2 秒后用同一个 key 再打,
 *    拿回首次的结果;当终态失败报给用户等于让一次其实成功的上传失败;
 * 4. **`400` / `413` 立刻冒泡**、不重试(请求本身不对,服务端已释放 key)。
 *
 * 另外钉住 `FormData` 那条坑:已发送的 `FormData` 会被浏览器标脏,重试**必须重新构造**,
 * 所以断言「第二次请求里文件还在、且两次不是同一个对象」。
 *
 * 三个入口(聊天图片 / 聊天语音 / 资料语音)都要覆盖:它们共用 `src/api/idempotency.ts`
 * 的口径,但各自都可能在改造时漏掉其中一个。
 */
import { HttpResponse, http as mswHttp } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import {
  IDEMPOTENCY_KEY_PATTERN,
  newIdempotencyKey,
  UPLOAD_ATTEMPTS,
  UPLOAD_IN_FLIGHT_DELAY_MS,
  uploadRetryDelay,
  withUploadRetries,
} from '@/api/idempotency'
import { tokenStore } from '@/api/token-store'
import { uploadProfileVoice } from '@/api/users'
import { uploadChatImage } from '@/im/self/image'
import { uploadChatVoice } from '@/im/self/voice'
import { server } from '../support/server'

const uploadedImage = {
  id: 12,
  url: 'https://cdn/media/chat/images/12.jpg?e=1&s=x',
  thumb_url: 'https://cdn/media/chat/images/12_thumb.jpg?e=1&s=x',
  width: 800,
  height: 600,
  size: 12345,
}

const uploadedVoice = {
  id: 46,
  url: 'https://cdn/media/chat/voices/46.m4a?e=1&s=x',
  duration_ms: 3200,
  size: 12345,
  status: 'ready',
}

const profileVoice = {
  url: 'https://cdn/media/voices/7.m4a?e=1&s=x',
  duration_ms: 4200,
  status: 'ready',
}

/** 三条上传入口共用的失败响应(均为本单要区分的两类)。 */
const inFlight = () =>
  HttpResponse.json({ code: 40901, message: '同一次上传正在处理中,请稍后重试' }, { status: 409 })

/** 一次「用户刚选的图」;jsdom 里没有 canvas,`compressImage` 会原样返回 File。 */
const imageFile = (): File => new File([new Uint8Array([1, 2, 3])], 'a.jpg', { type: 'image/jpeg' })

describe('newIdempotencyKey:生成的值必须能被后端接受', () => {
  it('落在契约的字符白名单里(不合规会 400,不是静默忽略)', () => {
    for (let i = 0; i < 20; i += 1) {
      expect(newIdempotencyKey()).toMatch(IDEMPOTENCY_KEY_PATTERN)
    }
  })

  it('每次调用都不同(同一次上传才复用,跨上传不能撞)', () => {
    expect(newIdempotencyKey()).not.toBe(newIdempotencyKey())
  })
})

describe('uploadChatImage:一次上传的重试复用同一个 key', () => {
  it('5xx 后重试:两次请求的 Idempotency-Key 相同,第二次仍带完整文件', async () => {
    const keys: (string | null)[] = []
    const sizes: number[] = []
    let calls = 0
    server.use(
      mswHttp.post('/api/v1/im/images', async ({ request }) => {
        calls += 1
        keys.push(request.headers.get('Idempotency-Key'))
        const form = await request.formData()
        sizes.push((form.get('file') as File).size)
        return calls === 1
          ? HttpResponse.json({ code: 500, message: '服务器开小差了' }, { status: 500 })
          : HttpResponse.json(uploadedImage, { status: 201 })
      }),
    )

    await expect(uploadChatImage(imageFile(), { sleep: vi.fn(async () => {}) })).resolves.toEqual(
      uploadedImage,
    )

    expect(calls).toBe(2)
    expect(keys[0]).toMatch(IDEMPOTENCY_KEY_PATTERN)
    expect(keys[1]).toBe(keys[0])
    // FormData 是重新构造的:第二次请求里文件还在(复用脏对象会变成空 body)
    expect(sizes).toEqual([3, 3])
  })

  it('换一张图 → 新 key(不是同一次上传)', async () => {
    const keys: (string | null)[] = []
    server.use(
      mswHttp.post('/api/v1/im/images', ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key'))
        return HttpResponse.json(uploadedImage, { status: 201 })
      }),
    )

    await uploadChatImage(imageFile())
    await uploadChatImage(imageFile())

    expect(keys).toHaveLength(2)
    expect(keys[0]).toMatch(IDEMPOTENCY_KEY_PATTERN)
    expect(keys[1]).not.toBe(keys[0])
  })

  it('409 + 40901:按契约退避 1–2 秒后同 key 重试,最终成功(不是终态失败)', async () => {
    const keys: (string | null)[] = []
    let calls = 0
    server.use(
      mswHttp.post('/api/v1/im/images', ({ request }) => {
        calls += 1
        keys.push(request.headers.get('Idempotency-Key'))
        return calls === 1 ? inFlight() : HttpResponse.json(uploadedImage, { status: 201 })
      }),
    )
    const sleep = vi.fn(async () => {})

    await expect(uploadChatImage(imageFile(), { sleep })).resolves.toEqual(uploadedImage)

    expect(calls).toBe(2)
    expect(keys[1]).toBe(keys[0])
    expect(sleep).toHaveBeenCalledTimes(1)
    // 退避不短于契约说的 1 秒(基础退避是 500ms,40901 单独抬到 1 秒)
    expect(sleep).toHaveBeenCalledWith(UPLOAD_IN_FLIGHT_DELAY_MS)
  })

  it('一直 40901:试满次数后老实上抛(可重试不等于无限重试)', async () => {
    let calls = 0
    server.use(
      mswHttp.post('/api/v1/im/images', () => {
        calls += 1
        return inFlight()
      }),
    )

    await expect(uploadChatImage(imageFile(), { sleep: vi.fn(async () => {}) })).rejects.toThrow(
      '同一次上传正在处理中',
    )
    expect(calls).toBe(UPLOAD_ATTEMPTS)
  })

  it.each([400, 413])('%i 立刻冒泡:不重试、不换 key', async (status) => {
    let calls = 0
    server.use(
      mswHttp.post('/api/v1/im/images', () => {
        calls += 1
        return HttpResponse.json({ code: status, message: '请求本身不对' }, { status })
      }),
    )
    const sleep = vi.fn(async () => {})

    await expect(uploadChatImage(imageFile(), { sleep })).rejects.toThrow('请求本身不对')

    expect(calls).toBe(1)
    expect(sleep).not.toHaveBeenCalled()
  })
})

describe('401 刷新后重放同一次上传:key 不变、请求体重建', () => {
  it('刷新拿新 access 后重发,Idempotency-Key 一致且文件仍在', async () => {
    tokenStore.access = 'expired'
    const keys: (string | null)[] = []
    const sizes: number[] = []
    let calls = 0
    server.use(
      mswHttp.post('/api/v1/im/images', async ({ request }) => {
        calls += 1
        keys.push(request.headers.get('Idempotency-Key'))
        const form = await request.formData()
        sizes.push((form.get('file') as File).size)
        if (request.headers.get('Authorization') !== 'Bearer new-access') {
          return HttpResponse.json({ code: 40100, message: '未认证' }, { status: 401 })
        }
        return HttpResponse.json(uploadedImage, { status: 201 })
      }),
      mswHttp.post('/api/v1/auth/token/refresh', () => HttpResponse.json({ access: 'new-access' })),
    )

    await expect(uploadChatImage(imageFile(), { sleep: vi.fn(async () => {}) })).resolves.toEqual(
      uploadedImage,
    )

    expect(calls).toBe(2)
    expect(tokenStore.access).toBe('new-access')
    // 重放的是同一次上传:key 不变;FormData 被重建,文件没有丢
    expect(keys[1]).toBe(keys[0])
    expect(sizes).toEqual([3, 3])
  })
})

describe('uploadChatVoice:同一个 key 走完重试,40901 可重试', () => {
  it('40901 后同 key 重试,拿回 201 的地址', async () => {
    const keys: (string | null)[] = []
    let calls = 0
    server.use(
      mswHttp.post('/api/v1/im/voices', ({ request }) => {
        calls += 1
        keys.push(request.headers.get('Idempotency-Key'))
        return calls === 1 ? inFlight() : HttpResponse.json(uploadedVoice, { status: 201 })
      }),
    )
    const sleep = vi.fn(async () => {})

    const result = await uploadChatVoice(new Blob(['a'], { type: 'audio/webm' }), 3200, { sleep })

    expect(result.queued).toBe(false)
    expect(calls).toBe(2)
    expect(keys[1]).toBe(keys[0])
    expect(sleep).toHaveBeenCalledWith(UPLOAD_IN_FLIGHT_DELAY_MS)
  })

  it('202 受理也是成功:不再重试,key 只用一次', async () => {
    const keys: (string | null)[] = []
    server.use(
      mswHttp.post('/api/v1/im/voices', ({ request }) => {
        keys.push(request.headers.get('Idempotency-Key'))
        return HttpResponse.json({ id: 46, status: 'pending', retry_after: 1 }, { status: 202 })
      }),
    )
    const sleep = vi.fn(async () => {})

    const result = await uploadChatVoice(new Blob(['a'], { type: 'audio/webm' }), 3200, { sleep })

    expect(result).toEqual({ queued: true, id: 46, retryAfterSeconds: 1 })
    expect(keys).toHaveLength(1)
    expect(sleep).not.toHaveBeenCalled()
  })

  it('400 立刻冒泡:不重试', async () => {
    let calls = 0
    server.use(
      mswHttp.post('/api/v1/im/voices', () => {
        calls += 1
        return HttpResponse.json({ code: 40007, message: '语音不能超过 60 秒' }, { status: 400 })
      }),
    )

    await expect(
      uploadChatVoice(new Blob(['a'], { type: 'audio/webm' }), 90000, {
        sleep: vi.fn(async () => {}),
      }),
    ).rejects.toThrow('语音不能超过 60 秒')
    expect(calls).toBe(1)
  })
})

describe('uploadProfileVoice:同一个 key 走完重试,413 不重试', () => {
  it('40901 后同 key 重试成功', async () => {
    const keys: (string | null)[] = []
    const types: string[] = []
    let calls = 0
    server.use(
      mswHttp.post('/api/v1/users/me/voice', async ({ request }) => {
        calls += 1
        keys.push(request.headers.get('Idempotency-Key'))
        // 重试也必须是完整、合法的 part:重建 FormData 时 MIME 仍被钉成白名单值
        const form = await request.formData()
        types.push((form.get('file') as File).type)
        return calls === 1 ? inFlight() : HttpResponse.json(profileVoice, { status: 201 })
      }),
    )

    const result = await uploadProfileVoice(new Blob(['audio'], { type: 'audio/webm' }), {
      sleep: vi.fn(async () => {}),
    })

    expect(result).toEqual({ queued: false, voice: profileVoice })
    expect(calls).toBe(2)
    expect(keys[1]).toBe(keys[0])
    expect(types).toEqual(['audio/webm', 'audio/webm'])
  })

  it('413 立刻冒泡:只请求一次(配额满了重试也一样)', async () => {
    let calls = 0
    server.use(
      mswHttp.post('/api/v1/users/me/voice', () => {
        calls += 1
        return HttpResponse.json(
          { code: 41301, message: '存储空间已满,请先删除部分照片' },
          { status: 413 },
        )
      }),
    )
    const sleep = vi.fn(async () => {})

    await expect(
      uploadProfileVoice(new Blob(['audio'], { type: 'audio/webm' }), { sleep }),
    ).rejects.toThrow('存储空间已满')
    expect(calls).toBe(1)
    expect(sleep).not.toHaveBeenCalled()
  })
})

describe('uploadRetryDelay:409 只有 40901 才是可重试', () => {
  const apiFailure = (status: number, code: number) =>
    Object.assign(new Error('boom'), {
      isAxiosError: true,
      response: { status, headers: {}, data: { code, message: 'boom' } },
    })

  it('409 + 40901 → 至少等 1 秒再来(同 key)', () => {
    expect(uploadRetryDelay(apiFailure(409, 40901), 500)).toBe(UPLOAD_IN_FLIGHT_DELAY_MS)
  })

  it('其它 409(不是「同一次上传在跑」)不重试', () => {
    expect(uploadRetryDelay(apiFailure(409, 409), 500)).toBeNull()
  })

  it('400 / 413 不重试', () => {
    expect(uploadRetryDelay(apiFailure(400, 400), 500)).toBeNull()
    expect(uploadRetryDelay(apiFailure(413, 41301), 500)).toBeNull()
  })
})

describe('withUploadRetries:每次尝试都重新构造请求体', () => {
  it('两次尝试拿到的是两个不同的 FormData,且都带着文件', async () => {
    const bodies: FormData[] = []
    let calls = 0
    const result = await withUploadRetries(
      async () => {
        const form = new FormData()
        form.append('file', new Blob(['payload']), 'a.bin')
        bodies.push(form)
        calls += 1
        if (calls === 1) {
          throw Object.assign(new Error('服务器开小差了'), {
            isAxiosError: true,
            response: { status: 500, headers: {}, data: { code: 500, message: '服务器开小差了' } },
          })
        }
        return 'ok'
      },
      { attempts: 2, sleep: async () => {} },
    )

    expect(result).toBe('ok')
    expect(bodies).toHaveLength(2)
    expect(bodies[0]).not.toBe(bodies[1])
    expect((bodies[1].get('file') as File).size).toBe(7)
  })
})
