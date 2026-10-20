<script setup lang="ts">
import AppButton from '@/components/AppButton.vue'

defineProps<{ open: boolean; busy?: boolean; error?: string }>()
const emit = defineEmits<{ close: []; confirm: [] }>()
</script>

<template>
  <div
    v-if="open"
    class="unmatch-dialog"
    role="dialog"
    aria-modal="true"
  >
    <div class="unmatch-dialog__card">
      <h2 class="unmatch-dialog__title">解除配对?</h2>
      <p class="unmatch-dialog__body">解除后双方将无法再聊天,且无法恢复。</p>
      <p v-if="error" class="unmatch-dialog__error">{{ error }}</p>
      <div class="unmatch-dialog__actions">
        <AppButton variant="ghost" @click="emit('close')">取消</AppButton>
        <AppButton
          class="unmatch-dialog__confirm"
          variant="danger"
          :loading="busy"
          @click="emit('confirm')"
        >
          解除配对
        </AppButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.unmatch-dialog {
  position: fixed;
  inset: 0;
  z-index: 150;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--scrim-strong);
}
.unmatch-dialog__card {
  width: 320px;
  padding: var(--space-xxl);
  border-radius: var(--radius-sheet);
  background: var(--color-bg-card);
  text-align: center;
}
.unmatch-dialog__title {
  margin: 0 0 var(--space-sm);
  font-size: var(--text-subtitle);
}
.unmatch-dialog__body {
  margin: 0 0 var(--space-xl);
  color: var(--color-text2);
  font-size: var(--text-caption);
}
.unmatch-dialog__error {
  margin: 0 0 var(--space-md);
  color: var(--color-danger);
  font-size: var(--text-badge);
}
.unmatch-dialog__actions {
  display: flex;
  gap: var(--space-md);
}
.unmatch-dialog__actions > * {
  flex: 1;
}
</style>
