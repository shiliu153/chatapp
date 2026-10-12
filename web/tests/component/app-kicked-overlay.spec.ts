import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppKickedOverlay from '@/components/AppKickedOverlay.vue'
import { useSessionStore } from '@/stores/session'
import { freshPinia } from '../support/pinia'

function mountOverlay() {
  const pinia = freshPinia()
  const store = useSessionStore()
  const w = mount(AppKickedOverlay, { global: { plugins: [pinia] } })
  return { w, store }
}

describe('AppKickedOverlay', () => {
  it('未被顶号时不渲染', () => {
    expect(mountOverlay().w.find('.kicked-overlay').exists()).toBe(false)
  })

  it('被顶号时展示全屏提示与重新登录按钮', async () => {
    const { w, store } = mountOverlay()
    store.kicked = true
    await w.vm.$nextTick()

    expect(w.find('.kicked-overlay').exists()).toBe(true)
    expect(w.text()).toContain('账号已在其他设备登录')

    await w.find('button').trigger('click')
    expect(store.kicked).toBe(false)
  })

  it('是模态对话框(读屏能识别)', async () => {
    const { w, store } = mountOverlay()
    store.kicked = true
    await w.vm.$nextTick()
    expect(w.find('[role="alertdialog"]').exists()).toBe(true)
  })
})
