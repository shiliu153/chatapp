<script setup lang="ts">
withDefaults(defineProps<{ emoji?: string; title: string; description?: string }>(), {
  emoji: '💫',
  description: '',
})
</script>

<template>
  <div class="app-empty">
    <span class="app-empty__emoji">{{ emoji }}</span>
    <p class="app-empty__title">{{ title }}</p>
    <p v-if="description" class="app-empty__desc">{{ description }}</p>
  </div>
</template>

<style scoped>
.app-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-sm);
  padding: var(--space-section-gap);
  text-align: center;
}
.app-empty__emoji {
  font-size: var(--text-emoji);
  line-height: 1;
}
.app-empty__title {
  margin: 0;
  font-size: var(--text-subtitle);
  font-weight: var(--weight-semibold);
  color: var(--color-text1);
}
.app-empty__desc {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
</style>
