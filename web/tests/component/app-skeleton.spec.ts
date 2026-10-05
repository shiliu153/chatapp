import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppSkeleton from '@/components/AppSkeleton.vue'

describe('AppSkeleton', () => {
  it('应用传入的宽高', () => {
    const w = mount(AppSkeleton, { props: { width: '120px', height: '24px' } })
    expect(w.attributes('style')).toContain('120px')
    expect(w.attributes('style')).toContain('24px')
  })

  it('默认铺满宽度、高 16px', () => {
    const w = mount(AppSkeleton)
    expect(w.attributes('style')).toContain('100%')
    expect(w.attributes('style')).toContain('16px')
  })

  it('对读屏软件隐藏(纯装饰)', () => {
    expect(mount(AppSkeleton).attributes('aria-hidden')).toBe('true')
  })
})
