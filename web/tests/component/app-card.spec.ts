import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppCard from '@/components/AppCard.vue'

describe('AppCard', () => {
  it('渲染插入内容', () => {
    const w = mount(AppCard, { slots: { default: '<p>资料卡</p>' } })
    expect(w.find('p').text()).toBe('资料卡')
  })

  it('hoverable 时带悬停类(Web 新增维度)', () => {
    expect(mount(AppCard, { props: { hoverable: true } }).classes()).toContain(
      'app-card--hoverable',
    )
  })

  it('padding 变体带对应类', () => {
    expect(mount(AppCard).classes()).toContain('app-card--md')
    expect(mount(AppCard, { props: { padding: 'lg' } }).classes()).toContain('app-card--lg')
  })
})
