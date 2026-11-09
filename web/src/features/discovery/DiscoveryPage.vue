<script setup lang="ts">
import { computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import AppToast from '@/components/AppToast.vue'
import { useToast } from '@/composables/useToast'
import { useDiscoveryStore } from '@/stores/discovery'
import { usePresenceStore } from '@/stores/presence'
import { useProfileStore } from '@/stores/profile'
import LikesEntry from './LikesEntry.vue'
import MatchesList from './MatchesList.vue'
import MatchMoment from './MatchMoment.vue'
import SwipeDeck from './SwipeDeck.vue'
import UndoButton from './UndoButton.vue'
import VisitsEntry from './VisitsEntry.vue'

const store = useDiscoveryStore()
const presence = usePresenceStore()
const profileStore = useProfileStore()
const router = useRouter()
/** 撤销/划卡的结果提示(「已撤销」),2 秒后自动消失 */
const toast = useToast(2000)

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
})

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

    <div v-if="store.quotaVisible || store.undoVisible" class="discovery__status">
      <p v-if="store.quotaVisible" class="discovery__quota">{{ store.quotaText }}</p>
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
      title="附近的卡都滑完了"
      description="过一会儿再来看看,或者去广场逛逛"
    />

    <SwipeDeck
      v-else
      :candidate="store.current"
      :submitting="store.submitting"
      :like-disabled="store.likeBlocked"
      :online="currentOnline"
      @decide="onDecide"
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
