<script setup lang="ts">
import { onMounted } from 'vue'
import AppBadge from '@/components/AppBadge.vue'
import { useLikesStore } from '@/stores/likes'

const store = useLikesStore()

onMounted(() => {
  store.loadCount().catch(() => {})
})
</script>

<template>
  <RouterLink class="likes-entry" :to="{ name: 'likes' }">
    <span class="likes-entry__heart" aria-hidden="true">♥</span>
    <span class="likes-entry__label">喜欢我的人</span>
    <AppBadge v-if="store.count > 0" :count="store.count" />
  </RouterLink>
</template>

<style scoped>
.likes-entry {
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
.likes-entry__heart {
  color: var(--color-brand);
  font-size: var(--text-body);
  line-height: 1;
}
</style>
