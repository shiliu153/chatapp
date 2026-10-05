<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{ src?: string | null; name?: string; size?: number }>(),
  { src: null, name: '', size: 40 },
)

const initial = computed(() => (props.name ? props.name.trim().charAt(0) : '♥'))
const showImage = computed(() => typeof props.src === 'string' && props.src.length > 0)
const style = computed(() => ({ width: `${props.size}px`, height: `${props.size}px` }))
</script>

<template>
  <span class="app-avatar" :class="{ 'app-avatar--fallback': !showImage }" :style="style">
    <img
      v-if="showImage"
      :src="props.src as string"
      alt=""
      class="app-avatar__img"
    />
    <template v-else>{{ initial }}</template>
  </span>
</template>

<style scoped>
.app-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: none;
  overflow: hidden;
  border-radius: var(--radius-full);
  background: var(--color-bg-page);
  font-size: var(--text-caption);
  font-weight: var(--weight-bold);
}
.app-avatar--fallback {
  background: var(--gradient-heart);
  color: var(--color-bg-card);
  font-size: var(--text-body);
}
.app-avatar__img {
  width: 100%;
  height: 100%;
  object-fit: cover;
}
</style>
