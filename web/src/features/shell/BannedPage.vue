<script setup lang="ts"></script>

<template>
  <section class="page">
    <h1 class="page__title">账号已被封禁</h1>
    <p class="page__hint">你的账号因违反社区规范已被限制使用。如有疑问请联系客服。</p>
  </section>
</template>

<style scoped>
.page {
  padding: var(--space-section-gap);
}
.page__title {
  margin: 0 0 var(--space-xs);
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.page__hint {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
</style>
