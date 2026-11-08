<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { ChatMessageKind } from '@/im/types'
import type { ChatMessage } from '@/im/types'
import { canQuote } from './quote'
import { canRecall } from './recall'

const props = defineProps<{ message: ChatMessage; x: number; y: number }>()
const emit = defineEmits<{
  close: []
  action: ['copy' | 'delete' | 'retry' | 'recall' | 'quote']
}>()

const MENU_WIDTH = 160

/** 靠近右/下边缘时向内收,别让菜单跑出窗口(spec §6.4) */
const style = computed(() => ({
  left: `${Math.min(props.x, Math.max(window.innerWidth - MENU_WIDTH, 0))}px`,
  top: `${Math.min(props.y, Math.max(window.innerHeight - 160, 0))}px`,
}))

const canCopy = computed(
  () => props.message.kind === ChatMessageKind.text && props.message.text.length > 0,
)

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

/** 下一拍挂「点别处关闭」的定时器(卸载时要清掉,否则菜单关掉后它还会跑)。 */
let dismissTimer: ReturnType<typeof setTimeout> | undefined
/** 打开菜单的那次点击还在冒泡链上:挂好监听后先等它过去,再开始响应外部点击。 */
let dismissArmed = false

/**
 * 点菜单**外面**才关闭。
 *
 * ⚠️ 必须监听 `click`,不能监听 `mousedown`(2026-11-08 验收现场抓到的真 bug):
 * 用户点菜单项时事件顺序是 `mousedown → mouseup → click`。用 mousedown 关菜单,
 * 按下那一刻父组件就把 `menu` 置空、组件被卸载,随后的 click 落在已经不存在的
 * 节点上 —— `onMenuAction` 永不执行,表现为「引用 / 复制 / 撤回 / 删除全都点不动」。
 * 菜单内部的点击也不该走到这里:菜单项自带 `@click.stop`。
 */
function onWindowClick(): void {
  if (dismissArmed) emit('close')
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  // 下一拍再挂:打开菜单的那次点击还在冒泡,当场挂上会把自己关掉。
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
  <div class="message-menu" :style="style" role="menu">
    <button
      v-if="canQuote(props.message)"
      type="button"
      class="message-menu__quote"
      role="menuitem"
      data-testid="menu-quote"
      @click.stop="emit('action', 'quote')"
    >
      引用
    </button>
    <button
      v-if="canRecall(props.message)"
      type="button"
      class="message-menu__recall"
      role="menuitem"
      @click.stop="emit('action', 'recall')"
    >
      撤回
    </button>
    <button
      v-if="canCopy"
      type="button"
      class="message-menu__copy"
      role="menuitem"
      @click.stop="emit('action', 'copy')"
    >
      复制
    </button>
    <button
      v-if="props.message.isFailed"
      type="button"
      class="message-menu__retry"
      role="menuitem"
      @click.stop="emit('action', 'retry')"
    >
      重发
    </button>
    <button
      v-if="props.message.isSelf && !props.message.isPending"
      type="button"
      class="message-menu__delete"
      role="menuitem"
      @click.stop="emit('action', 'delete')"
    >
      删除
    </button>
  </div>
</template>

<style scoped>
.message-menu {
  position: fixed;
  z-index: 140;
  display: flex;
  flex-direction: column;
  min-width: 120px;
  padding: var(--space-xs);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-chip);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-floating-bar);
}
.message-menu button {
  padding: var(--space-sm) var(--space-md);
  border: none;
  border-radius: var(--radius-chip);
  background: none;
  font-size: var(--text-caption);
  text-align: left;
  cursor: pointer;
}
.message-menu button:hover {
  background: var(--hover-overlay);
}
.message-menu__delete {
  color: var(--color-danger);
}
</style>
