<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>

<template>
  <div class="form-card-wrap">
    <section class="form-card">
      <header class="form-card__head">
        <h1 class="form-card__title">{{ title }}</h1>
        <p v-if="description" class="form-card__desc">{{ description }}</p>
      </header>
      <slot />
    </section>
  </div>
</template>

<style scoped>
.form-card-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: var(--space-section-gap);
  background: var(--color-bg-page);
}
.form-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-xl);
  width: clamp(var(--form-card-min), var(--form-card-ratio), var(--form-card-max));
  max-width: 100%;
  padding: var(--space-xxl);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
}
.form-card__head {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}
.form-card__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
  letter-spacing: -0.02em;
}
.form-card__desc {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
</style>
