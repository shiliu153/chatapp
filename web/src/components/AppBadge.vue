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
  /* stylelint-disable-next-line declaration-property-unit-disallowed-list -- 角标左右各 5px:space 档位从 4 起,5 是 18px 高胶囊装两位数的最小横向留白,没有对应档位;到期:补「角标内边距」token 或随 E-5 迁移该页时重定(会改视觉,需一次验收) */
  padding: 0 5px;
  border-radius: var(--radius-full);
  background: var(--color-brand);
  color: var(--color-bg-card);
  font-size: var(--text-badge);
  font-weight: var(--weight-bold);
  line-height: 1;
}
</style>
