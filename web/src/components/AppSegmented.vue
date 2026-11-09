<script setup lang="ts" generic="T extends string">
/**
 * 三态/多态分段控件(设置页「外观」、我的数据页「周期」共用)。
 *
 * 为什么做成组件:同一套分段样式被两个页面用到,复制一份 CSS 后两边会各自漂移
 * (改一处忘另一处,暗色下的选中态最不容易发现)。这里把它收成唯一实现。
 *
 * 语义:`role="group"` + 每个按钮 `aria-pressed`,键盘 Tab 可逐个聚焦;
 * 选中项只靠 `aria-pressed="true"` 表达,样式也从该属性出发(不另加 class)。
 */
const props = defineProps<{
  /** 选项;`value` 是回传给父组件的值,`label` 是展示文案 */
  options: readonly { value: T; label: string }[]
  /** 当前选中值(受控) */
  modelValue: T
  /** 无可见标题时的分组名,给读屏用 */
  label: string
}>()

const emit = defineEmits<{ 'update:modelValue': [value: T] }>()

/** 点已选中的项不发事件:避免父组件拿同值重复请求一次接口。 */
function pick(value: T): void {
  if (value === props.modelValue) return
  emit('update:modelValue', value)
}
</script>

<template>
  <div class="app-segmented" role="group" :aria-label="props.label">
    <button
      v-for="option in props.options"
      :key="option.value"
      class="app-segmented__segment"
      type="button"
      :aria-pressed="props.modelValue === option.value"
      @click="pick(option.value)"
    >
      {{ option.label }}
    </button>
  </div>
</template>

<style scoped>
.app-segmented {
  display: flex;
  gap: var(--space-xs);
  padding: var(--space-xs);
  border-radius: var(--radius-chip);
  background: var(--hover-overlay);
}
.app-segmented__segment {
  flex: 1;
  height: 36px;
  border: none;
  border-radius: var(--radius-chip);
  background: transparent;
  color: var(--color-text2);
  font-family: inherit;
  font-size: var(--text-body);
  cursor: pointer;
  transition:
    background var(--motion-fast) var(--ease-out),
    color var(--motion-fast) var(--ease-out);
}
.app-segmented__segment:hover {
  background: var(--hover-overlay-strong);
}
.app-segmented__segment[aria-pressed='true'] {
  background: var(--color-bg-card);
  color: var(--color-brand);
  font-weight: var(--weight-semibold);
}
</style>
