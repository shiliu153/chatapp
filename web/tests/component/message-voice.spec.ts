import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MessageVoice from '@/features/chat/MessageVoice.vue'
import type { VoiceProgress } from '@/im/voicePlayer'

const playVoice = vi.fn(
  (
    _url: string,
    onEnd: () => void,
    _onError?: () => void,
    _onProgress?: (p: VoiceProgress) => void,
  ) => onEnd(),
)
const stopVoice = vi.fn()
const seekVoice = vi.fn()
const setVoiceRate = vi.fn()

vi.mock('@/im/voicePlayer', () => ({
  playVoice: (
    url: string,
    onEnd: () => void,
    onError?: () => void,
    onProgress?: (p: VoiceProgress) => void,
  ) => playVoice(url, onEnd, onError, onProgress),
  stopVoice: () => stopVoice(),
  seekVoice: (ratio: number) => seekVoice(ratio),
  setVoiceRate: (rate: number) => setVoiceRate(rate),
}))

const CHAT_URL = 'http://cdn/media/chat/voices/a.m4a'

/** 点开播:返回被组件注册进来的进度回调(拿它模拟 `timeupdate`) */
async function startPlaying(
  wrapper: ReturnType<typeof mount>,
): Promise<(p: VoiceProgress) => void> {
  let progress: ((p: VoiceProgress) => void) | undefined
  playVoice.mockImplementationOnce(
    (
      _url: string,
      _onEnd: () => void,
      _onError?: () => void,
      onProgress?: (p: VoiceProgress) => void,
    ) => {
      progress = onProgress
    },
  )
  await wrapper.get('.voice__play').trigger('click')
  return (p) => progress?.(p)
}

describe('MessageVoice', () => {
  it('显示秒数,点一下播放', async () => {
    const w = mount(MessageVoice, { props: { url: CHAT_URL, durationMs: 12500 } })
    expect(w.text()).toContain('13″')

    await w.get('.voice__play').trigger('click')
    // 播完回调 + 失败回调 + 进度回调都给到播放器(批次 T 起共有四个参数)
    expect(playVoice).toHaveBeenCalledWith(
      CHAT_URL,
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
    )
    // 假播放器立即回调 onEnd,图标回到播放态
    expect(w.text()).toContain('▶')
  })

  it('没有 URL 时点击不播放', async () => {
    playVoice.mockClear()
    const w = mount(MessageVoice, { props: { url: null, durationMs: 3000 } })
    await w.get('.voice__play').trigger('click')
    expect(playVoice).not.toHaveBeenCalled()
  })

  it('没有地址时渲染不可播放的占位(失败/发送中的气泡)', () => {
    const w = mount(MessageVoice, { props: { url: null, durationMs: 3000 } })
    expect(w.find('.voice--empty').exists()).toBe(true)
    expect(w.get('.voice__play').attributes('aria-disabled')).toBe('true')
    expect(w.text()).toContain('🎙')
    // 不能播时连倍速按钮都不该出现
    expect(w.find('[data-testid="voice-rate"]').exists()).toBe(false)
  })

  it('资料语音口径:上限 30 秒,超长按 30 秒显示', () => {
    const w = mount(MessageVoice, {
      props: { url: 'https://cdn/media/voices/a.m4a', durationMs: 29_400, maxSeconds: 30 },
    })
    expect(w.text()).toContain('29″')

    const clamped = mount(MessageVoice, {
      props: { url: 'https://cdn/media/voices/a.m4a', durationMs: 42_000, maxSeconds: 30 },
    })
    expect(clamped.text()).toContain('30″')
  })

  it('播放失败时给出「播放失败,点击重试」而不是静默复位', async () => {
    // 资源 404 / 容器解不了 → 播放器回调 onError
    playVoice.mockImplementationOnce(
      (_url: string, _onEnd: () => void, onError?: () => void) => onError?.(),
    )
    const w = mount(MessageVoice, { props: { url: CHAT_URL, durationMs: 4000 } })

    await w.get('.voice__play').trigger('click')

    expect(w.text()).toContain('播放失败')
    expect(w.get('.voice__play').attributes('aria-label')).toBe('播放失败，点击重试')
    // 再点一次是重试,失败态先清掉
    await w.get('.voice__play').trigger('click')
    expect(w.text()).not.toContain('播放失败')
  })

  it('播放中再点一次是停止', async () => {
    const w = mount(MessageVoice, { props: { url: CHAT_URL, durationMs: 4000 } })
    await startPlaying(w)
    expect(w.text()).toContain('❚❚')

    await w.get('.voice__play').trigger('click')
    expect(stopVoice).toHaveBeenCalled()
    expect(w.text()).toContain('▶')
  })

  // --- 进度(批次 T)---

  it('timeupdate 推的进度反映到滑块与计时上', async () => {
    const w = mount(MessageVoice, { props: { url: CHAT_URL, durationMs: 12_500 } })
    const push = await startPlaying(w)

    push({ ratio: 0.5, currentMs: 6250, durationMs: 12_500 })
    await w.vm.$nextTick()

    const slider = w.get('[data-testid="voice-progress"]').element as HTMLInputElement
    expect(Number(slider.value)).toBe(500)
    expect(w.text()).toContain('0:06 / 13″')
  })

  it('拖动中滑块跟手(不被 timeupdate 拽回),松手才 seek', async () => {
    const w = mount(MessageVoice, { props: { url: CHAT_URL, durationMs: 20_000 } })
    const push = await startPlaying(w)
    const slider = w.get('[data-testid="voice-progress"]')

    // 拖到 80%
    ;(slider.element as HTMLInputElement).value = '800'
    await slider.trigger('input')
    expect((slider.element as HTMLInputElement).value).toBe('800')

    // 拖的过程中播放器还在推进度:不能把滑块拽回去
    push({ ratio: 0.1, currentMs: 2000, durationMs: 20_000 })
    await w.vm.$nextTick()
    expect(Number((slider.element as HTMLInputElement).value)).toBe(800)
    // 松手之前不 seek
    expect(seekVoice).not.toHaveBeenCalled()

    await slider.trigger('change')
    expect(seekVoice).toHaveBeenCalledWith(0.8)
    // 松手后停在拖到的位置
    expect(Number((slider.element as HTMLInputElement).value)).toBe(800)
  })

  it('没在播时进度条不可拖(seek 只对正在播的那条有意义)', () => {
    const w = mount(MessageVoice, { props: { url: CHAT_URL, durationMs: 4000 } })
    expect(w.get('[data-testid="voice-progress"]').attributes('disabled')).toBeDefined()
  })

  // --- 倍速(批次 T)---

  it('倍速按钮按 1.0x → 1.5x → 2.0x → 1.0x 循环', async () => {
    const w = mount(MessageVoice, { props: { url: CHAT_URL, durationMs: 4000 } })
    const rate = w.get('[data-testid="voice-rate"]')

    expect(rate.text()).toBe('1.0x')
    await rate.trigger('click')
    expect(rate.text()).toBe('1.5x')
    expect(setVoiceRate).toHaveBeenCalledWith(1.5)

    await rate.trigger('click')
    expect(rate.text()).toBe('2.0x')
    expect(setVoiceRate).toHaveBeenCalledWith(2)

    await rate.trigger('click')
    expect(rate.text()).toBe('1.0x')
    expect(setVoiceRate).toHaveBeenLastCalledWith(1)
  })

  it('先选倍速再播放:开播后立刻把倍速设上', async () => {
    setVoiceRate.mockClear()
    const w = mount(MessageVoice, { props: { url: CHAT_URL, durationMs: 4000 } })

    await w.get('[data-testid="voice-rate"]').trigger('click')
    await w.get('[data-testid="voice-rate"]').trigger('click')
    setVoiceRate.mockClear()

    await startPlaying(w)
    expect(setVoiceRate).toHaveBeenCalledWith(2)
  })

  it('这一条播完倍速复位 1.0x(换条播放也不带过去)', async () => {
    const w = mount(MessageVoice, { props: { url: CHAT_URL, durationMs: 4000 } })
    await w.get('[data-testid="voice-rate"]').trigger('click')
    await w.get('[data-testid="voice-rate"]').trigger('click')
    expect(w.get('[data-testid="voice-rate"]').text()).toBe('2.0x')

    // 假播放器在 click 时就回调 onEnd(播完)
    await w.get('.voice__play').trigger('click')
    expect(w.get('[data-testid="voice-rate"]').text()).toBe('1.0x')
  })
})
