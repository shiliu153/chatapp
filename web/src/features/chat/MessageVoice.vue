<script setup lang="ts">
/**
 * 语音播放条:▶/❚❚ + **可拖进度条** + 秒数 + 倍速按钮(批次 T 补齐)。
 *
 * 之前只有「播放/暂停图标 + 总秒数」,`voicePlayer` 的注释还写着「不做播放进度」。
 * 现在补三条:① `timeupdate` 推的进度;② 拖动松手 `seek`(用 `currentTime`);
 * ③ `1.0x / 1.5x / 2.0x` 循环的倍速(用 `playbackRate`)。
 *
 * 聊天气泡与「资料语音自我介绍」(编辑页试听 / 他人资料页播放)共用同一份播放逻辑
 * (`@/im/voicePlayer` 全局单例,同一时刻只播一条),所以这里只收 `url` + `durationMs`,
 * 不依赖 `ChatMessage` 整条消息。
 */
import { computed, onBeforeUnmount, ref } from 'vue'
import { playVoice, seekVoice, setVoiceRate, stopVoice } from '@/im/voicePlayer'
import type { VoiceProgress } from '@/im/voicePlayer'

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

/** 倍速档位:点一下 +1 档,最后一档回到 1.0x */
const RATES = [1, 1.5, 2]
/** 进度条用整数刻度(0–1000)而不是浮点:滑块的 `value` 是字符串,整数最不容易抖 */
const SLIDER_TICKS = 1000

const playing = ref(false)
/** 播放失败(链接失效/浏览器拦自动播放):气泡改成「播放失败」,再点一次即重试 */
const failed = ref(false)
/** 播放进度(0–1),由 `timeupdate` 推 */
const progress = ref(0)
/** 已播毫秒数:进度条旁边显示「0:03 / 13″」 */
const elapsedMs = ref(0)
/** 当前倍速(换一条播放 / 播完都回到 1.0x) */
const rate = ref(1)
/** 拖动中:进度跟手,不让 `timeupdate` 把滑块拽回去 */
const dragging = ref(false)
const dragRatio = ref(0)

const seconds = computed(() =>
  Math.min(props.maxSeconds, Math.max(1, Math.round(props.durationMs / 1000))),
)
/** 宽度随时长增长,并保证图标 + 进度条 + 秒数 + 倍速放得下 */
const width = computed(() => Math.min(240, Math.max(132, 104 + seconds.value * 2)))
const playable = computed(() => Boolean(props.url))
const rateLabel = computed(() => `${rate.value.toFixed(1)}x`)
const sliderValue = computed(() =>
  Math.round((dragging.value ? dragRatio.value : progress.value) * SLIDER_TICKS),
)
const elapsedLabel = computed(() =>
  formatMs(dragging.value ? dragRatio.value * props.durationMs : elapsedMs.value),
)
/** 播放中的文案「0:03 / 13″」;停着的时候只显示总时长。 */
const timeLabel = computed(() =>
  playing.value ? `${elapsedLabel.value} / ${seconds.value}″` : `${seconds.value}″`,
)

function formatMs(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  return `0:${String(total).padStart(2, '0')}`
}

/** 一次播放结束(自然播完 / 被别的语音顶掉 / 被自己暂停):图标、进度、倍速全部复位。 */
function onEnded(): void {
  playing.value = false
  progress.value = 0
  elapsedMs.value = 0
  dragging.value = false
  rate.value = 1
}

function onError(): void {
  playing.value = false
  failed.value = true
}

function onProgress(next: VoiceProgress): void {
  if (dragging.value) return
  progress.value = next.ratio
  elapsedMs.value = next.currentMs
}

function toggle(): void {
  if (!props.url) return
  if (playing.value) {
    stopVoice()
    playing.value = false
    return
  }
  failed.value = false
  playing.value = true
  progress.value = 0
  elapsedMs.value = 0
  playVoice(props.url, onEnded, onError, onProgress)
  // 非 1.0x 时要在开播后立刻设上:新建的 Audio 元素默认就是 1.0x
  if (rate.value !== 1) setVoiceRate(rate.value)
}

/**
 * 倍速:1.0x → 1.5x → 2.0x → 1.0x。
 *
 * 暂停时点也直接记在 `rate` 上,`toggle()` 开播后立刻 `setVoiceRate`,
 * 所以「先选 2.0x 再点播放」也是 2 倍速。
 */
function cycleRate(): void {
  const index = RATES.indexOf(rate.value)
  rate.value = RATES[(index + 1) % RATES.length]
  setVoiceRate(rate.value)
}

/** 拖动中:只更新滑块位置(跟手),不 seek —— 边拖边 seek 会让音频卡成一段一段。 */
function onSliderInput(event: Event): void {
  const value = Number((event.target as HTMLInputElement).value)
  dragging.value = true
  dragRatio.value = Math.min(1, Math.max(0, value / SLIDER_TICKS))
}

/** 松手:按比例 seek(`currentTime`),进度条停在拖到的位置。 */
function onSliderCommit(): void {
  if (!dragging.value) return
  dragging.value = false
  progress.value = dragRatio.value
  elapsedMs.value = dragRatio.value * props.durationMs
  seekVoice(dragRatio.value)
}

onBeforeUnmount(() => {
  if (playing.value) stopVoice()
})
</script>

<template>
  <div class="voice" :class="{ 'voice--empty': !playable }" :style="{ width: `${width}px` }">
    <button
      type="button"
      class="voice__play"
      :aria-label="
        !playable
          ? `语音 ${seconds} 秒，暂不可播放`
          : failed
            ? '播放失败，点击重试'
            : playing
              ? '暂停语音'
              : `播放语音 ${seconds} 秒`
      "
      :aria-disabled="!playable"
      @click="toggle"
    >
      <span class="voice__icon">{{ !playable ? '🎙' : playing ? '❚❚' : failed ? '⚠' : '▶' }}</span>
    </button>

    <input
      class="voice__progress"
      type="range"
      min="0"
      :max="SLIDER_TICKS"
      :value="sliderValue"
      :disabled="!playing"
      aria-label="播放进度"
      data-testid="voice-progress"
      @input="onSliderInput"
      @change="onSliderCommit"
    />

    <span class="voice__seconds" :class="{ 'voice__seconds--failed': failed }">
      {{ failed ? '播放失败,点击重试' : timeLabel }}
    </span>

    <button
      v-if="playable"
      type="button"
      class="voice__rate"
      data-testid="voice-rate"
      :aria-label="`播放速度 ${rateLabel}`"
      @click="cycleRate"
    >
      {{ rateLabel }}
    </button>
  </div>
</template>

<style scoped>
.voice {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  min-height: 28px;
  border: none;
  background: none;
  color: inherit;
  font: inherit;
}
/* 播放/暂停按钮:只包图标,点击区域仍然按 24px 给足 */
.voice__play {
  flex: none;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0;
  border: none;
  background: none;
  color: inherit;
  font: inherit;
  cursor: pointer;
}
.voice__icon {
  font-size: var(--text-badge);
  line-height: 1;
}
/* 不可播放时保持同宽,但去掉可点击暗示 */
.voice--empty .voice__play {
  cursor: default;
  opacity: 0.6;
}
/* 进度条:用 accent-color 跟随主色,暗色主题下也由 token 覆盖 */
.voice__progress {
  flex: 1;
  min-width: 0;
  height: 16px;
  accent-color: var(--color-brand);
  background: none;
  cursor: pointer;
}
.voice__progress:disabled {
  cursor: default;
  opacity: 0.5;
}
.voice__seconds {
  flex: none;
  font-size: var(--text-body);
  white-space: nowrap;
}
.voice__seconds--failed {
  color: var(--color-danger);
  font-size: var(--text-caption);
}
/* 倍速:小药丸,一眼看出当前档位 */
.voice__rate {
  flex: none;
  padding: 0 var(--space-xs);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  color: inherit;
  font: inherit;
  font-size: var(--text-badge);
  line-height: 1.6;
  cursor: pointer;
}
.voice__rate:hover {
  background: var(--hover-overlay);
}
</style>
