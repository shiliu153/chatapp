<script setup lang="ts">
import AppButton from './AppButton.vue'

const props = withDefaults(defineProps<{ message?: string; retryLabel?: string }>(), {
  message: '出了点问题',
  retryLabel: '重试',
})
const emit = defineEmits<{ retry: [] }>()
</script>

<template>
  <div class="app-error">
    <span class="app-error__emoji">🫧</span>
    <p class="app-error__message">{{ props.message }}</p>
    <AppButton variant="ghost" @click="emit('retry')">{{ props.retryLabel }}</AppButton>
  </div>
</template>

<style scoped>
.app-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-section-gap);
  text-align: center;
}
.app-error__emoji {
  font-size: var(--text-emoji);
  line-height: 1;
}
.app-error__message {
  margin: 0;
  font-size: var(--text-body);
  color: var(--color-text2);
}
</style>
