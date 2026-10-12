<script setup lang="ts">
/** 在线光:一屏只出现在「值得注意的人」身上(候选卡/资料页/会话行)。 */
defineProps<{ online: boolean }>()
</script>

<template>
  <span v-if="online" class="online-dot" aria-label="在线" />
</template>

<style scoped>
.online-dot {
  display: inline-block;
  flex: none;
  width: 12px;
  height: 12px;
  border: 2px solid var(--color-bg-card);
  border-radius: var(--radius-full);
  background: var(--color-green);
  box-shadow: 0 0 0 4px var(--glow-online);
}
</style>
