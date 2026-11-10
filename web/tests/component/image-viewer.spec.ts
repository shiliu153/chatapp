import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ImageViewer from '@/features/chat/ImageViewer.vue'

const A = 'https://cos/a.jpg'
const B = 'https://cos/b.jpg'
const C = 'https://cos/c.jpg'

/** 取图片当前的 CSS transform(jsdom 里 style 对象就是真值) */
function transformOf(wrapper: ReturnType<typeof mount>): string {
  return (wrapper.find('.image-viewer__img').element as HTMLElement).style.transform
}

describe('ImageViewer', () => {
  it('渲染当前图片', () => {
    const w = mount(ImageViewer, {
      props: { urls: [A, B], index: 1 },
    })
    expect(w.find('.image-viewer__img').attributes('src')).toBe(B)
  })

  it('点遮罩关闭', async () => {
    const w = mount(ImageViewer, { props: { urls: [A], index: 0 } })
    await w.find('.image-viewer__mask').trigger('click')
    expect(w.emitted('close')).toHaveLength(1)
  })

  it('按 Esc 关闭', async () => {
    const w = mount(ImageViewer, {
      props: { urls: [A], index: 0 },
      attachTo: document.body,
    })
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(w.emitted('close')).toHaveLength(1)
    w.unmount()
  })

  it('点图片本身不关闭(避免手滑)', async () => {
    const w = mount(ImageViewer, { props: { urls: [A], index: 0 } })
    await w.find('.image-viewer__img').trigger('click')
    expect(w.emitted('close')).toBeUndefined()
  })

  // --- 页码(批次 T)---

  it('多张时显示页码 i / n,单张不显示', () => {
    const multi = mount(ImageViewer, { props: { urls: [A, B, C], index: 1 } })
    expect(multi.get('[data-testid="viewer-page"]').text().replace(/\s+/g, ' ')).toBe('2 / 3')

    const single = mount(ImageViewer, { props: { urls: [A], index: 0 } })
    expect(single.find('[data-testid="viewer-page"]').exists()).toBe(false)
    // 单张也没有左右按钮
    expect(single.find('[data-testid="viewer-prev"]').exists()).toBe(false)
    expect(single.find('[data-testid="viewer-next"]').exists()).toBe(false)
  })

  // --- 左右切(批次 T)---

  it('点左右按钮切图,页码跟着走;到头不动', async () => {
    const w = mount(ImageViewer, { props: { urls: [A, B], index: 0 } })

    await w.get('[data-testid="viewer-next"]').trigger('click')
    expect(w.find('.image-viewer__img').attributes('src')).toBe(B)
    expect(w.get('[data-testid="viewer-page"]').text().replace(/\s+/g, ' ')).toBe('2 / 2')

    // 已经是最后一张:再点不动
    await w.get('[data-testid="viewer-next"]').trigger('click')
    expect(w.find('.image-viewer__img').attributes('src')).toBe(B)

    await w.get('[data-testid="viewer-prev"]').trigger('click')
    expect(w.find('.image-viewer__img').attributes('src')).toBe(A)

    // 第一张再往前也不动
    await w.get('[data-testid="viewer-prev"]').trigger('click')
    expect(w.find('.image-viewer__img').attributes('src')).toBe(A)
  })

  it('方向键 ← / → 切图', async () => {
    const w = mount(ImageViewer, { props: { urls: [A, B, C], index: 0 }, attachTo: document.body })

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    await w.vm.$nextTick()
    expect(w.find('.image-viewer__img').attributes('src')).toBe(B)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    await w.vm.$nextTick()
    expect(w.find('.image-viewer__img').attributes('src')).toBe(C)

    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
    await w.vm.$nextTick()
    expect(w.find('.image-viewer__img').attributes('src')).toBe(B)
    w.unmount()
  })

  // --- 缩放(批次 T)---

  it('滚轮放大 / 缩小,最大 4x、最小 1x', async () => {
    const w = mount(ImageViewer, { props: { urls: [A, B], index: 0 } })
    const img = w.find('.image-viewer__img')
    expect(transformOf(w)).toBe('scale(1)')

    await img.trigger('wheel', { deltaY: -100 })
    expect(transformOf(w)).toBe('scale(1.25)')

    await img.trigger('wheel', { deltaY: 100 })
    expect(transformOf(w)).toBe('scale(1)')

    // 往小里滚不会小于 1(再小就只是「留白变多」,没有意义)
    await img.trigger('wheel', { deltaY: 100 })
    expect(transformOf(w)).toBe('scale(1)')

    for (let i = 0; i < 20; i++) await img.trigger('wheel', { deltaY: -100 })
    expect(transformOf(w)).toBe('scale(4)')
  })

  it('双击在 1x / 2x 之间来回', async () => {
    const w = mount(ImageViewer, { props: { urls: [A], index: 0 } })
    const img = w.find('.image-viewer__img')

    await img.trigger('dblclick')
    expect(transformOf(w)).toBe('scale(2)')
    expect(img.classes()).toContain('image-viewer__img--zoomed')

    await img.trigger('dblclick')
    expect(transformOf(w)).toBe('scale(1)')
  })

  it('换一张图复位缩放(不把上一张的倍数带过去)', async () => {
    const w = mount(ImageViewer, { props: { urls: [A, B], index: 0 } })
    await w.find('.image-viewer__img').trigger('dblclick')
    expect(transformOf(w)).toBe('scale(2)')

    await w.get('[data-testid="viewer-next"]').trigger('click')
    expect(transformOf(w)).toBe('scale(1)')
  })

  it('外部换了起始下标:回到那一张并复位缩放', async () => {
    const w = mount(ImageViewer, { props: { urls: [A, B, C], index: 0 } })
    await w.find('.image-viewer__img').trigger('dblclick')

    await w.setProps({ index: 2 })
    expect(w.find('.image-viewer__img').attributes('src')).toBe(C)
    expect(transformOf(w)).toBe('scale(1)')
  })
})
