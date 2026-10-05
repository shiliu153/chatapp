const FIVE_MINUTES = 5 * 60 * 1000

/** 两条消息间隔 > 5 分钟时插入时间条(与 App 一致)。 */
export function shouldShowTime(prevMs: number | null, currentMs: number): boolean {
  if (prevMs === null) return true
  return currentMs - prevMs > FIVE_MINUTES
}

const pad = (n: number) => String(n).padStart(2, '0')

/** 当天只到分钟;跨天带上月日。 */
export function formatTime(ms: number, now: Date = new Date()): string {
  const date = new Date(ms)
  const hm = `${pad(date.getHours())}:${pad(date.getMinutes())}`
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  return sameDay ? hm : `${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${hm}`
}
