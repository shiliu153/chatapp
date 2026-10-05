<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue'
import type { Candidate } from '@/api/types'
import CandidateCard from './CandidateCard.vue'
import { swipeDirection } from './swipe'

const props = withDefaults(
  defineProps<{ candidate: Candidate | null; submitting?: boolean }>(),
  { submitting: false },
)
const emit = defineEmits<{ decide: ['like' | 'pass'] }>()

const offsetX = ref(0)
const dragging = ref(false)
let startX = 0

function decide(action: 'like' | 'pass') {
  if (props.submitting) return
  emit('decide', action)
}

function onPointerDown(event: PointerEvent) {
  if (props.submitting) return
  dragging.value = true
  startX = event.clientX
  window.addEventListener('pointermove', onPointerMove)
  window.addEventListener('pointerup', onPointerUp)
}

function onPointerMove(event: PointerEvent) {
  if (!dragging.value) return
  offsetX.value = event.clientX - startX
}

function onPointerUp() {
  dragging.value = false
  const action = swipeDirection(offsetX.value)
  offsetX.value = 0
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
  if (action) decide(action)
}

function onKeydown(event: KeyboardEvent) {
  // 输入框里按方向键不该触发滑卡
  const target = event.target as HTMLElement | null
  if (target && ['INPUT', 'TEXTAREA'].includes(target.tagName)) return
  if (event.key === 'ArrowRight') decide('like')
  if (event.key === 'ArrowLeft') decide('pass')
}

window.addEventListener('keydown', onKeydown)
onUnmounted(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('pointermove', onPointerMove)
  window.removeEventListener('pointerup', onPointerUp)
})

// 换卡时复位位移与动画状态
watch(
  () => props.candidate?.user_id,
  () => {
    offsetX.value = 0
  },
)

const cardStyle = computed(() => ({
  transform: `translateX(${offsetX.value}px) rotate(${offsetX.value / 24}deg)`,
  transition: dragging.value ? 'none' : 'transform var(--motion-base) var(--ease-out)',
}))
</script>

<template>
  <div class="swipe-deck">
    <div
      v-if="props.candidate"
      class="swipe-deck__stage"
      :style="cardStyle"
      @pointerdown="onPointerDown"
    >
      <CandidateCard :candidate="props.candidate" />
    </div>

    <div v-if="props.candidate" class="swipe-deck__actions">
      <button
        type="button"
        class="swipe-deck__button swipe-deck__pass"
        aria-label="不喜欢"
        :disabled="props.submitting"
        @click="decide('pass')"
      >
        ✕
      </button>
      <button
        type="button"
        class="swipe-deck__button swipe-deck__like"
        aria-label="喜欢"
        :disabled="props.submitting"
        @click="decide('like')"
      >
        ♥
      </button>
    </div>
  </div>
</template>

<style scoped>
.swipe-deck {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-lg);
  height: 100%;
  min-height: 0;
}
/* 卡片按可用高度定尺(spec §6.3):宽高比锁 3:4,窗口矮就整体缩小 */
.swipe-deck__stage {
  flex: 1;
  min-height: 0;
  aspect-ratio: 3 / 4;
  max-width: 100%;
  cursor: grab;
}
.swipe-deck__stage:active {
  cursor: grabbing;
}
.swipe-deck__actions {
  display: flex;
  gap: var(--space-xl);
  flex: none;
}
.swipe-deck__button {
  width: 56px;
  height: 56px;
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
  font-size: var(--text-title);
  cursor: pointer;
  transition:
    transform var(--motion-fast) var(--ease-out),
    color var(--motion-fast) var(--ease-out);
}
.swipe-deck__button:not(:disabled):hover {
  transform: translateY(-2px);
}
.swipe-deck__button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.swipe-deck__pass:not(:disabled):hover {
  color: var(--color-text2);
}
.swipe-deck__like:not(:disabled):hover {
  color: var(--color-brand);
}
</style>
