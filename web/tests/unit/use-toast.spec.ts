import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { useToast } from '@/composables/useToast'

describe('useToast', () => {
  beforeEach(() => vi.useFakeTimers())
  afterEach(() => vi.useRealTimers())

  it('show 之后 1.5 秒自动清空', () => {
    const toast = useToast()
    toast.show('已复制')
    expect(toast.text.value).toBe('已复制')
    vi.advanceTimersByTime(1500)
    expect(toast.text.value).toBe('')
  })

  it('连续 show 会重置计时，不会提前消失', () => {
    const toast = useToast()
    toast.show('第一条')
    vi.advanceTimersByTime(1000)
    toast.show('第二条')
    vi.advanceTimersByTime(1000)
    expect(toast.text.value).toBe('第二条')
    vi.advanceTimersByTime(500)
    expect(toast.text.value).toBe('')
  })

  it('clear 立即清空', () => {
    const toast = useToast()
    toast.show('x')
    toast.clear()
    expect(toast.text.value).toBe('')
  })
})
