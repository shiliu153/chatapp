<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'

const props = defineProps<{ urls: string[]; index: number }>()
const emit = defineEmits<{ close: [] }>()

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="image-viewer" role="dialog" aria-modal="true">
    <!-- 遮罩铺满整屏且在图片之下:点图片不会冒泡到遮罩 -->
    <div class="image-viewer__mask" @click="emit('close')" />
    <img class="image-viewer__img" :src="props.urls[props.index]" alt="查看大图" />
  </div>
</template>

<style scoped>
.image-viewer {
  position: fixed;
  inset: 0;
  z-index: 120;
  display: flex;
  align-items: center;
  justify-content: center;
}
.image-viewer__mask {
  position: absolute;
  inset: 0;
  background: var(--color-photo-scrim);
  cursor: zoom-out;
}
.image-viewer__img {
  position: relative;
  z-index: 1;
  max-width: 92vw;
  max-height: 92vh;
  border-radius: var(--radius-image);
  box-shadow: var(--shadow-floating-bar);
}
</style>
