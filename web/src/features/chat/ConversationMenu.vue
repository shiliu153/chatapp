<script setup lang="ts">
/**
 * 会话行「更多」菜单(批次 N):置顶 / 免打扰 / 删除会话。
 *
 * 交互口径与 `MessageMenu` 一致(2026-11-08 验收踩过的坑):
 * - 点菜单**外面**才关闭,必须监听 `click` 而不是 `mousedown` —— 用 mousedown 的话,
 *   按下那一刻父组件就把菜单置空、组件被卸载,随后的 click 落在不存在的节点上,
 *   表现为「三项全都点不动」;
 * - 打开菜单的那次点击还在冒泡链上,所以「点外面关闭」的监听要等下一拍再挂。
 */
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'

const props = defineProps<{ pinned: boolean; muted: boolean; x: number; y: number }>()
const emit = defineEmits<{ close: []; action: ['pin' | 'mute' | 'delete'] }>()

const MENU_WIDTH = 168
const MENU_HEIGHT = 132

/** 靠近右/下边缘时向内收,别让菜单跑出窗口 */
const style = computed(() => ({
  left: `${Math.min(props.x, Math.max(window.innerWidth - MENU_WIDTH, 0))}px`,
  top: `${Math.min(props.y, Math.max(window.innerHeight - MENU_HEIGHT, 0))}px`,
}))

const firstItem = ref<HTMLButtonElement | null>(null)

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') emit('close')
}

let dismissTimer: ReturnType<typeof setTimeout> | undefined
let dismissArmed = false

function onWindowClick(): void {
  if (dismissArmed) emit('close')
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  // 键盘打开时焦点直接进菜单:Tab 之后能顺着三项走
  void nextTick(() => firstItem.value?.focus())
  dismissTimer = setTimeout(() => {
    dismissArmed = true
    window.addEventListener('click', onWindowClick)
  }, 0)
})

onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('click', onWindowClick)
  if (dismissTimer) clearTimeout(dismissTimer)
})
</script>

<template>
  <div
    class="conversation-menu"
    :style="style"
    role="menu"
    aria-label="会话操作"
  >
    <button
      ref="firstItem"
      type="button"
      class="conversation-menu__pin"
      role="menuitem"
      data-testid="menu-pin"
      @click.stop="emit('action', 'pin')"
    >
      {{ props.pinned ? '取消置顶' : '置顶' }}
    </button>
    <button
      type="button"
      class="conversation-menu__mute"
      role="menuitem"
      data-testid="menu-mute"
      @click.stop="emit('action', 'mute')"
    >
      {{ props.muted ? '取消免打扰' : '免打扰' }}
    </button>
    <button
      type="button"
      class="conversation-menu__delete"
      role="menuitem"
      data-testid="menu-delete"
      @click.stop="emit('action', 'delete')"
    >
      删除会话
    </button>
  </div>
</template>

<style scoped>
.conversation-menu {
  position: fixed;
  z-index: 140;
  display: flex;
  flex-direction: column;
  min-width: 140px;
  padding: var(--space-xs);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-chip);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-floating-bar);
}
.conversation-menu button {
  padding: var(--space-sm) var(--space-md);
  border: none;
  border-radius: var(--radius-chip);
  background: none;
  color: var(--color-text1);
  font-size: var(--text-caption);
  text-align: left;
  cursor: pointer;
}
.conversation-menu button:hover {
  background: var(--hover-overlay);
}
.conversation-menu button:focus-visible {
  outline: 2px solid var(--color-focus-ring);
}
.conversation-menu__delete {
  color: var(--color-danger);
}
</style>
