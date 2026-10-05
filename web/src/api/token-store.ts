/** 令牌与账号 id 的本地存储(与 App 的 SharedPreferences 语义一致,Web 落在 localStorage)。 */
const ACCESS_KEY = 'hb.access'
const REFRESH_KEY = 'hb.refresh'
const USER_ID_KEY = 'hb.userId'

export const tokenStore = {
  get access(): string | null {
    return localStorage.getItem(ACCESS_KEY)
  },
  set access(value: string | null) {
    if (value === null) localStorage.removeItem(ACCESS_KEY)
    else localStorage.setItem(ACCESS_KEY, value)
  },

  get refresh(): string | null {
    return localStorage.getItem(REFRESH_KEY)
  },
  set refresh(value: string | null) {
    if (value === null) localStorage.removeItem(REFRESH_KEY)
    else localStorage.setItem(REFRESH_KEY, value)
  },

  get userId(): number | null {
    const raw = localStorage.getItem(USER_ID_KEY)
    if (raw === null) return null
    const parsed = Number(raw)
    return Number.isNaN(parsed) ? null : parsed
  },
  set userId(value: number | null) {
    if (value === null) localStorage.removeItem(USER_ID_KEY)
    else localStorage.setItem(USER_ID_KEY, String(value))
  },

  clear(): void {
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
    localStorage.removeItem(USER_ID_KEY)
  },
}
