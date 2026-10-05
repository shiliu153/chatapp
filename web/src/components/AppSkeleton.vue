<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{ width?: string; height?: string; radius?: string }>(),
  { width: '100%', height: '16px', radius: 'var(--radius-image)' },
)

const style = computed(() => ({
  width: props.width,
  height: props.height,
  borderRadius: props.radius,
}))
</script>

<template>
  <span class="app-skeleton" :style="style" aria-hidden="true" />
</template>

<style scoped>
.app-skeleton {
  display: block;
  background: var(--color-divider);
  animation: app-skeleton-breathe var(--motion-loop) var(--ease-out) infinite;
}
@keyframes app-skeleton-breathe {
  0%,
  100% {
    opacity: 1;
  }
  50% {
    opacity: 0.55;
  }
}
</style>
