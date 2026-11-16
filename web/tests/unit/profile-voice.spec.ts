import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchProfileVoiceStatus, PROFILE_VOICE_MIME_TYPES, profileVoicePartType } from '@/api/users'
import { useProfileStore } from '@/stores/profile'
import { server } from '../support/server'

const mePayload = {
  id: 11,
  user_id: 9,
  phone: '13800000001',
  nickname: '小雨',
  gender: 'female',
  birthday: '2000-01-01',
  age: 26,
  city: '上海',
  bio: '你好',
  status: 'complete',
  ban_reason: '',
  missing_fields: [],
  tags: [],
  photos: [],
  preference: { target_gender: null, age_min: 18, age_max: 99, city: '' },
  voice: null,
}

const voicePayload = { url: 'https://cdn/media/voices/7f3a.m4a', duration_ms: 8500 }

describe('资料语音:MIME 归一', () => {
  it('去掉 codecs 参数后仍是白名单值', () => {
    expect(profileVoicePartType('audio/webm;codecs=opus')).toBe('audio/webm')
    expect(profileVoicePartType('audio/ogg;codecs=opus')).toBe('audio/ogg')
  })

  it('白名单内的主类型原样保留', () => {
    for (const type of PROFILE_VOICE_MIME_TYPES) {
      expect(profileVoicePartType(type)).toBe(type)
    }
  })

  it('空 / 不在白名单的一律兜底成 audio/webm,绝不送 octet-stream', () => {
    expect(profileVoicePartType('')).toBe('audio/webm')
    expect(profileVoicePartType('application/octet-stream')).toBe('audio/webm')
    expect(profileVoicePartType('video/webm')).toBe('audio/webm')
  })
})

describe('资料语音:store 上传/删除', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('上传:multipart 字段只有 file,且那个 part 的 MIME 在白名单内', async () => {
    let keys: string[] = []
    let partType = ''
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(mePayload)),
      mswHttp.post('/api/v1/users/me/voice', async ({ request }) => {
        const form = await request.formData()
        keys = [...form.keys()]
        const file = form.get('file') as File
        partType = file.type
        return HttpResponse.json(voicePayload, { status: 201 })
      }),
    )
    const store = useProfileStore()
    await store.load()

    // 浏览器录音的典型形状:带 codecs 参数
    await store.uploadVoice(new Blob(['audio-bytes'], { type: 'audio/webm;codecs=opus' }))

    expect(keys).toEqual(['file']) // 契约只有 file,客户端不声明时长
    expect(PROFILE_VOICE_MIME_TYPES).toContain(partType)
    expect(partType).toBe('audio/webm')
    expect(store.profile?.voice).toEqual(voicePayload)
  })

  it('上传:Blob 没有 type 时也要送白名单 MIME(application/octet-stream 会被 400)', async () => {
    let partType = ''
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(mePayload)),
      mswHttp.post('/api/v1/users/me/voice', async ({ request }) => {
        const form = await request.formData()
        partType = (form.get('file') as File).type
        return HttpResponse.json(voicePayload, { status: 201 })
      }),
    )
    const store = useProfileStore()
    await store.load()

    await store.uploadVoice(new Blob(['audio-bytes']))

    expect(partType).not.toBe('application/octet-stream')
    expect(PROFILE_VOICE_MIME_TYPES).toContain(partType)
  })

  it('上传失败时不影响已有语音', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json({ ...mePayload, voice: voicePayload })),
      mswHttp.post('/api/v1/users/me/voice', () =>
        HttpResponse.json(
          { code: 40007, message: '语音不能超过 5MB', request_id: 'r' },
          { status: 400 },
        ),
      ),
    )
    const store = useProfileStore()
    await store.load()

    await expect(store.uploadVoice(new Blob(['x'], { type: 'audio/webm' }))).rejects.toThrow()
    expect(store.profile?.voice).toEqual(voicePayload)
  })

  it('删除:DELETE 到 /users/me/voice 并把本地 voice 置回 null', async () => {
    let method = ''
    let path = ''
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json({ ...mePayload, voice: voicePayload })),
      mswHttp.delete('/api/v1/users/me/voice', ({ request }) => {
        method = request.method
        path = new URL(request.url).pathname
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const store = useProfileStore()
    await store.load()
    expect(store.profile?.voice).toEqual(voicePayload)

    await store.removeVoice()

    expect(method).toBe('DELETE')
    expect(path).toBe('/api/v1/users/me/voice')
    expect(store.profile?.voice).toBeNull()
  })
})

/** 202 受理体(im.md §6.4 / users.md §2.11 同形状);retry_after 取 1 秒让用例跑得快。 */
const queuedPayload = { id: 7, status: 'pending', retry_after: 1 }

/** 一条三态状态;轮询接口 users.md §2.13。 */
function voiceStatus(
  code: 'pending' | 'ready' | 'failed',
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    id: 7,
    status: code,
    url: code === 'ready' ? 'https://cdn/media/voices/new.m4a?e=1&s=x' : null,
    duration_ms: code === 'ready' ? 12500 : null,
    size: code === 'ready' ? 72000 : null,
    code: null,
    message: null,
    ...extra,
  }
}

describe('资料语音:异步转码(M-3)', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('202 受理 → 旧语音先下线 → 轮询 ready 后填回播放地址', async () => {
    const store = useProfileStore()
    /** 第一次轮询时的本地状态:覆盖语义要求旧语音此刻已经没了,且页面处于「转码中」 */
    let voiceDuringPoll: unknown = 'unset'
    let processingDuringPoll: unknown = 'unset'
    const answers = [voiceStatus('pending'), voiceStatus('ready')]
    server.use(
      mswHttp.get('/api/v1/users/me', () =>
        HttpResponse.json({ ...mePayload, voice: voicePayload }),
      ),
      mswHttp.post('/api/v1/users/me/voice', () =>
        HttpResponse.json(queuedPayload, { status: 202 }),
      ),
      mswHttp.get('/api/v1/users/me/voice', () => {
        if (voiceDuringPoll === 'unset') {
          voiceDuringPoll = store.profile?.voice
          processingDuringPoll = store.voiceProcessing
        }
        return HttpResponse.json(answers.shift() ?? voiceStatus('ready'))
      }),
    )
    await store.load()
    expect(store.profile?.voice).toEqual(voicePayload)

    const uploading = store.uploadVoice(new Blob(['audio-bytes'], { type: 'audio/webm' }))
    await vi.advanceTimersByTimeAsync(1000)
    await vi.advanceTimersByTimeAsync(1000)

    await expect(uploading).resolves.toBe('ready')
    expect(voiceDuringPoll).toBeNull() // 轮询期间旧语音已在本地下线
    expect(processingDuringPoll).toBe(true) // 页面据此显示「正在转码」
    expect(store.voiceProcessing).toBe(false)
    expect(store.profile?.voice).toEqual({
      url: 'https://cdn/media/voices/new.m4a?e=1&s=x',
      duration_ms: 12500,
      status: 'ready',
    })
  })

  it('202 → failed:抛出服务端给的中文原因,本地没有语音', async () => {
    const store = useProfileStore()
    server.use(
      mswHttp.get('/api/v1/users/me', () =>
        HttpResponse.json({ ...mePayload, voice: voicePayload }),
      ),
      mswHttp.post('/api/v1/users/me/voice', () =>
        HttpResponse.json(queuedPayload, { status: 202 }),
      ),
      mswHttp.get('/api/v1/users/me/voice', () =>
        HttpResponse.json(
          voiceStatus('failed', { code: '41301', message: '存储空间已满,请先删除部分照片' }),
        ),
      ),
    )
    await store.load()

    const uploading = store.uploadVoice(new Blob(['x'], { type: 'audio/webm' }))
    // 先挂上拒绝断言再推进定时器,否则这一拍里没人接的 rejection 会变成未处理拒绝
    const failure = expect(uploading).rejects.toThrow('存储空间已满')
    await vi.advanceTimersByTimeAsync(1000)

    await failure
    expect(store.voiceProcessing).toBe(false)
    expect(store.profile?.voice).toBeNull()
  })

  it('轮询回 404:按「未录制」处理(absent),不谎报已保存', async () => {
    const store = useProfileStore()
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(mePayload)),
      mswHttp.post('/api/v1/users/me/voice', () =>
        HttpResponse.json(queuedPayload, { status: 202 }),
      ),
      mswHttp.get('/api/v1/users/me/voice', () =>
        HttpResponse.json({ code: 404, message: '未找到', request_id: 'r' }, { status: 404 }),
      ),
    )
    await store.load()

    // 404 不是错误:resolve 成 'absent',页面据此按「未录制」渲染
    await expect(store.uploadVoice(new Blob(['x'], { type: 'audio/webm' }))).resolves.toBe('absent')
    expect(store.profile?.voice).toBeNull()
    expect(store.voiceProcessing).toBe(false)
  })

  it('GET /users/me/voice 的 404 在封装层就是 null,不抛异常', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me/voice', () =>
        HttpResponse.json({ code: 404, message: '未找到', request_id: 'r' }, { status: 404 }),
      ),
    )

    await expect(fetchProfileVoiceStatus()).resolves.toBeNull()
  })
})
