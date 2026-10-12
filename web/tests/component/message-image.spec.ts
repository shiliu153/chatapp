import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import MessageImage from '@/features/chat/MessageImage.vue'
import { ChatMessageKind, type ChatMessage } from '@/im/types'

const message = (overrides: Partial<ChatMessage> = {}): ChatMessage => ({
  msgId: 'm1',
  peerId: 'u9',
  isSelf: true,
  timestamp: 1_700_000_000_000,
  kind: ChatMessageKind.image,
  text: '',
  senderName: '我',
  senderAvatar: null,
  isPending: false,
  isFailed: false,
  imageUrl: 'https://cdn/thumb.jpg',
  imageLargeUrl: 'https://cdn/large.jpg',
  ...overrides,
})

describe('MessageImage', () => {
  beforeEach(() => {
    // jsdom 没有实现 createObjectURL / revokeObjectURL
    vi.stubGlobal('URL', {
      ...URL,
      createObjectURL: vi.fn(() => 'blob:local-preview'),
      revokeObjectURL: vi.fn(),
    })
  })
  afterEach(() => vi.unstubAllGlobals())

  it('优先用原图(点开看大图才是原图)', () => {
    const w = mount(MessageImage, { props: { message: message() } })
    expect(w.find('.message-image__img').attributes('src')).toBe('https://cdn/large.jpg')
  })

  it('没有原图时退回缩略图', () => {
    const w = mount(MessageImage, { props: { message: message({ imageLargeUrl: null }) } })
    expect(w.find('.message-image__img').attributes('src')).toBe('https://cdn/thumb.jpg')
  })

  it('URL 都没有时显示占位块(不是破图)', () => {
    const w = mount(MessageImage, {
      props: { message: message({ imageUrl: null, imageLargeUrl: null }) },
    })
    expect(w.find('.message-image__placeholder').exists()).toBe(true)
    expect(w.find('.message-image__img').exists()).toBe(false)
  })

  it('发送中先用本地 blob 预览,不用空 URL', () => {
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    const w = mount(MessageImage, {
      props: { message: message({ isPending: true, imageUrl: null, imageLargeUrl: null }), localFile: file },
    })

    expect(w.find('.message-image__img').attributes('src')).toBe('blob:local-preview')
    expect(w.classes()).toContain('message-image--pending')
  })

  it('发送成功后换成服务端 URL 并回收 blob(防内存泄漏)', async () => {
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    const w = mount(MessageImage, {
      props: { message: message({ isPending: true, imageUrl: null, imageLargeUrl: null }), localFile: file },
    })
    expect(URL.revokeObjectURL).not.toHaveBeenCalled()

    await w.setProps({
      message: message({ isPending: false, imageUrl: 'https://cdn/done.jpg', imageLargeUrl: null }),
    })

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:local-preview')
    expect(w.find('.message-image__img').attributes('src')).toBe('https://cdn/done.jpg')
  })

  it('图片加载失败时显示兜底文案', async () => {
    const w = mount(MessageImage, { props: { message: message() } })
    await w.find('.message-image__img').trigger('error')

    expect(w.find('.message-image__fallback').text()).toBe('图片加载失败')
    expect(w.find('.message-image__img').exists()).toBe(false)
  })

  it('点图派发 open(交给灯箱)', async () => {
    const w = mount(MessageImage, { props: { message: message() } })
    await w.find('.message-image__img').trigger('click')

    expect(w.emitted('open')).toHaveLength(1)
  })

  it('卸载时回收 blob', () => {
    const file = new File(['x'], 'a.png', { type: 'image/png' })
    const w = mount(MessageImage, {
      props: { message: message({ isPending: true, imageUrl: null, imageLargeUrl: null }), localFile: file },
    })
    w.unmount()

    expect(URL.revokeObjectURL).toHaveBeenCalledWith('blob:local-preview')
  })
})
