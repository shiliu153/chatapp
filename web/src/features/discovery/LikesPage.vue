<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import { useDiscoveryStore } from '@/stores/discovery'
import { useLikesStore } from '@/stores/likes'
import type { LikeReceived } from '@/api/types'
import MatchMoment from './MatchMoment.vue'

const store = useLikesStore()
const discovery = useDiscoveryStore()
const router = useRouter()
const hasMore = computed(() => store.items.length < store.count)

onMounted(() => {
  reload()
})

function reload() {
  store.load(true).catch(() => {})
}

async function loadMore() {
  try {
    await store.load()
  } catch {
    /* store.error 已展示 */
  }
}

async function onAccept(item: LikeReceived) {
  try {
    await store.accept(item.user_id)
    if (store.matched) await discovery.loadMatches(true)
  } catch {
    /* store.error 已展示 */
  }
}

function onChat() {
  const target = store.matched
  store.dismissMatched()
  if (target) router.push({ name: 'chat', params: { peerId: `u${target.user_id}` } })
}

function subtitle(item: LikeReceived): string {
  const parts = [
    item.age === null ? '' : `${item.age} 岁`,
    item.city,
    ...item.tags.slice(0, 3).map((tag) => tag.name),
    formatLikedAt(item.liked_at),
  ]
  return parts.filter(Boolean).join(' · ')
}

function formatLikedAt(iso: string): string {
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  return `${Math.floor(hours / 24)} 天前`
}
</script>

<template>
  <section class="likes">
    <header class="likes__header">
      <RouterLink class="likes__back" :to="{ name: 'discovery' }">← 返回</RouterLink>
      <h1 class="likes__title">喜欢我的人</h1>
    </header>

    <p v-if="store.error" class="likes__error">{{ store.error }}</p>

    <div v-if="store.loading && store.items.length === 0" class="likes__skeleton">
      <AppSkeleton v-for="i in 3" :key="i" height="64px" />
    </div>
    <AppErrorView
      v-else-if="store.error && store.items.length === 0"
      :message="store.error"
      @retry="reload"
    />
    <AppEmpty
      v-else-if="!store.loading && store.items.length === 0"
      emoji="💗"
      title="还没有人喜欢你"
      description="把资料完善一点,多滑几张卡,缘分快到了"
    />

    <ul v-else class="likes__list">
      <li v-for="item in store.items" :key="item.user_id" class="likes__row">
        <RouterLink
          class="likes__person"
          :to="{ name: 'user-profile', params: { id: item.user_id } }"
        >
          <AppAvatar :src="item.photos[0]?.url" :name="item.nickname" :size="44" />
          <span class="likes__meta">
            <span class="likes__name">{{ item.nickname || `用户${item.user_id}` }}</span>
            <span class="likes__sub">{{ subtitle(item) }}</span>
          </span>
        </RouterLink>
        <AppButton
          class="likes__accept"
          variant="ghost"
          :loading="store.busyUserId === item.user_id"
          @click="onAccept(item)"
        >
          喜欢
        </AppButton>
      </li>
    </ul>

    <AppButton
      v-if="hasMore"
      class="likes__more"
      variant="ghost"
      block
      @click="loadMore"
    >
      加载更多
    </AppButton>

    <MatchMoment
      v-if="store.matched"
      :candidate="store.matched"
      @close="store.dismissMatched()"
      @chat="onChat"
    />
  </section>
</template>

<style scoped>
.likes {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  max-width: var(--form-card-max);
  margin: 0 auto;
  padding: var(--space-xl) var(--space-section-gap);
}
.likes__header {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.likes__back {
  align-self: flex-start;
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-decoration: none;
}
.likes__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.likes__error {
  margin: 0;
  color: var(--color-danger);
  font-size: var(--text-caption);
}
.likes__skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.likes__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  margin: 0;
  padding: 0;
  list-style: none;
}
.likes__row {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
}
.likes__person {
  display: flex;
  flex: 1;
  align-items: center;
  gap: var(--space-md);
  min-width: 0;
  color: inherit;
  text-decoration: none;
}
.likes__meta {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.likes__name {
  overflow: hidden;
  color: var(--color-text1);
  font-size: var(--text-subtitle);
  font-weight: var(--weight-semibold);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.likes__sub {
  overflow: hidden;
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.likes__more {
  align-self: center;
}
</style>
