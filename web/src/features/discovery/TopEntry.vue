<script setup lang="ts">
import type { RouteLocationRaw } from 'vue-router'
import AppBadge from '@/components/AppBadge.vue'

defineProps<{
  icon: string
  label: string
  to: RouteLocationRaw
  count: number
}>()
</script>

<template>
  <RouterLink class="top-entry" :to="to">
    <span class="top-entry__icon" aria-hidden="true">{{ icon }}</span>
    <span class="top-entry__label">{{ label }}</span>
    <AppBadge v-if="count > 0" :count="count" />
  </RouterLink>
</template>

<style scoped>
.top-entry {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
  align-self: flex-start;
  padding: var(--space-xs) var(--space-md);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-decoration: none;
}
.top-entry__icon {
  color: var(--color-brand);
  font-size: var(--text-body);
  line-height: 1;
}
</style>
