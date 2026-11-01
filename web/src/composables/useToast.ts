import { ref } from 'vue'
import type { Ref } from 'vue'

/** 轻量提示:show() 显示文案并在 [durationMs] 后自动清空;连续 show 重置计时。 */
export function useToast(durationMs = 1500): {
  text: Ref<string>
  show: (message: string) => void
  clear: () => void
} {
  const text = ref('')
  let timer: ReturnType<typeof setTimeout> | undefined

  function clear(): void {
    if (timer) clearTimeout(timer)
    timer = undefined
    text.value = ''
  }

  function show(message: string): void {
    clear()
    text.value = message
    timer = setTimeout(() => {
      text.value = ''
      timer = undefined
    }, durationMs)
  }

  return { text, show, clear }
}
