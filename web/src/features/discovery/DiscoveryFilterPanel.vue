<script setup lang="ts">
import { ref } from 'vue'
import AppButton from '@/components/AppButton.vue'
import AppInput from '@/components/AppInput.vue'
import TagPicker from '@/features/profile/TagPicker.vue'
import type { DiscoveryFilters, Preference } from '@/api/types'

/**
 * 发现页筛选面板(批次 S,discovery.md §3.1)。
 *
 * 传进来的 `initial` 是**当前已生效的筛选**(空对象 = 完全按偏好),面板打开时
 * 的默认值 = `initial` 覆盖 `preference` —— 也就是「现在实际在用的范围」。
 *
 * 语义要点:面板上的值**减去偏好默认值**才是要发出去的筛选对象。改过的字段才发,
 * 没改的一个参数都不发(后端对缺省字段继续沿用偏好)。所以「只改城市」时
 * `age_min` / `age_max` 必须缺席,不能把面板里的默认年龄区间当成筛选条件发出去。
 */
const props = defineProps<{
  /** 当前「想找的人」偏好:面板默认值的来源(设置页仍是偏好的唯一持久化入口) */
  preference: Preference
  /** 已经生效的筛选;空对象 = 完全按偏好 */
  initial: DiscoveryFilters
}>()

const emit = defineEmits<{ close: []; apply: [DiscoveryFilters]; reset: [] }>()

/** 后端口径:年龄筛选只接受 18–99 的整数(discovery.md §3.1) */
const AGE_MIN = 18
const AGE_MAX = 99

function clampAge(age: number): number {
  return Math.min(AGE_MAX, Math.max(AGE_MIN, age))
}

const ageMin = ref(String(props.initial.age_min ?? clampAge(props.preference.age_min)))
const ageMax = ref(String(props.initial.age_max ?? clampAge(props.preference.age_max)))
const city = ref(props.initial.city ?? props.preference.city)
const tagIds = ref<number[]>([...(props.initial.tag_ids ?? [])])
const error = ref('')

/**
 * 把面板上的值**减去偏好**得到筛选对象。
 *
 * 三个「不发」的情形:
 * 1. 年龄区间 == 偏好区间 → 不发 `age_min`/`age_max`(等价,少发更清楚);
 * 2. 城市留空或与偏好相同 → 不发 `city`(空串后端也当没传,这里干脆不发);
 * 3. 没选标签 → 不发 `tag_ids`(偏好里没有标签项,不选就是「不筛」)。
 */
function compose(): DiscoveryFilters {
  const min = clampAge(Number(ageMin.value))
  const max = clampAge(Number(ageMax.value))
  const ageChanged = min !== clampAge(props.preference.age_min) || max !== clampAge(props.preference.age_max)
  const cityText = city.value.trim()
  const next: DiscoveryFilters = {}
  if (ageChanged) {
    next.age_min = min
    next.age_max = max
  }
  if (cityText && cityText !== props.preference.city) next.city = cityText
  if (tagIds.value.length > 0) next.tag_ids = [...tagIds.value].sort((a, b) => a - b)
  return next
}

/**
 * 「应用」:先本地挡掉必然 400 的组合(非整数 / 越界 / 下限大于上限),
 * 免得用户点了没反应还得看后端错误文案。
 */
function onApply() {
  error.value = ''
  const min = Number(ageMin.value)
  const max = Number(ageMax.value)
  if (!Number.isInteger(min) || !Number.isInteger(max) || min < AGE_MIN || max > AGE_MAX || min > max) {
    error.value = `年龄区间需为 ${AGE_MIN}–${AGE_MAX} 的整数,且下限不大于上限`
    return
  }
  emit('apply', compose())
}
</script>

<template>
  <div
    class="filter-panel"
    role="dialog"
    aria-modal="true"
    aria-label="筛选"
    @click.self="emit('close')"
  >
    <div class="filter-panel__card">
      <header class="filter-panel__header">
        <div>
          <h2 class="filter-panel__title">筛选</h2>
          <p class="filter-panel__hint">只影响这一次的候选池,不会改掉「想找的人」设置</p>
        </div>
        <button
          type="button"
          class="filter-panel__close"
          aria-label="关闭"
          @click="emit('close')"
        >
          ×
        </button>
      </header>

      <div class="filter-panel__body">
        <p class="filter-panel__label">年龄区间</p>
        <div class="filter-panel__ages">
          <AppInput
            v-model="ageMin"
            class="filter-panel__age"
            type="number"
            inputmode="numeric"
            placeholder="下限"
          />
          <span class="filter-panel__dash">—</span>
          <AppInput
            v-model="ageMax"
            class="filter-panel__age"
            type="number"
            inputmode="numeric"
            placeholder="上限"
          />
        </div>

        <p class="filter-panel__label">城市</p>
        <AppInput v-model="city" placeholder="留空 = 沿用偏好" :maxlength="50" />

        <p class="filter-panel__label">兴趣标签(可多选,命中其一即可)</p>
        <TagPicker v-model="tagIds" />

        <p v-if="error" class="filter-panel__error">{{ error }}</p>
      </div>

      <footer class="filter-panel__actions">
        <AppButton
          class="filter-panel__reset"
          variant="ghost"
          block
          @click="emit('reset')"
        >
          重置
        </AppButton>
        <AppButton class="filter-panel__apply" block @click="onApply">应用</AppButton>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.filter-panel {
  position: fixed;
  inset: 0;
  z-index: 150;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--scrim-strong);
}
.filter-panel__card {
  display: flex;
  flex-direction: column;
  width: min(440px, calc(100vw - var(--space-xxl) * 2));
  max-height: 82vh;
  border-radius: var(--radius-sheet);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-floating-bar);
}
.filter-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--space-md);
  padding: var(--space-xl) var(--space-xl) var(--space-sm);
}
.filter-panel__title {
  margin: 0;
  font-size: var(--text-title);
  font-weight: var(--weight-bold);
  color: var(--color-text1);
}
.filter-panel__hint {
  margin: var(--space-xs) 0 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.filter-panel__close {
  flex: none;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--radius-full);
  background: transparent;
  color: var(--color-text2);
  font-size: var(--text-title);
  line-height: 1;
  cursor: pointer;
}
.filter-panel__close:hover {
  background: var(--hover-overlay);
}
/* 内容超高时只有这一块滚动:滚动容器在面板里部,不接管指针事件
   (别在它上面绑 touchmove / preventDefault,否则矮屏上会吞掉控件的点击) */
.filter-panel__body {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  min-height: 0;
  padding: var(--space-sm) var(--space-xl) var(--space-lg);
  overflow-y: auto;
}
.filter-panel__label {
  margin: var(--space-sm) 0 0;
  font-size: var(--text-caption);
  font-weight: var(--weight-semibold);
  color: var(--color-text2);
}
.filter-panel__ages {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
}
.filter-panel__age {
  flex: 1;
}
.filter-panel__dash {
  color: var(--color-text3);
}
.filter-panel__error {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-danger);
}
.filter-panel__actions {
  display: flex;
  gap: var(--space-md);
  padding: var(--space-md) var(--space-xl) var(--space-xl);
}
.filter-panel__actions > * {
  flex: 1;
}
</style>
