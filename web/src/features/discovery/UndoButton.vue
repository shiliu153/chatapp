<script setup lang="ts">
import { computed } from 'vue'

/**
 * 撤销上一次滑卡的圆钮 + 30 秒倒计时环(discovery.md §3.9)。
 *
 * 环的长度就是「还剩多久」:满窗为整圈,归零就只剩灰色描边、按钮置灰。
 * 组件本身不碰 store 也不计时 —— 秒数与进度都由发现页从 store 传进来,
 * 这样倒计时状态只有一份,单测也能直接喂值。
 */
const props = withDefaults(
  defineProps<{
    /** 剩余秒数,0 = 窗口已过(置灰) */
    secondsLeft: number
    /** 环的进度,1 = 满 30 秒,0 = 已过期 */
    progress: number
    /** 正在请求撤销:防连点 */
    busy?: boolean
  }>(),
  { busy: false },
)

const emit = defineEmits<{ undo: [] }>()

/** 环的半径与周长(viewBox 40×40,描边 3,留 1px 余量不被裁) */
const RADIUS = 17
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

const disabled = computed(() => props.busy || props.secondsLeft <= 0)
const dashOffset = computed(
  () => CIRCUMFERENCE * (1 - Math.min(1, Math.max(0, props.progress))),
)
const label = computed(() =>
  disabled.value ? '撤销上一次滑卡(已超过 30 秒)' : `撤销上一次滑卡,还剩 ${props.secondsLeft} 秒`,
)

function onClick(): void {
  if (disabled.value) return
  emit('undo')
}
</script>

<template>
  <button
    type="button"
    class="undo-button"
    :class="{ 'undo-button--disabled': disabled }"
    :disabled="disabled"
    :aria-label="label"
    :title="label"
    @click="onClick"
  >
    <svg class="undo-button__ring" viewBox="0 0 40 40" aria-hidden="true">
      <circle
        class="undo-button__track"
        cx="20"
        cy="20"
        :r="RADIUS"
      />
      <circle
        class="undo-button__bar"
        cx="20"
        cy="20"
        :r="RADIUS"
        :stroke-dasharray="CIRCUMFERENCE"
        :stroke-dashoffset="dashOffset"
      />
    </svg>
    <span class="undo-button__glyph" aria-hidden="true">↺</span>
  </button>
</template>

<style scoped>
.undo-button {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  padding: 0;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  color: var(--color-brand);
  cursor: pointer;
  transition: transform var(--motion-fast) var(--ease-out);
}
.undo-button:not(:disabled):hover {
  transform: translateY(-2px);
}
.undo-button--disabled {
  color: var(--color-text3);
  cursor: not-allowed;
}
.undo-button__ring {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  transform: rotate(-90deg);
}
.undo-button__track,
.undo-button__bar {
  fill: none;
  stroke-width: 3;
}
.undo-button__track {
  stroke: var(--color-divider);
}
.undo-button__bar {
  stroke: var(--color-brand);
  stroke-linecap: round;
  transition: stroke-dashoffset var(--motion-medium) linear;
}
.undo-button--disabled .undo-button__bar {
  stroke: var(--color-divider);
}
.undo-button__glyph {
  font-size: var(--text-subtitle);
  line-height: 1;
}
@media (prefers-reduced-motion: reduce) {
  .undo-button,
  .undo-button__bar {
    transition: none;
  }
}
</style>
