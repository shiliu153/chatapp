/**
 * 聊天语音的异步转码链路(M-3,契约 `docs/api/im.md` §6.4 / §6.5)。
 *
 * 三个层面各钉一条:
 * 1. `uploadChatVoice` 认 201 / 202 两种响应,别把受理体当「已转码」;
 * 2. `awaitChatVoice` 轮询到 `ready` 才给出可发送的 `url`,`failed` 抛出可展示的中文;
 * 3. `SelfImClient.sendVoice` 的顺序是「上传 → (202 时)等转码 → 才发 WS 帧」,
 *    并且中途通过 `onTranscoding` 通知 UI。
 */
import { HttpResponse, http as mswHttp } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { awaitChatVoice, uploadChatVoice } from '@/im/self/voice'
import { SelfImClient } from '@/im/self/client'
import type { SelfTransport } from '@/im/self/transport'
import type { ImBootstrap } from '@/im/types'
import { server } from '../support/server'

const readyPayload = {
  id: 46,
  url: 'https://cdn/media/chat/voices/46.m4a?e=1&s=x',
  duration_ms: 3200,
  size: 12345,
  status: 'ready',
}

const queuedPayload = { id: 46, status: 'pending', retry_after: 1 }

describe('uploadChatVoice:201 与 202', () => {
  it('201 直接给地址:queued=false,可直接发帧', async () => {
    server.use(
      mswHttp.post('/api/v1/im/voices', () => HttpResponse.json(readyPayload, { status: 201 })),
    )

    const result = await uploadChatVoice(new Blob(['a'], { type: 'audio/webm' }), 3200)

    expect(result.queued).toBe(false)
    if (!result.queued) {
      expect(result.voice.url).toBe(readyPayload.url)
      expect(result.voice.duration_ms).toBe(3200)
    }
  })

  it('202 只有 id 与 retry_after:queued=true,不能当成功', async () => {
    server.use(
      mswHttp.post('/api/v1/im/voices', () => HttpResponse.json(queuedPayload, { status: 202 })),
    )

    const result = await uploadChatVoice(new Blob(['a'], { type: 'audio/webm' }), 3200)

    expect(result).toEqual({ queued: true, id: 46, retryAfterSeconds: 1 })
  })

  it('上传仍是 multipart:字段是 file + duration_ms(契约没变)', async () => {
    let keys: string[] = []
    let duration = ''
    server.use(
      mswHttp.post('/api/v1/im/voices', async ({ request }) => {
        const form = await request.formData()
        keys = [...form.keys()]
        duration = String(form.get('duration_ms'))
        return HttpResponse.json(readyPayload, { status: 201 })
      }),
    )

    await uploadChatVoice(new Blob(['a'], { type: 'audio/webm' }), 3200)

    expect(keys).toEqual(['file', 'duration_ms'])
    expect(duration).toBe('3200')
  })
})

describe('awaitChatVoice:轮询到转码落定', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('pending 两次后 ready:返回可直接塞进 send 帧的载荷', async () => {
    const statuses = [
      { ...readyPayload, status: 'pending', url: null, duration_ms: null, size: null },
      { ...readyPayload, status: 'pending', url: null, duration_ms: null, size: null },
      readyPayload,
    ]
    let calls = 0
    server.use(
      mswHttp.get('/api/v1/im/voices/46', () => {
        calls += 1
        return HttpResponse.json(statuses.shift() ?? readyPayload)
      }),
    )

    const done = awaitChatVoice(46, 1)
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(1000)

    await expect(done).resolves.toEqual({
      id: 46,
      url: readyPayload.url,
      duration_ms: 3200,
      size: 12345,
    })
    expect(calls).toBe(3)
  })

  it('failed:抛出服务端给的中文原因(用户能照着做)', async () => {
    server.use(
      mswHttp.get('/api/v1/im/voices/46', () =>
        HttpResponse.json({
          id: 46,
          status: 'failed',
          url: null,
          duration_ms: null,
          size: null,
          code: '41301',
          message: '存储空间已满,请先删除部分照片',
        }),
      ),
    )

    await expect(awaitChatVoice(46, 1)).rejects.toThrow('存储空间已满')
  })

  it('failed 且服务端没给 message:用兜底话术', async () => {
    server.use(
      mswHttp.get('/api/v1/im/voices/46', () =>
        HttpResponse.json({
          id: 46,
          status: 'failed',
          url: null,
          duration_ms: null,
          size: null,
          code: null,
          message: null,
        }),
      ),
    )

    await expect(awaitChatVoice(46, 1)).rejects.toThrow('语音转码失败')
  })
})

/** 假传输:只记录上行帧,便于断言「转码没完成之前一帧都不发」。 */
class FakeTransport implements SelfTransport {
  sent: string[] = []
  private handler?: (raw: string) => void

  onFrame(fn: (raw: string) => void): void {
    this.handler = fn
  }

  onClose(): void {}

  async connect(): Promise<void> {}

  send(raw: string): void {
    this.sent.push(raw)
  }

  async close(): Promise<void> {}

  emit(raw: string): void {
    this.handler?.(raw)
  }
}

const bootstrap: ImBootstrap = {
  token: 'tok',
  wsUrl: 'ws://test/im/ws',
  httpUrl: 'http://test/im/api',
  imUserId: 'u9',
}

/** 推进一个宏任务:客户端发帧/处理 ack 都在微任务里,等一拍就够。 */
const flush = (): Promise<void> => new Promise((resolve) => setTimeout(resolve, 0))

async function loggedIn(client: SelfImClient, transport: FakeTransport): Promise<void> {
  await client.init(bootstrap)
  const login = client.login('u9', 'tok')
  await flush()
  transport.emit('{"v":1,"type":"auth_ok","data":{"uid":9}}')
  await login
}

describe('SelfImClient.sendVoice:202 受理', () => {
  it('先等转码拿到 url,才发 send 帧;期间通知了 onTranscoding', async () => {
    const transport = new FakeTransport()
    const waited: Array<[number, number]> = []
    const phases: string[] = []
    // 手动放行的「转码 Promise」:否则等不出「转码中途」这个观察点(全是微任务)
    let releaseTranscode: () => void = () => {}
    const client = new SelfImClient(
      () => transport,
      undefined,
      async () => ({ queued: true as const, id: 46, retryAfterSeconds: 1 }),
      async (voiceId: number, retryAfter: number) => {
        waited.push([voiceId, retryAfter])
        await new Promise<void>((resolve) => {
          releaseTranscode = resolve
        })
        return { id: 46, url: readyPayload.url, duration_ms: 3200, size: 12345 }
      },
    )
    await loggedIn(client, transport)

    const sending = client.sendVoice('u2', new Blob(['a']), 3200, undefined, {
      onTranscoding: () => phases.push('transcoding'),
    })
    await flush()

    // 转码期间:只有 auth 帧,还没有 send 帧 —— 没有 url 的语音帧对方播不了
    expect(transport.sent.filter((raw) => raw.includes('"type":"send"'))).toHaveLength(0)
    expect(phases).toEqual(['transcoding'])
    expect(waited).toEqual([[46, 1]])

    // 转码完成后才有 send 帧
    releaseTranscode()
    await flush()
    const frame = JSON.parse(transport.sent[transport.sent.length - 1]) as {
      id: string
      data: { kind: string; voice: { url: string; duration_ms: number; size: number } }
    }
    expect(frame.data.kind).toBe('voice')
    expect(frame.data.voice.url).toBe(readyPayload.url)
    expect(frame.data.voice.duration_ms).toBe(3200)

    transport.emit(
      JSON.stringify({
        v: 1,
        type: 'ack',
        id: frame.id,
        data: { msg_id: '900', seq: 7, ts: 1700000000000 },
      }),
    )
    await expect(sending).resolves.toMatchObject({ msgId: '900', kind: 'voice' })
  })

  it('转码失败时抛错、一帧都不发(让气泡变成可重试的失败态)', async () => {
    const transport = new FakeTransport()
    const client = new SelfImClient(
      () => transport,
      undefined,
      async () => ({ queued: true as const, id: 46, retryAfterSeconds: 1 }),
      async () => Promise.reject(new Error('存储空间已满,请先删除部分照片')),
    )
    await loggedIn(client, transport)

    await expect(client.sendVoice('u2', new Blob(['a']), 3200)).rejects.toThrow('存储空间已满')
    expect(transport.sent.filter((raw) => raw.includes('"type":"send"'))).toHaveLength(0)
  })

  it('201 老路径不变:不发轮询、onTranscoding 不触发', async () => {
    const transport = new FakeTransport()
    const waitVoice = vi.fn()
    const client = new SelfImClient(
      () => transport,
      undefined,
      async () => ({
        queued: false as const,
        voice: { id: 46, url: readyPayload.url, duration_ms: 3200, size: 12345 },
      }),
      waitVoice,
    )
    await loggedIn(client, transport)

    const sending = client.sendVoice('u2', new Blob(['a']), 3200, undefined, {
      onTranscoding: () => {
        throw new Error('201 不该进转码态')
      },
    })
    await flush()
    const frame = JSON.parse(transport.sent[transport.sent.length - 1]) as { id: string }
    transport.emit(
      JSON.stringify({
        v: 1,
        type: 'ack',
        id: frame.id,
        data: { msg_id: '901', seq: 8, ts: 1 },
      }),
    )

    await expect(sending).resolves.toMatchObject({ msgId: '901' })
    expect(waitVoice).not.toHaveBeenCalled()
  })
})
