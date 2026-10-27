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
    :style="{ width: `${width}px` }"
    :aria-label="`播放语音 ${seconds} 秒`"
    @click="toggle"
  >
    <span class="voice__icon">{{ playing ? '❚❚' : '▶' }}</span>
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
.voice__seconds {
  font-size: var(--text-body);
}
</style>
