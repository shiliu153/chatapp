<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'

const emit = defineEmits<{ close: []; unmatch: [] }>()

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
  <div class="chat-more" role="menu">
    <button
      type="button"
      class="chat-more__unmatch"
      role="menuitem"
      @click="emit('unmatch')"
    >
      解除配对
    </button>
  </div>
</template>

<style scoped>
.chat-more {
  position: absolute;
  top: 56px;
  right: var(--space-section-gap);
  z-index: 130;
  display: flex;
  flex-direction: column;
  min-width: 120px;
  padding: var(--space-xs);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-chip);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-floating-bar);
}
.chat-more button {
  padding: var(--space-sm) var(--space-md);
  border: none;
  border-radius: var(--radius-chip);
  background: none;
  color: var(--color-danger);
  font-size: var(--text-caption);
  text-align: left;
  cursor: pointer;
}
.chat-more button:hover {
  background: var(--hover-overlay);
}
</style>
