/** 三段数字逐段比较;格式不合法按 0 处理。 */
export function isOutdated(current: string, min: string): boolean {
  const parts = (value: string): number[] =>
    value.split('.').map((item) => Number.parseInt(item, 10) || 0)
  const a = parts(current)
  const b = parts(min)
  for (let i = 0; i < 3; i++) {
    const x = a[i] ?? 0
    const y = b[i] ?? 0
    if (x !== y) return x < y
  }
  return false
}
