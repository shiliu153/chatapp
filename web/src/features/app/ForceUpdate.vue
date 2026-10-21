<script setup lang="ts">
defineProps<{ current: string; min: string; downloadUrl: string }>()
</script>

<template>
  <main class="force-update">
    <h1>需要更新后才能继续使用</h1>
    <p>当前版本 {{ current }},最低要求 {{ min }}</p>
    <a v-if="downloadUrl" :href="downloadUrl" class="force-update__link">下载新版本</a>
  </main>
</template>

<style scoped>
.force-update {
  min-height: 100vh;
  display: grid;
  place-content: center;
  gap: 12px;
  padding: 32px;
  text-align: center;
  background: var(--color-bg-page);
  color: var(--color-text-1);
}

.force-update__link {
  color: var(--color-brand);
}
</style>
