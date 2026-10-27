import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import MessageVoice from '@/features/chat/MessageVoice.vue'
import { ChatMessageKind, type ChatMessage } from '@/im/types'

const playVoice = vi.fn((_url: string, onEnd: () => void) => onEnd())
const stopVoice = vi.fn()

vi.mock('@/im/voicePlayer', () => ({
  playVoice: (url: string, onEnd: () => void) => playVoice(url, onEnd),
  stopVoice: () => stopVoice(),
}))

const message = (overrides: Partial<ChatMessage> = {}): ChatMessage => ({
  msgId: 'v1',
  peerId: 'u9',
  isSelf: false,
  seq: 1,
  timestamp: 1_700_000_000_000,
  kind: ChatMessageKind.voice,
  text: '',
  senderName: '小红',
  senderAvatar: null,
  isPending: false,
  isFailed: false,
  imageUrl: null,
  imageLargeUrl: null,
  voiceUrl: 'http://cdn/media/chat/voices/a.m4a',
  voiceDurationMs: 12500,
  isRevoked: false,
  ...overrides,
})

describe('MessageVoice', () => {
  it('显示秒数,点一下播放', async () => {
    const wrapper = mount(MessageVoice, { props: { message: message() } })
    expect(wrapper.text()).toContain('13″')

    await wrapper.get('button').trigger('click')
    expect(playVoice).toHaveBeenCalledWith(
      'http://cdn/media/chat/voices/a.m4a',
      expect.any(Function),
    )
    // 假播放器立即回调 onEnd,图标回到播放态
    expect(wrapper.text()).toContain('▶')
  })

  it('没有 URL 时点击不播放', async () => {
    playVoice.mockClear()
    const wrapper = mount(MessageVoice, { props: { message: message({ voiceUrl: null }) } })
    await wrapper.get('button').trigger('click')
    expect(playVoice).not.toHaveBeenCalled()
  })
})
