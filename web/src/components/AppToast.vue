<script setup lang="ts">
/** 底部居中轻提示;文案由调用方用 useToast 控制,空串不渲染。 */
defineProps<{ text: string }>()
</script>

<template>
  <p v-if="text" class="app-toast" role="status">{{ text }}</p>
</template>

<style scoped>
.app-toast {
  position: fixed;
  bottom: 96px;
  left: 50%;
  z-index: 20;
  margin: 0;
  padding: var(--space-xs) var(--space-md);
  border-radius: var(--radius-full);
  background: var(--color-text1);
  color: var(--color-bg-card);
  font-size: var(--text-badge);
  transform: translateX(-50%);
  animation: app-toast-in var(--motion-fast) var(--ease-out);
}

@keyframes app-toast-in {
  from {
    opacity: 0;
    transform: translate(-50%, var(--space-xs));
  }
}

@media (prefers-reduced-motion: reduce) {
  .app-toast {
    animation: none;
  }
}
</style>
