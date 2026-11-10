<script setup lang="ts">
/**
 * 批量删除聊天记录的二次确认(批次 T)。
 *
 * 删除是**单方**行为(与「撤回」相对):只删自己这一侧的副本,对方仍看得见、
 * 也不会收到任何通知,且不可恢复。文案必须把这一点说清 —— 否则用户会以为
 * 跟撤回一样「双方都没了」。
 */
import AppButton from '@/components/AppButton.vue'

withDefaults(defineProps<{ open: boolean; count: number; busy?: boolean }>(), {
  busy: false,
})
const emit = defineEmits<{ close: []; confirm: [] }>()
</script>

<template>
  <div
    v-if="open"
    class="delete-messages"
    role="dialog"
    aria-modal="true"
  >
    <div class="delete-messages__card">
      <h2 class="delete-messages__title">删除这 {{ count }} 条?</h2>
      <p class="delete-messages__body">
        只在你这边删除,对方仍可见。删除后不可恢复。
      </p>
      <div class="delete-messages__actions">
        <AppButton variant="ghost" @click="emit('close')">取消</AppButton>
        <AppButton
          class="delete-messages__confirm"
          variant="danger"
          :loading="busy"
          @click="emit('confirm')"
        >
          删除
        </AppButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.delete-messages {
  position: fixed;
  inset: 0;
  z-index: 150;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--scrim-strong);
}
.delete-messages__card {
  width: 320px;
  padding: var(--space-xxl);
  border-radius: var(--radius-sheet);
  background: var(--color-bg-card);
  text-align: center;
}
.delete-messages__title {
  margin: 0 0 var(--space-sm);
  font-size: var(--text-subtitle);
}
.delete-messages__body {
  margin: 0 0 var(--space-xl);
  color: var(--color-text2);
  font-size: var(--text-caption);
  line-height: var(--leading-body);
}
.delete-messages__actions {
  display: flex;
  gap: var(--space-md);
}
.delete-messages__actions > * {
  flex: 1;
}
</style>
