import { describe, expect, it } from 'vitest'
import { SWIPE_THRESHOLD, swipeDirection } from '@/features/discovery/swipe'

describe('swipeDirection', () => {
  it('未超过阈值不判定', () => {
    expect(swipeDirection(0)).toBeNull()
    expect(swipeDirection(SWIPE_THRESHOLD - 1)).toBeNull()
    expect(swipeDirection(-(SWIPE_THRESHOLD - 1))).toBeNull()
  })

  it('右滑是喜欢,左滑是跳过', () => {
    expect(swipeDirection(SWIPE_THRESHOLD)).toBe('like')
    expect(swipeDirection(400)).toBe('like')
    expect(swipeDirection(-SWIPE_THRESHOLD)).toBe('pass')
    expect(swipeDirection(-400)).toBe('pass')
  })
})
