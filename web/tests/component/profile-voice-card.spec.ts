import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { HttpResponse, http as mswHttp } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ProfileVoiceCard from '@/features/profile/ProfileVoiceCard.vue'
import { PROFILE_VOICE_MIME_TYPES } from '@/api/users'
import { useProfileStore } from '@/stores/profile'
import { freshPinia } from '../support/pinia'
import { server } from '../support/server'

/** 假 MediaRecorder:start 后 state 变 recording,stop 触发 ondataavailable + onstop。 */
class FakeRecorder {
  static supported = ['audio/webm;codecs=opus']
  static isTypeSupported = (type: string) => FakeRecorder.supported.includes(type)

  state = 'inactive'
  mimeType = 'audio/webm;codecs=opus'
  ondataavailable: ((event: { data: Blob }) => void) | null = null
  onstop: (() => void) | null = null

  start(): void {
    this.state = 'recording'
  }

  stop(): void {
    this.state = 'inactive'
    this.ondataavailable?.({ data: new Blob(['chunk'], { type: this.mimeType }) })
    this.onstop?.()
  }
}

const me = {
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

const savedVoice = { url: 'https://cdn/media/voices/abc.m4a', duration_ms: 8500 }

/** 挂载前先把资料灌进 store:页面只读 store,卡片同理。 */
async function mountCard(payload: Record<string, unknown> = me) {
  server.use(mswHttp.get('/api/v1/users/me', () => HttpResponse.json(payload)))
  const pinia = freshPinia()
  const store = useProfileStore()
  await store.load()
  const w = mount(ProfileVoiceCard, { global: { plugins: [pinia] } })
  await flushPromises()
  return { w, store }
}

/** 录一段(2.5 秒)并点「保存语音」,用于断言各种上传失败提示。 */
async function recordAndSave(w: ReturnType<typeof mount>) {
  await w.find('.voice-card__mic').trigger('click')
  await flushPromises()
  vi.advanceTimersByTime(2500)
  await w.find('.voice-bar__send').trigger('click')
  await flushPromises()
  await w.find('.voice-card__save').trigger('click')
  await flushPromises()
}

describe('ProfileVoiceCard', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.stubGlobal('MediaRecorder', FakeRecorder)
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] })) },
    })
    // jsdom 没有 objectURL 实现,直接钉在 URL 构造器上
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:preview'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    setActivePinia(createPinia())
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
    vi.restoreAllMocks() // 顺带还原 window.confirm 的 spy
  })

  it('没录过语音时露出麦克风入口与 30 秒说明', async () => {
    const { w } = await mountCard()
    expect(w.find('.voice-card__mic').exists()).toBe(true)
    expect(w.text()).toContain('最长 30 秒')
    expect(w.find('.voice-bar').exists()).toBe(false)
  })

  it('点麦克风进入录音条,停止后可试听并保存(part MIME 必为白名单值)', async () => {
    let partType = ''
    let keys: string[] = []
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)),
      mswHttp.post('/api/v1/users/me/voice', async ({ request }) => {
        const form = await request.formData()
        keys = [...form.keys()]
        partType = (form.get('file') as File).type
        return HttpResponse.json(savedVoice, { status: 201 })
      }),
    )
    const { w, store } = await mountCard()

    await w.find('.voice-card__mic').trigger('click')
    await flushPromises()
    expect(w.find('.voice-bar').exists()).toBe(true)
    expect(w.text()).toContain('停止')

    vi.advanceTimersByTime(2500)
    await w.find('.voice-bar__send').trigger('click')
    await flushPromises()

    // 已录好:本地播放条 + 重录 / 保存
    expect(w.find('.voice-bar').exists()).toBe(false)
    expect(w.text()).toContain('3″')
    expect(w.find('.voice-card__save').exists()).toBe(true)

    await w.find('.voice-card__save').trigger('click')
    await flushPromises()

    expect(keys).toEqual(['file'])
    expect(PROFILE_VOICE_MIME_TYPES).toContain(partType)
    expect(partType).toBe('audio/webm')
    expect(store.profile?.voice).toEqual(savedVoice)
    expect(w.text()).toContain('语音已保存')
    // 保存后只剩「已保存」态:重录 + 删除语音
    expect(w.find('.voice-card__delete').exists()).toBe(true)
  })

  it('上传被 400 打回:显示服务端文案,本地录音保留可原地重试', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)),
      mswHttp.post('/api/v1/users/me/voice', () =>
        HttpResponse.json(
          { code: 40007, message: '只支持 M4A/AAC/WebM/OGG 音频', request_id: 'r' },
          { status: 400 },
        ),
      ),
    )
    const { w } = await mountCard()

    await recordAndSave(w)

    expect(w.text()).toContain('只支持 M4A/AAC/WebM/OGG 音频')
    // 失败不丢草稿:还能直接再点一次保存(不必重录)
    expect(w.find('.voice-card__save').exists()).toBe(true)
  })

  it('存储配额满(413)按「空间不足」提示', async () => {
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)),
      mswHttp.post('/api/v1/users/me/voice', () =>
        HttpResponse.json(
          {
            code: 41301,
            message: '存储空间已满(已用 200MB / 上限 200MB),请先删除部分照片,或等待聊天图片过期',
            request_id: 'r',
          },
          { status: 413 },
        ),
      ),
    )
    const { w } = await mountCard()

    await recordAndSave(w)

    expect(w.text()).toContain('存储空间已满')
  })

  it('录制中点取消丢掉这段录音,不上传', async () => {
    let uploaded = false
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)),
      mswHttp.post('/api/v1/users/me/voice', () => {
        uploaded = true
        return HttpResponse.json(savedVoice, { status: 201 })
      }),
    )
    const { w } = await mountCard()

    await w.find('.voice-card__mic').trigger('click')
    await flushPromises()
    vi.advanceTimersByTime(2000)
    await w.find('.voice-bar__cancel').trigger('click')
    await flushPromises()

    expect(w.find('.voice-bar').exists()).toBe(false)
    expect(w.find('.voice-card__mic').exists()).toBe(true)
    expect(uploaded).toBe(false)
  })

  it('离开页面统一按「取消」处理:录到一半卸载不发送', async () => {
    let uploaded = false
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json(me)),
      mswHttp.post('/api/v1/users/me/voice', () => {
        uploaded = true
        return HttpResponse.json(savedVoice, { status: 201 })
      }),
    )
    const { w } = await mountCard()

    await w.find('.voice-card__mic').trigger('click')
    await flushPromises()
    vi.advanceTimersByTime(5000)
    w.unmount()
    await flushPromises()

    expect(uploaded).toBe(false)
  })

  it('已有语音:显示播放条与删除,删除后回到录音入口', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    let deleted = false
    server.use(
      mswHttp.get('/api/v1/users/me', () => HttpResponse.json({ ...me, voice: savedVoice })),
      mswHttp.delete('/api/v1/users/me/voice', () => {
        deleted = true
        return new HttpResponse(null, { status: 204 })
      }),
    )
    const { w, store } = await mountCard({ ...me, voice: savedVoice })
    await flushPromises()

    expect(w.text()).toContain('9″')
    expect(w.find('.voice-card__delete').exists()).toBe(true)

    await w.find('.voice-card__delete').trigger('click')
    await flushPromises()

    expect(confirmSpy).toHaveBeenCalled()
    expect(deleted).toBe(true)
    expect(store.profile?.voice).toBeNull()
    expect(w.text()).toContain('已删除')
    expect(w.find('.voice-card__mic').exists()).toBe(true)
  })

  it('浏览器不支持录音时点击麦克风说明原因,而不是静默', async () => {
    vi.unstubAllGlobals() // 回到 jsdom:没有 MediaRecorder
    const { w } = await mountCard()

    expect(w.find('.voice-card__mic').attributes('aria-disabled')).toBe('true')
    await w.find('.voice-card__mic').trigger('click')
    await flushPromises()

    expect(w.find('.voice-bar').exists()).toBe(false)
    expect(w.text()).toContain('当前浏览器不支持录音')
  })
})
