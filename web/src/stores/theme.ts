import { defineStore } from 'pinia'
import { ref } from 'vue'

/**
 * 外观模式(计划 F-3):跟随系统 / 浅色 / 深色。
 *
 * 实现方式:`<html data-theme="dark|light">` + `tokens.css` 的 `[data-theme='dark']`
 * 覆盖块。页面与组件零改动,因为它们一直只用 CSS 变量取色。
 *
 * 为什么持久化在 localStorage 而不是后端:外观是纯客户端偏好,与账号无关;
 * 未登录的登录页也要能跟随系统,放后端反而要等首屏请求。
 */
export type ThemeMode = 'system' | 'light' | 'dark'

/** 持久化 key;与 App 侧 shared_preferences 的 key 同名(两端口径一致,便于排查)。 */
export const THEME_MODE_KEY = 'theme_mode'

const MODES: readonly ThemeMode[] = ['system', 'light', 'dark']

/** 读本地存的外观模式;非法值(手改 localStorage / 老版本残留)一律回落 system。 */
export function loadThemeMode(): ThemeMode {
  try {
    const raw = localStorage.getItem(THEME_MODE_KEY)
    if (raw && (MODES as readonly string[]).includes(raw)) return raw as ThemeMode
  } catch {
    // 隐私模式下 localStorage 可能抛异常,外观不值得因此挂掉整站
  }
  return 'system'
}

/** 写本地存的外观模式。 */
export function saveThemeMode(mode: ThemeMode): void {
  try {
    localStorage.setItem(THEME_MODE_KEY, mode)
  } catch {
    // 同上:写失败只影响下次启动的记忆,不影响本次切换
  }
}

/** 系统是否偏好深色。jsdom / 老浏览器没有 matchMedia 时按浅色处理。 */
export function systemPrefersDark(): boolean {
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return false
  return window.matchMedia('(prefers-color-scheme: dark)').matches
}

/** 模式 → 实际生效的明暗(system 需要问一次系统)。 */
export function resolveTheme(mode: ThemeMode): 'light' | 'dark' {
  if (mode === 'dark') return 'dark'
  if (mode === 'light') return 'light'
  return systemPrefersDark() ? 'dark' : 'light'
}

/**
 * 把生效明暗写到 `<html data-theme>`。
 *
 * 在 `main.ts` 挂载前也调一次(见 `applyStoredTheme`),避免深色用户首屏闪一下白。
 */
export function applyTheme(mode: ThemeMode): 'light' | 'dark' {
  const resolved = resolveTheme(mode)
  if (typeof document !== 'undefined') {
    document.documentElement.dataset.theme = resolved
  }
  return resolved
}

/** 启动即应用(不需要 pinia 实例,供 main.ts 在 createApp 之前调用)。 */
export function applyStoredTheme(): ThemeMode {
  const mode = loadThemeMode()
  applyTheme(mode)
  return mode
}

export const useThemeStore = defineStore('theme', () => {
  /** 用户选择的模式。 */
  const mode = ref<ThemeMode>(loadThemeMode())
  /** 实际生效的明暗(system 模式下会随系统变化)。 */
  const resolved = ref<'light' | 'dark'>(applyTheme(mode.value))

  /** 重新计算并应用(系统偏好变化时调用)。 */
  function refresh(): void {
    resolved.value = applyTheme(mode.value)
  }

  /** 切换模式:写 localStorage + 立即生效。 */
  function setMode(next: ThemeMode): void {
    mode.value = next
    saveThemeMode(next)
    refresh()
  }

  return { mode, resolved, refresh, setMode }
})
