<script setup lang="ts">
import { onMounted } from 'vue'
import { useProfileStore } from '@/stores/profile'

const props = defineProps<{ modelValue: number[] }>()
const emit = defineEmits<{ 'update:modelValue': [number[]] }>()

const store = useProfileStore()

onMounted(() => {
  store.loadTags().catch(() => {})
})

function toggle(id: number) {
  const next = props.modelValue.includes(id)
    ? props.modelValue.filter((x) => x !== id)
    : [...props.modelValue, id]
  emit('update:modelValue', next)
}
</script>

<template>
  <div class="tag-picker">
    <button
      v-for="tag in store.tags"
      :key="tag.id"
      type="button"
      class="tag-picker__chip"
      :class="{ 'tag-picker__chip--active': props.modelValue.includes(tag.id) }"
      @click="toggle(tag.id)"
    >
      {{ tag.name }}
    </button>
  </div>
</template>

<style scoped>
.tag-picker {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
}
.tag-picker__chip {
  height: 32px;
  padding: 0 var(--space-md);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  font-size: var(--text-caption);
  cursor: pointer;
  transition:
    border-color var(--motion-fast) var(--ease-out),
    color var(--motion-fast) var(--ease-out);
}
.tag-picker__chip:hover {
  background: var(--hover-overlay);
}
.tag-picker__chip--active {
  border-color: var(--color-brand);
  color: var(--color-brand);
}
</style>
