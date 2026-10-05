import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ImageViewer from '@/features/chat/ImageViewer.vue'

describe('ImageViewer', () => {
  it('渲染当前图片', () => {
    const w = mount(ImageViewer, {
      props: { urls: ['https://cos/a.jpg', 'https://cos/b.jpg'], index: 1 },
    })
    expect(w.find('.image-viewer__img').attributes('src')).toBe('https://cos/b.jpg')
  })

  it('点遮罩关闭', async () => {
    const w = mount(ImageViewer, { props: { urls: ['https://cos/a.jpg'], index: 0 } })
    await w.find('.image-viewer__mask').trigger('click')
    expect(w.emitted('close')).toHaveLength(1)
  })

  it('按 Esc 关闭', async () => {
    const w = mount(ImageViewer, {
      props: { urls: ['https://cos/a.jpg'], index: 0 },
      attachTo: document.body,
    })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(w.emitted('close')).toHaveLength(1)
    w.unmount()
  })

  it('点图片本身不关闭(避免手滑)', async () => {
    const w = mount(ImageViewer, { props: { urls: ['https://cos/a.jpg'], index: 0 } })
    await w.find('.image-viewer__img').trigger('click')
    expect(w.emitted('close')).toBeUndefined()
  })
})
