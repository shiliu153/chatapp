<script setup lang="ts">
import { ref, watch } from 'vue'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ close: []; submitted: [string] }>()

/** 注销后会被永久删除的内容(与 App 弹窗、隐私政策 §四口径一致)。 */
const CONSEQUENCES = [
  '个人资料、标签与全部照片',
  '配对关系与聊天关系',
  '你发布的动态与评论',
  '拉黑与举报记录',
  '账号本身(手机号将被释放)',
]

const phone = ref('')
const error = ref('')

// 每次打开都从干净状态开始(与 ReportDialog 同范式)
watch(
  () => props.open,
  (open) => {
    if (open) {
      phone.value = ''
      error.value = ''
    }
  },
)

function onSubmit() {
  if (!/^\d{11}$/.test(phone.value.trim())) {
    error.value = '请输入 11 位手机号'
    return
  }
  emit('submitted', phone.value.trim())
}
</script>

<template>
  <div
    v-if="props.open"
    class="delete-dialog"
    role="dialog"
    aria-modal="true"
  >
    <div class="delete-dialog__panel">
      <h2 class="delete-dialog__title">注销账号</h2>
      <p class="delete-dialog__desc">以下内容将被永久删除,且无法恢复:</p>
      <ul class="delete-dialog__list">
        <li v-for="item in CONSEQUENCES" :key="item">{{ item }}</li>
      </ul>

      <div class="delete-dialog__input">
        <AppInput
          v-model="phone"
          inputmode="numeric"
          placeholder="请输入当前账号的手机号"
          :error="error"
        />
      </div>

      <div class="delete-dialog__actions">
        <AppButton
          class="delete-dialog__cancel"
          variant="ghost"
          block
          @click="emit('close')"
        >
          取消
        </AppButton>
        <AppButton
          class="delete-dialog__confirm"
          variant="danger"
          block
          :disabled="!/^\d{11}$/.test(phone.trim())"
          @click="onSubmit"
        >
          确认注销
        </AppButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.delete-dialog {
  position: fixed;
  inset: 0;
  z-index: 85;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--scrim-strong);
}
.delete-dialog__panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  width: clamp(280px, 40%, var(--form-card-max));
  padding: var(--space-xxl);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-floating-bar);
}
.delete-dialog__title {
  margin: 0;
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
}
.delete-dialog__desc {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.delete-dialog__list {
  margin: 0;
  padding-left: var(--space-lg);
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.delete-dialog__input {
  margin-top: var(--space-sm);
}
.delete-dialog__actions {
  display: flex;
  gap: var(--space-md);
}
</style>
