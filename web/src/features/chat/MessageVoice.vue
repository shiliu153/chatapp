<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import type { ChatMessage } from '@/im/types'
import { playVoice, stopVoice } from '@/im/voicePlayer'

const props = defineProps<{ message: ChatMessage }>()

const playing = ref(false)
const seconds = computed(() =>
  Math.min(60, Math.max(1, Math.round((props.message.voiceDurationMs ?? 0) / 1000))),
)
/** 宽度随时长增长,并保证图标 + 秒数放得下 */
const width = computed(() => Math.min(200, Math.max(96, 72 + seconds.value * 2)))
const url = computed(() => props.message.voiceUrl ?? '')
/** 失败或发送中的气泡还没有签名地址,只能渲染占位,不能当成可播放 */
const playable = computed(() => Boolean(url.value))

function toggle(): void {
  if (!url.value) return
  if (playing.value) {
    stopVoice()
    playing.value = false
    return
  }
  playing.value = true
  playVoice(url.value, () => {
    playing.value = false
  })
}

onBeforeUnmount(() => {
  if (playing.value) stopVoice()
})
</script>

<template>
  <button
    type="button"
    class="voice"
    :class="{ 'voice--empty': !playable }"
    :style="{ width: `${width}px` }"
    :aria-label="playable ? `播放语音 ${seconds} 秒` : `语音 ${seconds} 秒，暂不可播放`"
    :aria-disabled="!playable"
    @click="toggle"
  >
    <span class="voice__icon">{{ !playable ? '🎙' : playing ? '❚❚' : '▶' }}</span>
    <span class="voice__seconds">{{ seconds }}″</span>
  </button>
</template>

<style scoped>
.voice {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: var(--space-sm);
  min-height: 28px;
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
  padding: 0;
}
.voice__icon {
  font-size: var(--text-badge);
  line-height: 1;
}
/* 不可播放时保持同宽,但去掉可点击暗示 */
.voice--empty {
  cursor: default;
  opacity: 0.6;
}
.voice__seconds {
  font-size: var(--text-body);
}
</style>
