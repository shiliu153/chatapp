<script setup lang="ts">
import type { VoicePhase } from './useVoiceRecorder'

/**
 * 录音时替换整个输入栏的三段式:取消 | 计时 | 确认。
 *
 * 聊天页用默认文案(取消 / 发送);资料页「语音自我介绍」传入自己的上限与文案
 * (30 秒 / 停止 / 处理中…),不复制一份布局。
 */
const props = withDefaults(
  defineProps<{
    phase: VoicePhase
    seconds: number
    /** 计时上限(秒):只影响显示,真正的自动停由 useVoiceRecorder 的 maxDurationMs 决定 */
    maxSeconds?: number
    cancelLabel?: string
    confirmLabel?: string
    sendingLabel?: string
  }>(),
  {
    maxSeconds: 60,
    cancelLabel: '取消',
    confirmLabel: '发送',
    sendingLabel: '发送中…',
  },
)
defineEmits<{ cancel: []; send: [] }>()

function clock(total: number): string {
  const safe = Math.max(0, Math.min(props.maxSeconds, total))
  return `${String(Math.floor(safe / 60)).padStart(2, '0')}:${String(safe % 60).padStart(2, '0')}`
}
</script>

<template>
  <div class="voice-bar" role="group" aria-label="录音中">
    <button
      type="button"
      class="voice-bar__cancel"
      :disabled="props.phase === 'sending'"
      @click="$emit('cancel')"
    >
      {{ props.cancelLabel }}
    </button>

    <span class="voice-bar__clock">
      <span class="voice-bar__dot" :class="{ 'voice-bar__dot--still': props.phase === 'sending' }" />
      <span class="voice-bar__seconds">{{ clock(props.seconds) }}</span>
    </span>

    <button
      type="button"
      class="voice-bar__send"
      :disabled="props.phase === 'sending'"
      @click="$emit('send')"
    >
      {{ props.phase === 'sending' ? props.sendingLabel : props.confirmLabel }}
    </button>
  </div>
</template>

<style scoped>
.voice-bar {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
}

.voice-bar__cancel,
.voice-bar__send {
  flex: none;
  height: 40px;
  padding: 0 var(--space-lg);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-input);
  background: var(--color-bg-card);
  color: var(--color-text1);
  font-size: var(--text-caption);
  cursor: pointer;
}

.voice-bar__cancel:disabled,
.voice-bar__send:disabled {
  color: var(--color-text3);
  cursor: default;
}

.voice-bar__send {
  border-color: var(--color-brand);
  background: var(--color-brand);
  color: var(--color-bg-card);
}

.voice-bar__send:disabled {
  border-color: var(--color-divider);
  background: var(--color-divider);
}

.voice-bar__clock {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  color: var(--color-text1);
}

.voice-bar__dot {
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--color-brand);
  animation: voice-bar-pulse var(--motion-loop) var(--ease-out) infinite;
}

.voice-bar__dot--still {
  animation: none;
}

.voice-bar__seconds {
  font-size: var(--text-subtitle);
  font-variant-numeric: tabular-nums;
}

@keyframes voice-bar-pulse {
  50% {
    opacity: 0.35;
  }
}

@media (prefers-reduced-motion: reduce) {
  .voice-bar__dot {
    animation: none;
  }
}
</style>
