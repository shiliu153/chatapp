import { beforeEach, describe, expect, it } from 'vitest'
import { layout, useSidebar } from '@/layout'

function setViewport(width: number) {
  Object.defineProperty(window, 'innerWidth', { configurable: true, value: width })
}

describe('useSidebar', () => {
  beforeEach(() => localStorage.clear())

  it('默认宽度 = 窗口宽 × 16%,并夹在 208–264', () => {
    setViewport(1280)
    expect(useSidebar().width.value).toBe(208) // 1280 * 0.16 = 204.8 → 夹到 208
    setViewport(1920)
    expect(useSidebar().width.value).toBe(264) // 307.2 → 夹到 264
    setViewport(1500)
    expect(useSidebar().width.value).toBe(240) // 240 落在区间内
  })

  it('宽度低于阈值时切图标态', () => {
    setViewport(1280)
    const s = useSidebar()
    s.setWidthForTest(layout.sidebar.iconThreshold - 1)
    expect(s.isIconOnly.value).toBe(true)
    s.setWidthForTest(layout.sidebar.iconThreshold)
    expect(s.isIconOnly.value).toBe(false)
  })

  it('拖拽被夹在 72–360', () => {
    setViewport(1280)
    const s = useSidebar()
    s.setWidthForTest(10)
    expect(s.width.value).toBe(layout.sidebar.dragMin)
    s.setWidthForTest(9999)
    expect(s.width.value).toBe(layout.sidebar.dragMax)
  })

  it('宽度写入 localStorage,重新创建时沿用', () => {
    setViewport(1280)
    useSidebar().setWidthForTest(300)
    expect(localStorage.getItem('hb.sidebarWidth')).toBe('300')
    expect(useSidebar().width.value).toBe(300)
  })

  it('双击复位到默认宽度', () => {
    setViewport(1280)
    const s = useSidebar()
    s.setWidthForTest(320)
    s.resetToDefault()
    expect(s.width.value).toBe(208)
  })

  it('记忆的值被写坏时回落到默认宽度', () => {
    setViewport(1280)
    localStorage.setItem('hb.sidebarWidth', 'abc')
    expect(useSidebar().width.value).toBe(208)
  })

  it('拖拽过程中随指针移动更新宽度', () => {
    setViewport(1280)
    const s = useSidebar() // 起始 208
    s.beginDrag({ clientX: 200, preventDefault: () => {} } as unknown as PointerEvent)

    window.dispatchEvent(new PointerEvent('pointermove', { clientX: 260 }))
    expect(s.width.value).toBe(268) // 208 + 60

    window.dispatchEvent(new PointerEvent('pointerup'))
    expect(s.isDragging.value).toBe(false)
  })
})
