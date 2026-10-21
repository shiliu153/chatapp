import { describe, expect, it } from 'vitest'
import { isOutdated } from '@/features/app/version'

describe('isOutdated', () => {
  it('按三段数字比较', () => {
    expect(isOutdated('1.0.0', '1.1.0')).toBe(true)
    expect(isOutdated('1.1.0', '1.1.0')).toBe(false)
    expect(isOutdated('1.10.0', '1.2.0')).toBe(false)
    expect(isOutdated('2.0', '1.9.9')).toBe(false)
  })
})
