import { beforeEach, describe, expect, it } from 'vitest'
import { tokenStore } from '@/api/token-store'

describe('tokenStore', () => {
  beforeEach(() => localStorage.clear())

  it('读写三件套', () => {
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
    tokenStore.userId = 42
    expect(tokenStore.access).toBe('a')
    expect(tokenStore.refresh).toBe('r')
    expect(tokenStore.userId).toBe(42)
  })

  it('清空后全部为 null', () => {
    tokenStore.access = 'a'
    tokenStore.refresh = 'r'
    tokenStore.userId = 42
    tokenStore.clear()
    expect(tokenStore.access).toBeNull()
    expect(tokenStore.refresh).toBeNull()
    expect(tokenStore.userId).toBeNull()
  })

  it('userId 存的是数字,读回来仍是数字', () => {
    tokenStore.userId = 7
    expect(localStorage.getItem('hb.userId')).toBe('7')
    expect(typeof tokenStore.userId).toBe('number')
  })

  it('userId 被写坏时读回 null 而不是 NaN', () => {
    localStorage.setItem('hb.userId', 'abc')
    expect(tokenStore.userId).toBeNull()
  })

  it('显式写 null 等于删除', () => {
    tokenStore.access = 'a'
    tokenStore.access = null
    expect(localStorage.getItem('hb.access')).toBeNull()
  })
})
