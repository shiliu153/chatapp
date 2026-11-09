<script setup lang="ts">
import { computed, onBeforeUnmount, ref } from 'vue'
import { parseApiError } from '@/api/error'
import AppButton from '@/components/AppButton.vue'
import MessageVoice from '@/features/chat/MessageVoice.vue'
import VoiceRecordBar from '@/features/chat/VoiceRecordBar.vue'
import { VOICE_TEXT, useVoiceRecorder } from '@/features/chat/useVoiceRecorder'
import { canRecordVoice } from '@/im/self/voice'
import { useProfileStore } from '@/stores/profile'
import { PROFILE_VOICE_MAX_MS, PROFILE_VOICE_MAX_SECONDS } from './voiceIntro'

/**
 * 编辑资料页的「语音自我介绍」卡(批次 R-3 · Web)。
 *
 * 交互:点麦克风录音(最长 30 秒自动停)→ 本地试听 / 重录 / 保存语音 → 存好后变成
 * 「已保存」(试听 / 重录 / 删除)。录音状态机复用 `useVoiceRecorder`(资料侧只改上限
 * 参数),录音条是 `VoiceRecordBar`,播放条是 `MessageVoice` —— 三件都不复制第二份。
 *
 * 数据只经由 store(`uploadVoice` / `removeVoice`),本组件不直接调 http。
 */
const store = useProfileStore()

/** 已录好但还没上传的本地音频(object URL 只在本组件生命周期内有效) */
const localBlob = ref<Blob | null>(null)
const localDurationMs = ref(0)
const localUrl = ref('')
/** 上传/删除进行中:期间锁住所有按钮,避免重复提交 */
const busy = ref(false)
const hint = ref('')

/** 服务端已有的语音(没录过是 null) */
const saved = computed(() => store.profile?.voice ?? null)

const recorder = useVoiceRecorder({
  maxDurationMs: PROFILE_VOICE_MAX_MS,
  enabled: () => canRecordVoice() && !busy.value,
  // 资料侧的「发送」= 先留在本地试听,用户确认后再上传(server 只收 file)
  onSend: async (blob, durationMs) => {
    setLocal(blob, durationMs)
  },
  onNotice: (text) => {
    hint.value = text
  },
})

/** jsdom 里没有 createObjectURL,测试会打桩;拿不到就退回不可播放的占位。 */
function createPreviewUrl(blob: Blob): string {
  const create = (URL as unknown as { createObjectURL?: (target: Blob) => string })
    .createObjectURL
  return typeof create === 'function' ? create(blob) : ''
}

/** 同上,revoke 也要守卫:jsdom 里同样不存在。 */
function revokePreviewUrl(url: string): void {
  if (!url) return
  const revoke = (URL as unknown as { revokeObjectURL?: (target: string) => void })
    .revokeObjectURL
  if (typeof revoke === 'function') revoke(url)
}

function setLocal(blob: Blob, durationMs: number): void {
  revokePreviewUrl(localUrl.value)
  localBlob.value = blob
  localDurationMs.value = durationMs
  localUrl.value = createPreviewUrl(blob)
}

function clearLocal(): void {
  revokePreviewUrl(localUrl.value)
  localBlob.value = null
  localDurationMs.value = 0
  localUrl.value = ''
}

/**
 * 录音入口。能力不满足时**不能置 `disabled`**(那样点击收不到,用户不知道为什么),
 * 用 `aria-disabled` + 点击给出原因(坑灵手册 web.md「置灰别用 disabled」)。
 */
function onStartRecording(): void {
  hint.value = ''
  if (!canRecordVoice()) {
    hint.value = VOICE_TEXT.unsupported
    return
  }
  void recorder.start()
}

function onCancelRecording(): void {
  void recorder.cancel()
}

/** 停止录音:录音条上的「停止」;到 30 秒也会自动走到这里 */
function onStopRecording(): void {
  void recorder.stopAndSend()
}

/** 「重录」:丢掉本地草稿(已保存的语音不动)后重新开始 */
function onRerecord(): void {
  clearLocal()
  onStartRecording()
}

async function onSave(): Promise<void> {
  const blob = localBlob.value
  if (!blob || busy.value) return
  busy.value = true
  hint.value = ''
  try {
    await store.uploadVoice(blob)
    clearLocal()
    hint.value = '语音已保存'
  } catch (e) {
    // 失败保留本地录音,原地点「保存语音」可重试(不必重录)
    hint.value = parseApiError(e).message
  } finally {
    busy.value = false
  }
}

async function onDelete(): Promise<void> {
  if (busy.value) return
  if (!window.confirm('删除后别人就听不到这段语音了,可以重新录。')) return
  busy.value = true
  hint.value = ''
  try {
    await store.removeVoice()
    hint.value = '已删除'
  } catch (e) {
    hint.value = parseApiError(e).message
  } finally {
    busy.value = false
  }
}

onBeforeUnmount(() => {
  // 语义固定是「取消」:离开页面绝不把没确认的录音发出去
  recorder.dispose()
  revokePreviewUrl(localUrl.value)
})
</script>

<template>
  <div class="voice-card">
    <h2 class="voice-card__title">语音自我介绍</h2>
    <p class="voice-card__desc">
      录一段最长 {{ PROFILE_VOICE_MAX_SECONDS }} 秒的自我介绍,任何能看你资料的人都能听。
    </p>

    <VoiceRecordBar
      v-if="recorder.phase.value !== 'idle'"
      :phase="recorder.phase.value"
      :seconds="recorder.seconds.value"
      :max-seconds="PROFILE_VOICE_MAX_SECONDS"
      confirm-label="停止"
      sending-label="处理中…"
      @cancel="onCancelRecording"
      @send="onStopRecording"
    />

    <template v-else>
      <!-- 刚录好、还没上传:可以试听,再决定保存还是重录 -->
      <div v-if="localBlob" class="voice-card__row voice-card__row--local">
        <MessageVoice
          :url="localUrl || null"
          :duration-ms="localDurationMs"
          :max-seconds="PROFILE_VOICE_MAX_SECONDS"
        />
        <AppButton
          class="voice-card__rerecord"
          variant="ghost"
          :disabled="busy"
          @click="onRerecord"
        >
          重录
        </AppButton>
        <AppButton class="voice-card__save" :loading="busy" @click="onSave">保存语音</AppButton>
      </div>

      <!-- 已保存:试听 + 重录 / 删除 -->
      <div v-else-if="saved" class="voice-card__row voice-card__row--saved">
        <MessageVoice
          :url="saved.url"
          :duration-ms="saved.duration_ms"
          :max-seconds="PROFILE_VOICE_MAX_SECONDS"
        />
        <AppButton
          class="voice-card__rerecord"
          variant="ghost"
          :disabled="busy"
          @click="onStartRecording"
        >
          重录
        </AppButton>
        <AppButton
          class="voice-card__delete"
          variant="danger"
          :disabled="busy"
          @click="onDelete"
        >
          删除语音
        </AppButton>
      </div>

      <!-- 还没录:露出麦克风入口(点一下开录,PC 不是按住) -->
      <div v-else class="voice-card__row">
        <button
          type="button"
          class="voice-card__mic"
          :aria-disabled="!canRecordVoice()"
          aria-label="录制语音自我介绍"
          @click="onStartRecording"
        >
          🎙
        </button>
        <span class="voice-card__status">点麦克风开始录音,最长 {{ PROFILE_VOICE_MAX_SECONDS }} 秒</span>
      </div>
    </template>

    <p v-if="hint" class="voice-card__hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
.voice-card {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  padding: var(--space-lg);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
}
.voice-card__title {
  margin: 0;
  font-size: var(--text-subtitle);
  font-weight: var(--weight-semibold);
  color: var(--color-text1);
}
.voice-card__desc {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.voice-card__row {
  display: flex;
  align-items: center;
  gap: var(--space-md);
}
.voice-card__row--local,
.voice-card__row--saved {
  flex-wrap: wrap;
}
.voice-card__mic {
  flex: none;
  width: 48px;
  height: 48px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-bg-page);
  color: var(--color-text1);
  font-size: var(--text-subtitle);
  cursor: pointer;
  transition: background var(--motion-fast) var(--ease-out);
}
.voice-card__mic:hover {
  background: var(--color-divider);
}
/* 能力不满足时置灰但保留点击(点击会说明原因),所以不用 disabled */
.voice-card__mic[aria-disabled='true'] {
  color: var(--color-text3);
  cursor: default;
}
.voice-card__status {
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.voice-card__hint {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
</style>
