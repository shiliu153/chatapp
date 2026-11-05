import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import {
  THEME_MODE_KEY,
  applyStoredTheme,
  applyTheme,
  loadThemeMode,
  resolveTheme,
  useThemeStore,
} from '@/stores/theme'

/** 让 matchMedia 报出指定的系统明暗(jsdom 默认没有实现)。 */
function mockSystemDark(dark: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: query.includes('dark') ? dark : false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
  }))
}

describe('外观 store(F-3)', () => {
  beforeEach(() => {
    localStorage.clear()
    document.documentElement.removeAttribute('data-theme')
    setActivePinia(createPinia())
    mockSystemDark(false)
  })

  it('默认跟随系统', () => {
    expect(loadThemeMode()).toBe('system')
    expect(useThemeStore().mode).toBe('system')
  })

  it('非法的本地值回落 system(手改 localStorage 不至于白屏)', () => {
    localStorage.setItem(THEME_MODE_KEY, 'purple')
    expect(loadThemeMode()).toBe('system')
  })

  it('resolveTheme:显式模式不看系统,system 看系统', () => {
    expect(resolveTheme('light')).toBe('light')
    expect(resolveTheme('dark')).toBe('dark')
    expect(resolveTheme('system')).toBe('light')
    mockSystemDark(true)
    expect(resolveTheme('system')).toBe('dark')
  })

  it('setMode 立即生效、写 localStorage,并写 <html data-theme>', () => {
    const store = useThemeStore()
    store.setMode('dark')
    expect(store.resolved).toBe('dark')
    expect(localStorage.getItem(THEME_MODE_KEY)).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')

    store.setMode('light')
    expect(store.resolved).toBe('light')
    expect(document.documentElement.dataset.theme).toBe('light')
  })

  it('refresh:system 模式下跟随系统明暗变化', () => {
    const store = useThemeStore()
    store.setMode('system')
    expect(store.resolved).toBe('light')
    mockSystemDark(true)
    store.refresh()
    expect(store.resolved).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('applyStoredTheme:启动时按存下来的模式写 dataset(首屏不闪白)', () => {
    localStorage.setItem(THEME_MODE_KEY, 'dark')
    expect(applyStoredTheme()).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')
  })

  it('applyTheme 在 matchMedia 缺失时按浅色处理(老浏览器兜底)', () => {
    vi.stubGlobal('matchMedia', undefined)
    expect(applyTheme('system')).toBe('light')
  })
})
