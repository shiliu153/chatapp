<script setup lang="ts">
import AppButton from '@/components/AppButton.vue'
import { APP_NAME, DOWNLOADS_ENABLED } from '@/constants'
</script>

<template>
  <main class="guard">
    <section class="guard__panel">
      <span class="guard__logo">♥ {{ APP_NAME }}</span>
      <h1 class="guard__title">请在电脑上打开网页版</h1>
      <p class="guard__desc">手机上请使用「{{ APP_NAME }}」App,体验更完整。</p>
      <AppButton block size="lg" :disabled="!DOWNLOADS_ENABLED">
        {{ DOWNLOADS_ENABLED ? '下载 App' : '下载 App · 敬请期待' }}
      </AppButton>
    </section>
  </main>
</template>

<style scoped>
.guard {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: var(--space-section-gap);
  background: var(--color-bg-page);
}
.guard__panel {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  width: clamp(280px, 82%, var(--form-card-max));
  padding: var(--space-xxl);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
  text-align: center;
}
.guard__logo {
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
  color: var(--color-brand);
}
.guard__title {
  margin: 0;
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
}
.guard__desc {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
</style>
