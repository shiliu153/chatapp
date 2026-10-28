import { beforeEach, describe, expect, it } from 'vitest'
import { tokenStore } from '@/api/token-store'

describe('tokenStore', () => {
  beforeEach(() => localStorage.clear())

  it('access 只存内存,不写 localStorage', () => {
    tokenStore.access = 'a'
    expect(tokenStore.access).toBe('a')
    expect(localStorage.getItem('hb.access')).toBeNull()
  })

  it('userId 存 localStorage,读回来是数字', () => {
    tokenStore.userId = 7
    expect(localStorage.getItem('hb.userId')).toBe('7')
    expect(typeof tokenStore.userId).toBe('number')
  })

  it('userId 被写坏时读回 null 而不是 NaN', () => {
    localStorage.setItem('hb.userId', 'abc')
    expect(tokenStore.userId).toBeNull()
  })

  it('clear 清掉内存 access 与 userId', () => {
    tokenStore.access = 'a'
    tokenStore.userId = 42
    tokenStore.clear()
    expect(tokenStore.access).toBeNull()
    expect(tokenStore.userId).toBeNull()
  })

  it('升级后清掉旧版本遗留的 access/refresh', () => {
    localStorage.setItem('hb.access', 'old-access')
    localStorage.setItem('hb.refresh', 'old-refresh')

    tokenStore.clear()

    expect(localStorage.getItem('hb.access')).toBeNull()
    expect(localStorage.getItem('hb.refresh')).toBeNull()
  })
})
