<script setup lang="ts">
/**
 * 删除会话的二次确认(批次 N)。
 *
 * 删除是**单方**行为:只把自己这一侧的会话与本地记录去掉,对端完全不受影响。
 * 文案必须把这一点说清楚,否则用户会以为是「双方都删了」。
 */
import AppButton from '@/components/AppButton.vue'

defineProps<{ open: boolean; name?: string; busy?: boolean; error?: string }>()
const emit = defineEmits<{ close: []; confirm: [] }>()
</script>

<template>
  <div
    v-if="open"
    class="delete-conversation"
    role="dialog"
    aria-modal="true"
  >
    <div class="delete-conversation__card">
      <h2 class="delete-conversation__title">删除会话?</h2>
      <p class="delete-conversation__body">
        将与{{ name ? `「${name}」` : '对方' }}的会话从你的列表中移除,聊天记录不再显示;对方不受影响。
      </p>
      <p v-if="error" class="delete-conversation__error">{{ error }}</p>
      <div class="delete-conversation__actions">
        <AppButton variant="ghost" @click="emit('close')">取消</AppButton>
        <AppButton
          class="delete-conversation__confirm"
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
.delete-conversation {
  position: fixed;
  inset: 0;
  z-index: 150;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--scrim-strong);
}
.delete-conversation__card {
  width: 320px;
  padding: var(--space-xxl);
  border-radius: var(--radius-sheet);
  background: var(--color-bg-card);
  text-align: center;
}
.delete-conversation__title {
  margin: 0 0 var(--space-sm);
  font-size: var(--text-subtitle);
}
.delete-conversation__body {
  margin: 0 0 var(--space-xl);
  color: var(--color-text2);
  font-size: var(--text-caption);
  line-height: var(--leading-body);
}
.delete-conversation__error {
  margin: 0 0 var(--space-md);
  color: var(--color-danger);
  font-size: var(--text-badge);
}
.delete-conversation__actions {
  display: flex;
  gap: var(--space-md);
}
.delete-conversation__actions > * {
  flex: 1;
}
</style>
