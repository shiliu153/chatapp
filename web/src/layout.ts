import { computed, ref, type ComputedRef, type Ref } from 'vue'

/**
 * 自适应布局的行为参数(拖拽数学需要数字,故 JS 也要一份)。
 * ⚠️ 与 src/styles/tokens.css 的 --sidebar-* / --chatlist-* / --bubble-max-ratio
 * 必须一致,由 tests/unit/layout-consistency.spec.ts 兜底。
 */
export const layout = {
  sidebar: {
    ratio: 0.16,
    min: 208,
    max: 264,
    dragMin: 72,
    dragMax: 360,
    iconThreshold: 176,
  },
  chatList: { ratio: 0.22, min: 264, max: 360 },
  bubbleMaxRatio: 0.72,
} as const

const STORAGE_KEY = 'hb.sidebarWidth'

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max)
}

function defaultWidth(viewportWidth: number): number {
  const { ratio, min, max } = layout.sidebar
  return Math.round(clamp(viewportWidth * ratio, min, max))
}

function readStoredWidth(): number | null {
  const raw = localStorage.getItem(STORAGE_KEY)
  if (raw === null) return null
  const parsed = Number(raw)
  return Number.isNaN(parsed) ? null : parsed
}

export interface SidebarState {
  width: Ref<number>
  isIconOnly: ComputedRef<boolean>
  isDragging: Ref<boolean>
  beginDrag: (event: PointerEvent) => void
  resetToDefault: () => void
  /** 仅供测试:直接设定宽度(仍走夹取与持久化) */
  setWidthForTest: (value: number) => void
}

export function useSidebar(): SidebarState {
  const { dragMin, dragMax, iconThreshold } = layout.sidebar
  const width = ref(readStoredWidth() ?? defaultWidth(window.innerWidth))
  const isDragging = ref(false)

  function setWidth(value: number) {
    width.value = Math.round(clamp(value, dragMin, dragMax))
    localStorage.setItem(STORAGE_KEY, String(width.value))
  }

  function beginDrag(event: PointerEvent) {
    event.preventDefault()
    isDragging.value = true
    const startX = event.clientX
    const startWidth = width.value

    const onMove = (e: PointerEvent) => setWidth(startWidth + (e.clientX - startX))
    const onUp = () => {
      isDragging.value = false
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }

    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  return {
    width,
    isIconOnly: computed(() => width.value < iconThreshold),
    isDragging,
    beginDrag,
    resetToDefault: () => setWidth(defaultWidth(window.innerWidth)),
    setWidthForTest: setWidth,
  }
}
