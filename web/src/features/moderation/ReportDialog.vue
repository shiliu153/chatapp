<script setup lang="ts">
import { ref, watch } from 'vue'
import AppButton from '@/components/AppButton.vue'
import type { ReportType } from '@/api/types'

const props = defineProps<{ open: boolean; target: 'user' | 'post' }>()
const emit = defineEmits<{ close: []; submitted: [ReportType, string] }>()

/** 四类理由与后端枚举一一对应(moderation.md / feed.md)。 */
const REASONS: { value: ReportType; label: string }[] = [
  { value: 'harassment', label: '骚扰' },
  { value: 'porn', label: '色情' },
  { value: 'fraud', label: '诈骗' },
  { value: 'other', label: '其他' },
]

const reason = ref<ReportType | ''>('')
const detail = ref('')
const error = ref('')

// 每次打开都从干净状态开始
watch(
  () => props.open,
  (open) => {
    if (open) {
      reason.value = ''
      detail.value = ''
      error.value = ''
    }
  },
)

function onSubmit() {
  if (!reason.value) {
    error.value = '请选择举报理由'
    return
  }
  emit('submitted', reason.value, detail.value.trim())
}
</script>

<template>
  <div
    v-if="props.open"
    class="report-dialog"
    role="dialog"
    aria-modal="true"
  >
    <div class="report-dialog__panel">
      <h2 class="report-dialog__title">举报{{ props.target === 'post' ? '动态' : '用户' }}</h2>
      <p class="report-dialog__desc">我们会尽快核实处理,你的举报是匿名的</p>

      <div class="report-dialog__reasons">
        <button
          v-for="item in REASONS"
          :key="item.value"
          type="button"
          class="report-dialog__reason"
          :class="{ 'report-dialog__reason--active': reason === item.value }"
          @click="reason = item.value"
        >
          {{ item.label }}
        </button>
      </div>

      <textarea
        v-model="detail"
        class="report-dialog__detail"
        placeholder="补充说明(选填,最多 200 字)"
        maxlength="200"
        rows="3"
      />
      <p v-if="error" class="report-dialog__error">{{ error }}</p>

      <div class="report-dialog__actions">
        <AppButton
          class="report-dialog__cancel"
          variant="ghost"
          block
          @click="emit('close')"
        >
          取消
        </AppButton>
        <AppButton class="report-dialog__submit" block @click="onSubmit">提交举报</AppButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.report-dialog {
  position: fixed;
  inset: 0;
  z-index: 85;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--scrim-strong);
}
.report-dialog__panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  width: clamp(280px, 40%, var(--form-card-max));
  padding: var(--space-xxl);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-floating-bar);
}
.report-dialog__title {
  margin: 0;
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
}
.report-dialog__desc {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.report-dialog__reasons {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: var(--space-sm);
}
.report-dialog__reason {
  height: 40px;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-chip);
  background: var(--color-bg-card);
  cursor: pointer;
}
.report-dialog__reason--active {
  border-color: var(--color-brand);
  color: var(--color-brand);
}
.report-dialog__detail {
  padding: var(--space-md);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  font-family: var(--font-latin);
  font-size: var(--text-body);
  resize: vertical;
}
.report-dialog__error {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-danger);
}
.report-dialog__actions {
  display: flex;
  gap: var(--space-md);
}
</style>
