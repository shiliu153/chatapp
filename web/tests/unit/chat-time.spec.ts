import { describe, expect, it } from 'vitest'
import { formatTime, shouldShowTime } from '@/features/chat/time'

const MINUTE = 60_000

describe('shouldShowTime', () => {
  it('第一条消息总是显示时间', () => {
    expect(shouldShowTime(null, 1_700_000_000_000)).toBe(true)
  })

  it('间隔 5 分钟内不插时间条', () => {
    const t = 1_700_000_000_000
    expect(shouldShowTime(t, t + 4 * MINUTE)).toBe(false)
  })

  it('间隔正好 5 分钟不插(严格大于才插)', () => {
    const t = 1_700_000_000_000
    expect(shouldShowTime(t, t + 5 * MINUTE)).toBe(false)
  })

  it('超过 5 分钟插时间条', () => {
    const t = 1_700_000_000_000
    expect(shouldShowTime(t, t + 5 * MINUTE + 1)).toBe(true)
  })
})

describe('formatTime', () => {
  it('当天只显示时分', () => {
    const now = new Date('2026-10-05T20:30:00')
    expect(formatTime(new Date('2026-10-05T09:05:00').getTime(), now)).toBe('09:05')
  })

  it('非当天显示月日时分', () => {
    const now = new Date('2026-10-05T20:30:00')
    expect(formatTime(new Date('2026-10-04T09:05:00').getTime(), now)).toBe('10-04 09:05')
  })
})
