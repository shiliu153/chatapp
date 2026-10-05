import { describe, expect, it } from 'vitest'
import { isMobileDevice } from '@/composables/useDevice'

function fakeNavigator(platform: string, userAgent: string, maxTouchPoints = 0) {
  Object.defineProperty(window, 'navigator', {
    configurable: true,
    value: { platform, userAgent, maxTouchPoints },
  })
}

describe('isMobileDevice', () => {
  it('iPhone 判为移动端', () => {
    fakeNavigator('iPhone', 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)')
    expect(isMobileDevice()).toBe(true)
  })

  it('Android 判为移动端(platform 报的是 Linux armv8l,只能靠 UA)', () => {
    fakeNavigator('Linux armv8l', 'Mozilla/5.0 (Linux; Android 14; Pixel 8)')
    expect(isMobileDevice()).toBe(true)
  })

  it('Windows 桌面判为桌面端', () => {
    fakeNavigator('Win32', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/140.0')
    expect(isMobileDevice()).toBe(false)
  })

  it('iPad 伪装成 Mac(多点触控)仍判为移动端', () => {
    fakeNavigator('MacIntel', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 5)
    expect(isMobileDevice()).toBe(true)
  })

  it('真 Mac 判为桌面端', () => {
    fakeNavigator('MacIntel', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)', 0)
    expect(isMobileDevice()).toBe(false)
  })

  it('窗口很窄也不影响判定(不是像素断点)', () => {
    fakeNavigator('Win32', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 500 })
    expect(isMobileDevice()).toBe(false)
  })

  it('Linux 桌面判为桌面端', () => {
    fakeNavigator('Linux x86_64', 'Mozilla/5.0 (X11; Linux x86_64) Firefox/130.0')
    expect(isMobileDevice()).toBe(false)
  })

  it('platform 不可靠但 UA 是 iPhone 时仍判为移动端(内嵌 WebView / UA 覆写)', () => {
    fakeNavigator('Win32', 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X)')
    expect(isMobileDevice()).toBe(true)
  })

  it('platform 不可靠但 UA 是 iPad 时仍判为移动端', () => {
    fakeNavigator('Win32', 'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X)')
    expect(isMobileDevice()).toBe(true)
  })

  it('真 Mac 的 UA 不含 iPhone/iPad,不受宽松判定影响', () => {
    fakeNavigator('MacIntel', 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15', 0)
    expect(isMobileDevice()).toBe(false)
  })
})
