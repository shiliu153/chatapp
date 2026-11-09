import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { beforeEach, describe, expect, it } from 'vitest'
import { PROFILE_VOICE_MIME_TYPES, profileVoicePartType } from '@/api/users'
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
