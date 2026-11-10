<script setup lang="ts">
/**
 * 聊天图片全屏查看(批次 T 补齐)。
 *
 * 之前它收了 `urls[] + index` 却只渲染一张:参数齐了、交互全是空的。现在补三件事:
 * ① 缩放(滚轮 + 双击,`transform: scale`);② 左右切(`←` / `→` 键 + 左右按钮);
 * ③ 页码 `i / n`。
 *
 * 当前下标是**组件内部状态**(初值取 `props.index`)而不是受控 prop:聊天页只在
 * 「打开」那一刻关心从哪张开始,之后切换是纯查看行为,没必要再往上传一层事件
 * (传上去还得再同步回来,反而多一条会打架的回路)。
 */
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'

const props = defineProps<{ urls: string[]; index: number }>()
const emit = defineEmits<{ close: [] }>()

/** 缩放区间与滚轮步长:1x 是「刚好放得下」,4x 足够看清聊天截图里的字 */
const MIN_SCALE = 1
const MAX_SCALE = 4
const ZOOM_STEP = 0.25
/** 双击放大到的倍数 */
const DOUBLE_CLICK_SCALE = 2

const current = ref(props.index)
const scale = ref(MIN_SCALE)

const total = computed(() => props.urls.length)
const src = computed(() => props.urls[current.value] ?? '')
const canSwitch = computed(() => total.value > 1)
const zoomed = computed(() => scale.value > MIN_SCALE)

/** 外部换了起始下标(例如聊天页又打开了另一张)就回到那一张,并复位缩放。 */
watch(
  () => props.index,
  (next) => {
    current.value = next
    scale.value = MIN_SCALE
  },
)

function clampScale(value: number): number {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, value))
}

/** 缩放:`delta > 0` 放大。到边界就不动,不报错、不抖动。 */
function zoomBy(delta: number): void {
  scale.value = clampScale(Number((scale.value + delta).toFixed(2)))
}

/** 切到上一张 / 下一张(不首尾循环:到头就是到头,与页码对得上)。 */
function go(step: number): void {
  if (!canSwitch.value) return
  const next = current.value + step
  if (next < 0 || next >= total.value) return
  current.value = next
  // 换一张就复位缩放:把上一张的倍数套到下一张上,看到的往往是糊掉的局部
  scale.value = MIN_SCALE
}

/** 双击在图 1x / 2x 之间来回 */
function toggleZoom(): void {
  scale.value = zoomed.value ? MIN_SCALE : DOUBLE_CLICK_SCALE
}

function onWheel(event: WheelEvent): void {
  zoomBy(event.deltaY < 0 ? ZOOM_STEP : -ZOOM_STEP)
}

function onKeydown(event: KeyboardEvent): void {
  if (event.key === 'Escape') {
    emit('close')
    return
  }
  if (event.key === 'ArrowLeft') {
    event.preventDefault()
    go(-1)
    return
  }
  if (event.key === 'ArrowRight') {
    event.preventDefault()
    go(1)
  }
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onUnmounted(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div class="image-viewer" role="dialog" aria-modal="true">
    <!-- 遮罩铺满整屏且在图片之下:点图片不会冒泡到遮罩 -->
    <div class="image-viewer__mask" @click="emit('close')" />

    <button
      v-if="canSwitch"
      type="button"
      class="image-viewer__nav image-viewer__nav--prev"
      aria-label="上一张"
      data-testid="viewer-prev"
      @click="go(-1)"
    >
      ‹
    </button>

    <img
      class="image-viewer__img"
      :src="src"
      alt="查看大图"
      :class="{ 'image-viewer__img--zoomed': zoomed }"
      :style="{ transform: `scale(${scale})` }"
      @dblclick="toggleZoom"
      @wheel.prevent="onWheel"
    />

    <button
      v-if="canSwitch"
      type="button"
      class="image-viewer__nav image-viewer__nav--next"
      aria-label="下一张"
      data-testid="viewer-next"
      @click="go(1)"
    >
      ›
    </button>

    <p v-if="canSwitch" class="image-viewer__page" data-testid="viewer-page">
      {{ current + 1 }} / {{ total }}
    </p>
  </div>
</template>

<style scoped>
.image-viewer {
  position: fixed;
  inset: 0;
  z-index: 120;
  display: flex;
  align-items: center;
  justify-content: center;
}
.image-viewer__mask {
  position: absolute;
  inset: 0;
  background: var(--color-photo-scrim);
  cursor: zoom-out;
}
.image-viewer__img {
  position: relative;
  z-index: 1;
  max-width: 92vw;
  max-height: 92vh;
  border-radius: var(--radius-image);
  box-shadow: var(--shadow-floating-bar);
  cursor: zoom-in;
  transition: transform var(--motion-fast) var(--ease-out);
}
/* 放大之后指针改成「缩小」:同一个位置再点一下就是还原 */
.image-viewer__img--zoomed {
  cursor: zoom-out;
}
/* 左右切换:贴边居中,不抢图片的视线 */
.image-viewer__nav {
  position: absolute;
  top: 50%;
  z-index: 2;
  width: 48px;
  height: 48px;
  border: none;
  border-radius: var(--radius-full);
  background: var(--hover-overlay-strong);
  color: var(--color-text1);
  font-size: var(--text-title);
  line-height: 1;
  cursor: pointer;
  transform: translateY(-50%);
}
.image-viewer__nav:hover {
  background: var(--scrim-strong);
}
.image-viewer__nav--prev {
  left: var(--space-section-gap);
}
.image-viewer__nav--next {
  right: var(--space-section-gap);
}
/* 页码:底部居中半透明药丸,照片深浅都不影响可读 */
.image-viewer__page {
  position: absolute;
  bottom: var(--space-section-gap);
  left: 50%;
  z-index: 2;
  margin: 0;
  padding: var(--space-xs) var(--space-md);
  border-radius: var(--radius-full);
  background: var(--scrim-strong);
  color: var(--color-bg-card);
  font-size: var(--text-badge);
  transform: translateX(-50%);
}
</style>
