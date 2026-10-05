<script setup lang="ts">
import { computed, onMounted } from 'vue'
import AppButton from '@/components/AppButton.vue'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import { useSessionStore } from '@/stores/session'
import { useFeedStore } from '@/stores/feed'
import PostCard from './PostCard.vue'

const store = useFeedStore()
const session = useSessionStore()

const showEmpty = computed(() => !store.loading && !store.error && store.posts.length === 0)

onMounted(() => {
  store.load().catch(() => {})
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

    <div v-if="store.loading" class="square__grid">
      <AppSkeleton
        v-for="n in 4"
        :key="n"
        height="280px"
        radius="var(--radius-card)"
      />
    </div>

    <AppErrorView
      v-else-if="store.error && store.posts.length === 0"
      :message="store.error"
      @retry="store.load(true)"
    />

    <AppEmpty
      v-else-if="showEmpty"
      emoji="🌟"
      title="广场还很安静"
      description="发第一条动态,让大家认识你"
    />

    <div v-else class="square__grid">
      <PostCard
        v-for="item in store.posts"
        :key="item.id"
        :post="item"
        :mine="item.author.user_id === session.userId"
        @like="store.toggleLike(item)"
        @delete="store.removePost(item.id)"
      />
    </div>

    <div v-if="store.hasMore" class="square__footer">
      <AppButton
        class="square__more"
        variant="ghost"
        :loading="store.loadingMore"
        @click="store.load()"
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
