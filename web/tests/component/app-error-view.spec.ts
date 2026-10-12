import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppErrorView from '@/components/AppErrorView.vue'

describe('AppErrorView', () => {
  it('展示文案并可重试', async () => {
    const w = mount(AppErrorView, { props: { message: '网络开小差了' } })
    expect(w.text()).toContain('网络开小差了')
    await w.find('button').trigger('click')
    expect(w.emitted('retry')).toHaveLength(1)
  })

  it('默认文案与按钮文案', () => {
    const w = mount(AppErrorView)
    expect(w.text()).toContain('出了点问题')
    expect(w.text()).toContain('重试')
  })

  it('可自定义重试按钮文案', () => {
    const w = mount(AppErrorView, { props: { retryLabel: '重新加载' } })
    expect(w.text()).toContain('重新加载')
  })
})
