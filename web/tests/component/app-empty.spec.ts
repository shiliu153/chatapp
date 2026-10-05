import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppEmpty from '@/components/AppEmpty.vue'

describe('AppEmpty', () => {
  it('展示大号 emoji、标题与副文案', () => {
    const w = mount(AppEmpty, { props: { title: '附近还没有人', description: '换个筛选条件试试' } })
    expect(w.find('.app-empty__emoji').text()).toBe('💫')
    expect(w.text()).toContain('附近还没有人')
    expect(w.text()).toContain('换个筛选条件试试')
  })

  it('可以自定义 emoji', () => {
    const w = mount(AppEmpty, { props: { emoji: '🫧', title: '滑完了' } })
    expect(w.find('.app-empty__emoji').text()).toBe('🫧')
  })

  it('没有副文案时不渲染那一段', () => {
    const w = mount(AppEmpty, { props: { title: '空' } })
    expect(w.find('.app-empty__desc').exists()).toBe(false)
  })
})
