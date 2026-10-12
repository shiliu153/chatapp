<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    modelValue: string
    type?: string
    /** 与 DOM 的 inputmode 取值一致(移动端键盘类型);PC 上不影响功能 */
    inputmode?: 'search' | 'text' | 'email' | 'tel' | 'url' | 'none' | 'numeric' | 'decimal'
    placeholder?: string
    maxlength?: number
    disabled?: boolean
    error?: string
  }>(),
  {
    type: 'text',
    inputmode: undefined,
    placeholder: '',
    maxlength: undefined,
    disabled: false,
    error: '',
  },
)

const emit = defineEmits<{ 'update:modelValue': [string]; enter: [] }>()
</script>

<template>
  <div class="app-input" :class="{ 'app-input--error': !!props.error }">
    <input
      class="app-input__field"
      :type="props.type"
      :inputmode="props.inputmode"
      :value="props.modelValue"
      :placeholder="props.placeholder"
      :maxlength="props.maxlength"
      :disabled="props.disabled"
      @input="emit('update:modelValue', ($event.target as HTMLInputElement).value)"
      @keyup.enter="emit('enter')"
    />
    <p v-if="props.error" class="app-input__error">{{ props.error }}</p>
  </div>
</template>

<style scoped>
.app-input {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  width: 100%;
}
.app-input__field {
  width: 100%;
  height: 44px;
  padding: 0 var(--space-lg);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  background: var(--color-bg-card);
  color: var(--color-text1);
  font-size: var(--text-body);
  transition:
    border-color var(--motion-fast) var(--ease-out),
    box-shadow var(--motion-fast) var(--ease-out);
}
.app-input__field::placeholder {
  color: var(--color-text3);
}
.app-input__field:focus {
  border-color: var(--color-brand);
  box-shadow: var(--focus-glow);
}
.app-input--error .app-input__field {
  border-color: var(--color-danger);
}
.app-input__error {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-danger);
}
</style>
