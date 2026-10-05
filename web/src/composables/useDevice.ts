/**
 * 是否移动端浏览器。
 * 判据与 Flutter 的 ui_web.browser 一致:platform + UA + maxTouchPoints,
 * **不使用窗口宽度**(spec §6.1:窗口拖窄仍是 PC 壳层)。
 *
 * platform 与 UA 都看:真实 iPhone 的 platform 是 "iPhone",但内嵌 WebView、
 * 或被冻结/伪造 platform 的场景下 platform 可能是 "Win32" 之类,此时靠 UA 兜住。
 */
export function isMobileDevice(): boolean {
  if (typeof navigator === 'undefined') return false

  const platform = navigator.platform ?? ''
  const userAgent = navigator.userAgent ?? ''
  const maxTouchPoints = navigator.maxTouchPoints ?? 0

  const uaLooksAppleMobile = /iphone|ipad|ipod/i.test(userAgent)

  // iPad 请求「桌面版网站」时 platform 会是 MacIntel,靠多点触控或 UA 识别
  if (platform.startsWith('Mac')) return maxTouchPoints > 2 || uaLooksAppleMobile

  if (/iphone|ipad|ipod/i.test(platform) || uaLooksAppleMobile) return true
  if (/Android/i.test(userAgent)) return true

  return false
}
