<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import { useDiscoveryStore } from '@/stores/discovery'
import MatchesList from './MatchesList.vue'
import MatchMoment from './MatchMoment.vue'
import SwipeDeck from './SwipeDeck.vue'

const store = useDiscoveryStore()
const router = useRouter()

const showEmpty = computed(() => !store.loading && !store.error && store.exhausted)

onMounted(() => {
  store.loadCandidates()
})

async function onDecide(action: 'like' | 'pass') {
  await store.decide(action)
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
    <MatchesList />

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
      @decide="onDecide"
    />

    <MatchMoment
      v-if="store.matched"
      :candidate="store.matched"
      @close="store.dismissMatched()"
      @chat="onChat"
    />
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
.discovery__error {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-danger);
}
</style>
