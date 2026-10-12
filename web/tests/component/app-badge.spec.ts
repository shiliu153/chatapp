import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppBadge from '@/components/AppBadge.vue'

describe('AppBadge', () => {
  it('未读为 0 时不渲染', () => {
    expect(mount(AppBadge, { props: { count: 0 } }).find('.app-badge').exists()).toBe(false)
  })

  it('负数也不渲染', () => {
    expect(mount(AppBadge, { props: { count: -1 } }).find('.app-badge').exists()).toBe(false)
  })

  it('正常数字直接展示', () => {
    expect(mount(AppBadge, { props: { count: 3 } }).text()).toBe('3')
  })

  it('超过上限显示 99+', () => {
    expect(mount(AppBadge, { props: { count: 120 } }).text()).toBe('99+')
  })

  it('恰好等于上限时显示原数字', () => {
    expect(mount(AppBadge, { props: { count: 99 } }).text()).toBe('99')
  })
})
