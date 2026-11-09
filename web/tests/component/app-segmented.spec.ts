import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import AppSegmented from '@/components/AppSegmented.vue'

const OPTIONS = [
  { value: 'week' as const, label: '周' },
  { value: 'month' as const, label: '月' },
  { value: 'year' as const, label: '年' },
]

function mountSegmented(modelValue: 'week' | 'month' | 'year' = 'week') {
  return mount(AppSegmented, { props: { options: OPTIONS, modelValue, label: '统计周期' } })
}

describe('AppSegmented', () => {
  it('渲染全部选项,选中项只靠 aria-pressed 表达', () => {
    const w = mountSegmented('month')
    const segments = w.findAll('.app-segmented__segment')

    expect(segments.map((node) => node.text())).toEqual(['周', '月', '年'])
    expect(segments.map((node) => node.attributes('aria-pressed'))).toEqual([
      'false',
      'true',
      'false',
    ])
    expect(w.find('.app-segmented').attributes('role')).toBe('group')
    expect(w.find('.app-segmented').attributes('aria-label')).toBe('统计周期')
  })

  it('点未选中的项发 update:modelValue', async () => {
    const w = mountSegmented('week')

    await w.findAll('.app-segmented__segment')[2].trigger('click')

    expect(w.emitted('update:modelValue')).toEqual([['year']])
  })

  it('点已选中的项不发事件(避免父组件重复请求)', async () => {
    const w = mountSegmented('week')

    await w.findAll('.app-segmented__segment')[0].trigger('click')

    expect(w.emitted('update:modelValue')).toBeUndefined()
  })
})
