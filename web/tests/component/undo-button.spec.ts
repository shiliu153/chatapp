import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import UndoButton from '@/features/discovery/UndoButton.vue'

/** 环的周长,与组件里的 `2πr`(r = 17)对齐 */
const CIRCUMFERENCE = 2 * Math.PI * 17

describe('UndoButton', () => {
  it('窗口内可点:派发 undo,并报出剩余秒数', async () => {
    const w = mount(UndoButton, { props: { secondsLeft: 18, progress: 0.6 } })

    expect(w.find('button').attributes('aria-label')).toContain('还剩 18 秒')
    expect(w.find('button').attributes('disabled')).toBeUndefined()

    await w.find('button').trigger('click')

    expect(w.emitted('undo')).toHaveLength(1)
  })

  it('倒计时归零后置灰,点了也不派发', async () => {
    const w = mount(UndoButton, { props: { secondsLeft: 0, progress: 0 } })

    expect(w.find('button').attributes('disabled')).toBeDefined()
    expect(w.find('button').attributes('aria-label')).toContain('已超过 30 秒')

    await w.find('button').trigger('click')

    expect(w.emitted('undo')).toBeUndefined()
  })

  it('请求进行中(busy)时防连点', async () => {
    const w = mount(UndoButton, { props: { secondsLeft: 20, progress: 0.7, busy: true } })

    expect(w.find('button').attributes('disabled')).toBeDefined()

    await w.find('button').trigger('click')

    expect(w.emitted('undo')).toBeUndefined()
  })

  it('环的长度跟着进度走:满窗整圈、过期空圈', () => {
    const full = mount(UndoButton, { props: { secondsLeft: 30, progress: 1 } })
    const expired = mount(UndoButton, { props: { secondsLeft: 0, progress: 0 } })

    const offsetOf = (w: ReturnType<typeof mount>): number =>
      Number(w.find('.undo-button__bar').attributes('stroke-dashoffset'))

    expect(offsetOf(full)).toBeCloseTo(0, 5)
    expect(offsetOf(expired)).toBeCloseTo(CIRCUMFERENCE, 5)
  })
})
