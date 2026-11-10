<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import AppButton from '@/components/AppButton.vue'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import { useSessionStore } from '@/stores/session'
import { useFeedStore, useFollowingFeedStore } from '@/stores/feed'
import PostCard from './PostCard.vue'

const feed = useFeedStore()
const following = useFollowingFeedStore()
const session = useSessionStore()

type Tab = 'recommend' | 'following'
/** 当前 tab:默认「推荐」,与批次 I 之前的行为一致 */
const tab = ref<Tab>('recommend')

/** 当前 tab 的数据源(两个 store 形状一致,模板只认这一份) */
const current = computed(() => (tab.value === 'recommend' ? feed : following))

const showEmpty = computed(
  () => !current.value.loading && !current.value.error && current.value.items.length === 0,
)

function switchTab(next: Tab): void {
  if (tab.value === next) return
  tab.value = next
  // 关注流首次进入才拉;之后切回来复用已加载的列表(下拉/加载更多仍可刷新)
  if (next === 'following' && following.items.length === 0 && !following.loading) {
    following.load().catch(() => {})
  }
}

onMounted(() => {
  feed.load().catch(() => {})
})
</script>

<template>
  <section class="square">
    <header class="square__head">
      <h1 class="square__title">广场</h1>
      <RouterLink :to="{ name: 'post-compose' }">
        <AppButton>发动态</AppButton>
      </RouterLink>
    </header>

    <div class="square__tabs" role="tablist">
      <button
        class="square__tab"
        :class="{ 'square__tab--active': tab === 'recommend' }"
        type="button"
        role="tab"
        :aria-selected="tab === 'recommend'"
        @click="switchTab('recommend')"
      >
        推荐
      </button>
      <button
        class="square__tab"
        :class="{ 'square__tab--active': tab === 'following' }"
        type="button"
        role="tab"
        :aria-selected="tab === 'following'"
        @click="switchTab('following')"
      >
        关注
      </button>
    </div>

    <div v-if="current.loading" class="square__grid">
      <AppSkeleton
        v-for="n in 4"
        :key="n"
        height="280px"
        radius="var(--radius-card)"
      />
    </div>

    <AppErrorView
      v-else-if="current.error && current.items.length === 0"
      :message="current.error"
      @retry="current.load(true)"
    />

    <AppEmpty
      v-else-if="showEmpty"
      emoji="🌟"
      :title="tab === 'following' ? '还没有关注的人' : '广场还很安静'"
      :description="
        tab === 'following' ? '去「推荐」看看,关注感兴趣的人' : '发第一条动态,让大家认识你'
      "
    />

    <div v-else class="square__grid">
      <PostCard
        v-for="item in current.items"
        :key="item.id"
        :post="item"
        :mine="item.author.user_id === session.userId"
        @like="current.toggleLike(item)"
        @favorite="current.toggleFavorite(item)"
        @delete="current.removePost(item.id)"
      />
    </div>

    <div v-if="current.hasMore" class="square__footer">
      <AppButton
        class="square__more"
        variant="ghost"
        :loading="current.loadingMore"
        @click="current.load()"
      >
        加载更多
      </AppButton>
    </div>
  </section>
</template>

<style scoped>
.square {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  padding: var(--space-lg) var(--space-section-gap);
}
.square__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.square__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.square__tabs {
  display: flex;
  gap: var(--space-xl);
}
.square__tab {
  padding: var(--space-xs) 0;
  border: none;
  border-bottom: 3px solid transparent;
  background: transparent;
  color: var(--color-text2);
  font-size: var(--text-body);
  font-weight: var(--weight-medium);
  cursor: pointer;
}
.square__tab--active {
  border-bottom-color: var(--color-brand);
  color: var(--color-text1);
  font-weight: var(--weight-bold);
}
.square__grid {
  display: grid;
  /* 列数随宽度自适应(spec §6.3):单卡在 360px–520px 之间,CSS 自己算列数 */
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 360px), var(--feed-card-max)));
  justify-content: center;
  gap: var(--space-card-gap);
}
.square__footer {
  display: flex;
  justify-content: center;
}
</style>
