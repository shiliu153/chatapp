/**
 * 协议同意状态。
 * 与 App 的 legalVersion 语义一致:改文案时把 LEGAL_VERSION +1,启动弹窗会重新出现一次。
 */
export const LEGAL_VERSION = 2

const AGREED_KEY = 'hb.legalAgreed'

/** 是否已同意「当前版本」的协议。 */
export function isAgreed(): boolean {
  return localStorage.getItem(AGREED_KEY) === String(LEGAL_VERSION)
}

/** 记录已同意当前版本。 */
export function markAgreed(): void {
  localStorage.setItem(AGREED_KEY, String(LEGAL_VERSION))
}
