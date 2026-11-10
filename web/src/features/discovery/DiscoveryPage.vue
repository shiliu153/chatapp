<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import AppToast from '@/components/AppToast.vue'
import { useToast } from '@/composables/useToast'
import type { DiscoveryFilters, Preference } from '@/api/types'
import { useDiscoveryStore } from '@/stores/discovery'
import { usePresenceStore } from '@/stores/presence'
import { useProfileStore } from '@/stores/profile'
import DailyStrip from './DailyStrip.vue'
import DiscoveryFilterPanel from './DiscoveryFilterPanel.vue'
import LikesEntry from './LikesEntry.vue'
import MatchesList from './MatchesList.vue'
import MatchMoment from './MatchMoment.vue'
import SwipeDeck from './SwipeDeck.vue'
import UndoButton from './UndoButton.vue'
import VisitsEntry from './VisitsEntry.vue'

/**
 * 偏好还没拉回来时的占位默认值:与后端 `Preference` 的默认一致(不限性别 / 18–99 / 不限城市)。
 * 守卫进发现页前一般已经 `GET /users/me` 过,这里只是兜底,不会把默认值当成用户偏好写回去。
 */
const DEFAULT_PREFERENCE: Preference = { target_gender: null, age_min: 18, age_max: 99, city: '' }

const store = useDiscoveryStore()
const presence = usePresenceStore()
const profileStore = useProfileStore()
const router = useRouter()
/** 撤销/划卡的结果提示(「已撤销」),2 秒后自动消失 */
const toast = useToast(2000)

/** 筛选面板开关:面板用 `v-if` 挂载,每次打开都按「当前筛选 → 偏好」重新取默认值 */
const filterOpen = ref(false)
const filterPreference = computed<Preference>(
  () => profileStore.profile?.preference ?? DEFAULT_PREFERENCE,
)

const showEmpty = computed(() => !store.loading && !store.error && store.exhausted)
const currentOnline = computed(() => {
  const id = store.current?.user_id
  return id ? presence.isOnline(id) : false
})

// 只关心当前这张卡:在线状态每 45 秒由 presence store 自己刷新
watch(
  () => store.current?.user_id,
  (id) => {
    if (id) presence.track('candidates', [id])
  },
  { immediate: true },
)

onMounted(() => {
  store.loadCandidates()
  // 额度只在挂载时对一次账:之后成功 like 本地递减、撤销退回,不必每滑一次多打一个请求
  store.loadQuota()
  // 今日精选每天固定一批(discovery.md §3.11);失败就整块不渲染,不当错误抛给用户
  store.loadDaily()
  // 筛选面板的默认值来自偏好;正常由路由守卫拉过,兜底再拉一次
  if (!profileStore.profile) profileStore.load().catch(() => {})
})

/** 应用筛选:面板已经把「没改过的字段」减掉了,这里只负责换筛选态并重拉候选池 */
async function onApplyFilters(next: DiscoveryFilters) {
  filterOpen.value = false
  await store.applyFilters(next)
}

/** 重置 = 回到完全按偏好(请求里不带任何筛选参数) */
async function onResetFilters() {
  filterOpen.value = false
  await store.resetFilters()
}

async function onDecide(action: 'like' | 'pass') {
  await store.decide(action)
}

/** 撤销:成功由 store 把卡放回卡堆,这里只负责提示「已撤销」 */
async function onUndo() {
  if (await store.undo()) toast.show('已撤销')
}

/** 「去聊天」:先关掉情感时刻再跳,避免残留遮罩 */
function onChat() {
  const target = store.matched
  store.dismissMatched()
  if (target) router.push({ name: 'chat', params: { peerId: `u${target.user_id}` } })
}
</script>

<template>
  <section class="discovery">
    <div class="discovery__entries">
      <LikesEntry />
      <VisitsEntry />
    </div>
    <MatchesList />

    <div class="discovery__toolbar">
      <button
        type="button"
        class="discovery__filter"
        :class="{ 'discovery__filter--active': store.filtersActive }"
        :aria-label="store.filtersActive ? '筛选,已生效' : '筛选'"
        @click="filterOpen = true"
      >
        <svg class="discovery__filter-icon" viewBox="0 0 24 24" aria-hidden="true">
          <path
            d="M4 7h16M7 12h10M10 17h4"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
          />
        </svg>
        筛选
      </button>
      <p v-if="store.quotaVisible" class="discovery__quota">{{ store.quotaText }}</p>
    </div>

    <DailyStrip />

    <div v-if="store.undoVisible" class="discovery__status">
      <UndoButton
        v-if="store.undoVisible"
        :seconds-left="store.undoSecondsLeft"
        :progress="store.undoProgress"
        :busy="store.undoing"
        @undo="onUndo"
      />
    </div>

    <p v-if="store.error" class="discovery__error">{{ store.error }}</p>

    <AppSkeleton v-if="store.loading" height="520px" radius="var(--radius-discovery-card)" />

    <AppErrorView
      v-else-if="store.error && store.candidates.length === 0"
      :message="store.error"
      @retry="store.loadCandidates()"
    />

    <AppEmpty
      v-else-if="showEmpty"
      emoji="🫧"
      :title="store.filtersActive ? '这个范围里暂时没人' : '附近的卡都滑完了'"
      :description="
        store.filtersActive ? '把年龄、城市或标签放宽一点再试试' : '过一会儿再来看看,或者去广场逛逛'
      "
    />

    <SwipeDeck
      v-else
      :candidate="store.current"
      :submitting="store.submitting"
      :like-disabled="store.likeBlocked"
      :online="currentOnline"
      @decide="onDecide"
    />

    <DiscoveryFilterPanel
      v-if="filterOpen"
      :preference="filterPreference"
      :initial="store.filters"
      @close="filterOpen = false"
      @apply="onApplyFilters"
      @reset="onResetFilters"
    />

    <MatchMoment
      v-if="store.matched"
      :candidate="store.matched"
      :shared-tags="store.matchedSharedTags"
      :my-city="profileStore.profile?.city ?? ''"
      @close="store.dismissMatched()"
      @chat="onChat"
    />

    <AppToast :text="toast.text.value" />
  </section>
</template>

<style scoped>
.discovery {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  height: 100%;
  min-height: 0;
  padding: var(--space-lg) var(--space-section-gap);
}
.discovery__entries {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-xs);
}
.discovery__toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
}
/* 筛选入口:与「喜欢我的人」等入口同款胶囊;有筛选生效时换成品牌色描边 + 淡底 */
.discovery__filter {
  display: inline-flex;
  align-items: center;
  gap: var(--space-xs);
  padding: var(--space-xs) var(--space-md);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  color: var(--color-text2);
  font-family: var(--font-latin);
  font-size: var(--text-caption);
  font-weight: var(--weight-medium);
  cursor: pointer;
  transition:
    border-color var(--motion-fast) var(--ease-out),
    color var(--motion-fast) var(--ease-out),
    background var(--motion-fast) var(--ease-out);
}
.discovery__filter:hover {
  background: var(--hover-overlay);
}
.discovery__filter--active {
  border-color: var(--color-brand);
  background: var(--tint-brand);
  color: var(--color-brand);
  font-weight: var(--weight-semibold);
}
.discovery__filter-icon {
  width: 16px;
  height: 16px;
}
.discovery__status {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-sm);
  min-height: 40px;
}
.discovery__quota {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.discovery__error {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-danger);
}
</style>
