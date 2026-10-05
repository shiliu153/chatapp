/** 拖动多少像素才算一次滑卡(超过即判定,避免误触)。 */
export const SWIPE_THRESHOLD = 120

/** 纯函数:根据水平位移给出动作;未过阈值返回 null。 */
export function swipeDirection(dx: number): 'like' | 'pass' | null {
  if (dx >= SWIPE_THRESHOLD) return 'like'
  if (dx <= -SWIPE_THRESHOLD) return 'pass'
  return null
}
