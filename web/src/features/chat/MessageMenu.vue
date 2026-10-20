<script setup lang="ts">
import { computed, onMounted, onUnmounted } from 'vue'
import { ChatMessageKind } from '@/im/types'
import type { ChatMessage } from '@/im/types'
import { canRecall } from './recall'

const props = defineProps<{ message: ChatMessage; x: number; y: number }>()
const emit = defineEmits<{ close: []; action: ['copy' | 'delete' | 'retry' | 'recall'] }>()

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

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  // 点别处即关闭(下一帧再监听,避免把「打开菜单」的那次点击也算进去)
  setTimeout(() => window.addEventListener('mousedown', () => emit('close'), { once: true }), 0)
})
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="message-menu" :style="style" role="menu">
    <button
      v-if="canRecall(props.message)"
      type="button"
      class="message-menu__recall"
      role="menuitem"
      @click="emit('action', 'recall')"
    >
      撤回
    </button>
    <button
      v-if="canCopy"
      type="button"
      class="message-menu__copy"
      role="menuitem"
      @click="emit('action', 'copy')"
    >
      复制
    </button>
    <button
      v-if="props.message.isFailed"
      type="button"
      class="message-menu__retry"
      role="menuitem"
      @click="emit('action', 'retry')"
    >
      重发
    </button>
    <button
      v-if="props.message.isSelf && !props.message.isPending"
      type="button"
      class="message-menu__delete"
      role="menuitem"
      @click="emit('action', 'delete')"
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
