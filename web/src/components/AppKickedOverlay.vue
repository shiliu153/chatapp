<script setup lang="ts">
import { useSessionStore } from '@/stores/session'
import AppButton from './AppButton.vue'

const session = useSessionStore()
</script>

<template>
  <div
    v-if="session.kicked"
    class="kicked-overlay"
    role="alertdialog"
    aria-modal="true"
  >
    <div class="kicked-overlay__panel">
      <span class="kicked-overlay__emoji">📵</span>
      <h2 class="kicked-overlay__title">账号已在其他设备登录</h2>
      <p class="kicked-overlay__desc">
        为保障账号安全,同一账号只能在一台设备上使用。当前设备已退出,请重新登录。
      </p>
      <AppButton block size="lg" @click="session.acknowledgeKicked()">重新登录</AppButton>
    </div>
  </div>
</template>

<style scoped>
.kicked-overlay {
  position: fixed;
  inset: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--color-photo-scrim);
}
.kicked-overlay__panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  width: var(--form-card-max);
  max-width: 88vw;
  padding: var(--space-xxl);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-floating-bar);
  text-align: center;
}
.kicked-overlay__emoji {
  font-size: var(--text-emoji);
  line-height: 1;
}
.kicked-overlay__title {
  margin: 0;
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
}
.kicked-overlay__desc {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
</style>
