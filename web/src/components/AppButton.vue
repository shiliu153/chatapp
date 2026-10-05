<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    variant?: 'primary' | 'ghost' | 'danger'
    size?: 'md' | 'lg'
    disabled?: boolean
    loading?: boolean
    block?: boolean
  }>(),
  { variant: 'primary', size: 'md', disabled: false, loading: false, block: false },
)

const emit = defineEmits<{ click: [MouseEvent] }>()

function onClick(event: MouseEvent) {
  // 禁用/加载中一律不派发业务事件
  if (props.disabled || props.loading) return
  emit('click', event)
}
</script>

<template>
  <button
    type="button"
    class="app-button"
    :class="[`app-button--${variant}`, `app-button--${size}`, { 'app-button--block': block }]"
    :disabled="disabled || loading"
    @click="onClick"
  >
    <span v-if="loading" class="app-button__spinner" aria-hidden="true" />
    <slot />
  </button>
</template>

<style scoped>
.app-button {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--space-sm);
  border: 1px solid transparent;
  border-radius: var(--radius-input);
  font-family: var(--font-latin);
  font-weight: var(--weight-semibold);
  cursor: pointer;
  transition:
    background var(--motion-fast) var(--ease-out),
    opacity var(--motion-fast) var(--ease-out);
}
.app-button--md {
  height: 44px;
  padding: 0 var(--space-lg);
  font-size: var(--text-subtitle);
}
.app-button--lg {
  height: 52px;
  padding: 0 var(--space-xl);
  font-size: var(--text-subtitle);
}
.app-button--block {
  width: 100%;
}
.app-button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.app-button--primary {
  background: var(--gradient-heart);
  color: var(--color-bg-card);
  box-shadow: var(--shadow-primary-button);
}
.app-button--primary:not(:disabled):hover {
  filter: brightness(1.04);
}

.app-button--ghost {
  background: var(--color-bg-card);
  border-color: var(--color-divider);
  color: var(--color-text1);
}
.app-button--ghost:not(:disabled):hover {
  background: var(--hover-overlay);
}

.app-button--danger {
  background: var(--color-bg-card);
  border-color: var(--color-danger);
  color: var(--color-danger);
}
.app-button--danger:not(:disabled):hover {
  background: var(--hover-overlay);
}

.app-button__spinner {
  width: 16px;
  height: 16px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: var(--radius-full);
  animation: app-button-spin var(--motion-loop) linear infinite;
}
@keyframes app-button-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
