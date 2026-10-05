import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppButton from '@/components/AppButton.vue'

describe('AppButton', () => {
  it('渲染默认插槽文字并采用 primary 主按钮样式', () => {
    const w = mount(AppButton, { slots: { default: '开始' } })
    expect(w.text()).toBe('开始')
    expect(w.classes()).toContain('app-button--primary')
    expect(w.attributes('disabled')).toBeUndefined()
  })

  it('disabled 时不派发 click', async () => {
    const w = mount(AppButton, { props: { disabled: true }, slots: { default: '开始' } })
    await w.trigger('click')
    expect(w.emitted('click')).toBeUndefined()
  })

  it('loading 时阻止点击并展示加载态', async () => {
    const w = mount(AppButton, { props: { loading: true }, slots: { default: '登录' } })
    expect(w.find('.app-button__spinner').exists()).toBe(true)
    await w.trigger('click')
    expect(w.emitted('click')).toBeUndefined()
  })

  it('ghost 与 danger 走各自变体类', () => {
    expect(mount(AppButton, { props: { variant: 'ghost' } }).classes()).toContain('app-button--ghost')
    expect(mount(AppButton, { props: { variant: 'danger' } }).classes()).toContain(
      'app-button--danger',
    )
  })
})
