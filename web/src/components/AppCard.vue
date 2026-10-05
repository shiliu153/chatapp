<script setup lang="ts">
const props = withDefaults(defineProps<{ padding?: 'md' | 'lg'; hoverable?: boolean }>(), {
  padding: 'md',
  hoverable: false,
})
</script>

<template>
  <section
    class="app-card"
    :class="[`app-card--${props.padding}`, { 'app-card--hoverable': props.hoverable }]"
  >
    <slot />
  </section>
</template>

<style scoped>
.app-card {
  background: var(--color-bg-card);
  border-radius: var(--radius-card);
  box-shadow: var(--shadow-card);
  transition:
    box-shadow var(--motion-base) var(--ease-out),
    transform var(--motion-base) var(--ease-out);
}
.app-card--md {
  padding: var(--space-lg);
}
.app-card--lg {
  padding: var(--space-xl);
}
.app-card--hoverable:hover {
  box-shadow: var(--shadow-floating-bar);
  transform: translateY(-2px);
}
</style>
