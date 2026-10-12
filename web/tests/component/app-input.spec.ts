import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppInput from '@/components/AppInput.vue'

describe('AppInput', () => {
  it('输入时向父组件同步值', async () => {
    const w = mount(AppInput, { props: { modelValue: '' } })
    await w.find('input').setValue('13800000001')
    expect(w.emitted('update:modelValue')?.[0]).toEqual(['13800000001'])
  })

  it('回车时派发 enter 事件', async () => {
    const w = mount(AppInput, { props: { modelValue: 'x' } })
    await w.find('input').trigger('keyup.enter')
    expect(w.emitted('enter')).toHaveLength(1)
  })

  it('error 文案可见且带上错误态类', () => {
    const w = mount(AppInput, { props: { modelValue: '', error: '验证码错误' } })
    expect(w.text()).toContain('验证码错误')
    expect(w.classes()).toContain('app-input--error')
  })

  it('disabled 时输入框不可编辑', () => {
    const w = mount(AppInput, { props: { modelValue: '', disabled: true } })
    expect(w.find('input').attributes('disabled')).toBeDefined()
  })

  it('inputmode 落在真正的 input 上(不是外层容器)', () => {
    const w = mount(AppInput, { props: { modelValue: '', inputmode: 'numeric' } })
    expect(w.find('input').attributes('inputmode')).toBe('numeric')
  })
})
