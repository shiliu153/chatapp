/**
 * 会话凭证的浏览器侧存储。
 *
 * 设计要点:
 * 1. **access 只放内存**:页面刷新即丢,重新进站时用 HttpOnly Cookie 换一个新的;
 *    这样即使出现 XSS,攻击者也拿不到「页面关掉后还能用」的长期凭证。
 * 2. **refresh 不在 JS 里**:后端通过 `Set-Cookie` 下发(`HttpOnly; SameSite=Strict`),
 *    脚本读不到,只能由浏览器在请求刷新接口时自动携带。
 * 3. **userId 留在 localStorage**:它不是秘密,首屏用它决定要不要显示「上次登录」相关状态。
 *
 * 关联文档:
 * - 设计:docs/superpowers/specs/2026-10-28-token-hardening-design.md
 * - 接口契约:docs/api/auth.md
 */
const USER_ID_KEY = 'hb.userId'

/** 旧版本把两个令牌写在这里,升级后首启清掉,避免遗留的长期凭证继续躺在磁盘上。 */
const LEGACY_KEYS = ['hb.access', 'hb.refresh']

let accessToken: string | null = null

/** 清掉旧版本遗留的 localStorage 令牌(幂等)。 */
function dropLegacyTokens(): void {
  for (const key of LEGACY_KEYS) localStorage.removeItem(key)
}

dropLegacyTokens()

export const tokenStore = {
  get access(): string | null {
    return accessToken
  },
  set access(value: string | null) {
    accessToken = value
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
    accessToken = null
    localStorage.removeItem(USER_ID_KEY)
    dropLegacyTokens()
  },
}
