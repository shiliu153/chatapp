<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { playVoice, stopVoice } from '@/im/voicePlayer'

/**
 * 语音播放条:▶/❚❚ + 秒数。
 *
 * 聊天气泡与「资料语音自我介绍」(编辑页试听 / 他人资料页播放)共用同一份播放逻辑
 * (`@/im/voicePlayer` 全局单例,同一时刻只播一条),所以这里只收 `url` + `durationMs`,
 * 不再依赖 `ChatMessage` 整条消息。
 */
const props = withDefaults(
  defineProps<{
    /** 播放地址;空 = 还不能播(失败/发送中的气泡、本地录音还没生成 objectURL) */
    url: string | null
    /** 时长(毫秒) */
    durationMs: number
    /** 显示上限(秒):聊天 60,资料语音 30 */
    maxSeconds?: number
  }>(),
  { maxSeconds: 60 },
)

const playing = ref(false)
/** 播放失败(链接失效/浏览器拦自动播放):气泡改成「播放失败」,再点一次即重试 */
const failed = ref(false)
const seconds = computed(() =>
  Math.min(props.maxSeconds, Math.max(1, Math.round(props.durationMs / 1000))),
)
/** 宽度随时长增长,并保证图标 + 秒数放得下 */
const width = computed(() => Math.min(200, Math.max(96, 72 + seconds.value * 2)))
const playable = computed(() => Boolean(props.url))

function toggle(): void {
  if (!props.url) return
  if (playing.value) {
    stopVoice()
    playing.value = false
    return
  }
  failed.value = false
  playing.value = true
  playVoice(
    props.url,
    () => {
      playing.value = false
    },
    () => {
      playing.value = false
      failed.value = true
    },
  )
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
    :aria-label="
      !playable
        ? `语音 ${seconds} 秒，暂不可播放`
        : failed
          ? '播放失败，点击重试'
          : `播放语音 ${seconds} 秒`
    "
    :aria-disabled="!playable"
    @click="toggle"
  >
    <span class="voice__icon">{{ !playable ? '🎙' : playing ? '❚❚' : failed ? '⚠' : '▶' }}</span>
    <span class="voice__seconds" :class="{ 'voice__seconds--failed': failed }">
      {{ failed ? '播放失败,点击重试' : `${seconds}″` }}
    </span>
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
.voice__seconds--failed {
  color: var(--color-danger);
  font-size: var(--text-caption);
}
</style>
