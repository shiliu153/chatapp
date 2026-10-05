/**
 * 是否移动端浏览器。
 * 判据与 Flutter 的 ui_web.browser 一致:platform + UA + maxTouchPoints,
 * **不使用窗口宽度**(spec §6.1:窗口拖窄仍是 PC 壳层)。
 */
export function isMobileDevice(): boolean {
  if (typeof navigator === 'undefined') return false

  const platform = navigator.platform ?? ''
  const userAgent = navigator.userAgent ?? ''
  const maxTouchPoints = navigator.maxTouchPoints ?? 0

  // iPad 请求「桌面版网站」时 platform 会是 MacIntel,靠多点触控识别
  if (platform.startsWith('Mac')) return maxTouchPoints > 2

  if (/iphone|ipad|ipod/i.test(platform)) return true
  if (/Android/i.test(userAgent)) return true

  return false
}
