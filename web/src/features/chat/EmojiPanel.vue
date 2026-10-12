<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'

const emit = defineEmits<{ pick: [string]; close: [] }>()

/** 与 App 的表情面板保持同一组,不引第三方库 */
const EMOJIS = [
  '😀', '😄', '😁', '😊', '🥰', '😍', '😘', '😜',
  '🤔', '😅', '😂', '🥲', '😭', '😢', '😳', '😴',
  '👍', '👏', '🙏', '🤝', '💪', '🎉', '❤️', '💔',
  '🌹', '🍀', '☀️', '🌙', '🍜', '☕', '🎬', '🎵',
]

function onKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') emit('close')
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="emoji-panel">
    <button
      v-for="emoji in EMOJIS"
      :key="emoji"
      type="button"
      class="emoji-panel__item"
      @click="emit('pick', emoji)"
    >
      {{ emoji }}
    </button>
  </div>
</template>

<style scoped>
.emoji-panel {
  display: grid;
  grid-template-columns: repeat(8, 1fr);
  gap: var(--space-xs);
  padding: var(--space-md);
  border-top: 1px solid var(--color-divider);
  background: var(--color-bg-card);
}
.emoji-panel__item {
  height: 36px;
  border: none;
  border-radius: var(--radius-chip);
  background: none;
  font-size: var(--text-subtitle);
  cursor: pointer;
}
.emoji-panel__item:hover {
  background: var(--hover-overlay);
}
</style>
