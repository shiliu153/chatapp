<script setup lang="ts">
import { ref } from 'vue'
import AppButton from '@/components/AppButton.vue'
import { isAgreed, markAgreed } from './agreed'

const visible = ref(!isAgreed())
const checked = ref(false)
const hint = ref('')

function onAgree() {
  if (!checked.value) {
    hint.value = '请先阅读并同意以下文件'
    return
  }
  markAgreed()
  visible.value = false
}
</script>

<template>
  <div
    v-if="visible"
    class="legal-gate"
    role="dialog"
    aria-modal="true"
  >
    <div class="legal-gate__panel">
      <h2 class="legal-gate__title">欢迎来到心跳</h2>
      <p class="legal-gate__desc">开始之前,请阅读并同意以下文件:</p>
      <ul class="legal-gate__list">
        <li>
          <RouterLink to="/legal/agreement" target="_blank">《用户协议》</RouterLink>
        </li>
        <li>
          <RouterLink to="/legal/privacy" target="_blank">《隐私政策》</RouterLink>
        </li>
      </ul>
      <label class="legal-gate__check">
        <input v-model="checked" type="checkbox" />
        我已阅读并同意上述文件
      </label>
      <p v-if="hint" class="legal-gate__hint">{{ hint }}</p>
      <AppButton
        class="legal-gate__submit"
        block
        size="lg"
        @click="onAgree"
      >
        同意并继续
      </AppButton>
    </div>
  </div>
</template>

<style scoped>
.legal-gate {
  position: fixed;
  inset: 0;
  z-index: 90;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-photo-scrim);
}
.legal-gate__panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  width: var(--form-card-max);
  max-width: 88vw;
  padding: var(--space-xxl);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-floating-bar);
}
.legal-gate__title {
  margin: 0;
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
}
.legal-gate__desc {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.legal-gate__list {
  margin: 0;
  padding-left: var(--space-lg);
  font-size: var(--text-body);
}
.legal-gate__list a:hover {
  color: var(--color-brand);
}
.legal-gate__check {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  font-size: var(--text-caption);
}
.legal-gate__hint {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-danger);
}
</style>
