<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(defineProps<{ count: number; max?: number }>(), { max: 99 })

const label = computed(() => (props.count > props.max ? `${props.max}+` : String(props.count)))
</script>

<template>
  <span v-if="props.count > 0" class="app-badge">{{ label }}</span>
</template>

<style scoped>
.app-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: var(--radius-full);
  background: var(--color-brand);
  color: var(--color-bg-card);
  font-size: var(--text-badge);
  font-weight: var(--weight-bold);
  line-height: 1;
}
</style>
