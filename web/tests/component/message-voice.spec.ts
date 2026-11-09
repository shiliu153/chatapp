import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MessageVoice from '@/features/chat/MessageVoice.vue'

const playVoice = vi.fn((_url: string, onEnd: () => void, _onError?: () => void) => onEnd())
const stopVoice = vi.fn()

vi.mock('@/im/voicePlayer', () => ({
  playVoice: (url: string, onEnd: () => void, onError?: () => void) =>
    playVoice(url, onEnd, onError),
  stopVoice: () => stopVoice(),
}))

const CHAT_URL = 'http://cdn/media/chat/voices/a.m4a'

describe('MessageVoice', () => {
  it('显示秒数,点一下播放', async () => {
    const w = mount(MessageVoice, { props: { url: CHAT_URL, durationMs: 12500 } })
    expect(w.text()).toContain('13″')

    await w.get('button').trigger('click')
    // 播完回调 + 失败回调都给到播放器(失败要有提示,见下面的用例)
    expect(playVoice).toHaveBeenCalledWith(CHAT_URL, expect.any(Function), expect.any(Function))
    // 假播放器立即回调 onEnd,图标回到播放态
    expect(w.text()).toContain('▶')
  })

  it('没有 URL 时点击不播放', async () => {
    playVoice.mockClear()
    const w = mount(MessageVoice, { props: { url: null, durationMs: 3000 } })
    await w.get('button').trigger('click')
    expect(playVoice).not.toHaveBeenCalled()
  })

  it('没有地址时渲染不可播放的占位(失败/发送中的气泡)', () => {
    const w = mount(MessageVoice, { props: { url: null, durationMs: 3000 } })
    expect(w.find('.voice--empty').exists()).toBe(true)
    expect(w.get('button').attributes('aria-disabled')).toBe('true')
    expect(w.text()).toContain('🎙')
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
    playVoice.mockImplementationOnce((_url: string, _onEnd: () => void, onError?: () => void) =>
      onError?.(),
    )
    const w = mount(MessageVoice, { props: { url: CHAT_URL, durationMs: 4000 } })

    await w.get('button').trigger('click')

    expect(w.text()).toContain('播放失败')
    expect(w.get('button').attributes('aria-label')).toBe('播放失败，点击重试')
    // 再点一次是重试,失败态先清掉
    await w.get('button').trigger('click')
    expect(w.text()).not.toContain('播放失败')
  })

  it('播放中再点一次是停止', async () => {
    // 模拟「正在播」:playVoice 不立即回调 onEnd
    playVoice.mockImplementationOnce(() => {})
    const w = mount(MessageVoice, { props: { url: CHAT_URL, durationMs: 4000 } })

    await w.get('button').trigger('click')
    expect(w.text()).toContain('❚❚')

    await w.get('button').trigger('click')
    expect(stopVoice).toHaveBeenCalled()
    expect(w.text()).toContain('▶')
  })
})
