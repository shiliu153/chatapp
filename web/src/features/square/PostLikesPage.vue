<script setup lang="ts">
import { computed, onMounted } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import AppButton from '@/components/AppButton.vue'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import { usePostLikesStore } from '@/stores/feed'

/** 路由 `/posts/:id/likes` 的 `id`(routes.ts 用 props: true 传进来) */
const props = defineProps<{ id: string }>()

const store = usePostLikesStore()
const postId = computed(() => Number(props.id))

const showEmpty = computed(() => !store.loading && !store.error && store.items.length === 0)

onMounted(reload)

function reload(): void {
  store.load(postId.value, true)
}

function loadMore(): void {
  store.loadMore()
}

/** 相对时间:刚刚 / x 分钟前 / x 小时前 / x 天前(与「喜欢我的人」页同口径)。 */
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
  <section class="post-likes">
    <header class="post-likes__header">
      <RouterLink class="post-likes__back" :to="{ name: 'post-detail', params: { id: props.id } }">
        ← 返回动态
      </RouterLink>
      <h1 class="post-likes__title">点赞的人</h1>
      <!-- count 是**过滤后**的可见人数(双向拉黑 / 重封禁账号不计),不保证等于卡片上的赞数 -->
      <p v-if="!store.loading && !store.error" class="post-likes__count">
        共 {{ store.count }} 人点赞
      </p>
    </header>

    <div v-if="store.loading && store.items.length === 0" class="post-likes__skeleton">
      <AppSkeleton v-for="i in 3" :key="i" height="64px" />
    </div>

    <AppErrorView
      v-else-if="store.error && store.items.length === 0"
      :message="store.error"
      @retry="reload"
    />

    <AppEmpty
      v-else-if="showEmpty"
      emoji="♡"
      title="还没有人点赞"
      description="把这条动态分享出去,或者再等等"
    />

    <ul v-else class="post-likes__list">
      <li v-for="liker in store.items" :key="liker.user_id" class="post-likes__row">
        <RouterLink
          class="post-likes__person"
          :to="{ name: 'user-profile', params: { id: liker.user_id } }"
        >
          <AppAvatar :src="liker.avatar_url" :name="liker.nickname" :size="44" />
          <span class="post-likes__meta">
            <span class="post-likes__name">
              {{ liker.nickname || `用户${liker.user_id}` }}
            </span>
            <span class="post-likes__time">{{ formatLikedAt(liker.liked_at) }}</span>
          </span>
        </RouterLink>
      </li>
    </ul>

    <AppButton
      v-if="store.hasMore"
      class="post-likes__more"
      variant="ghost"
      block
      @click="loadMore"
    >
      加载更多
    </AppButton>
  </section>
</template>

<style scoped>
.post-likes {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  max-width: var(--form-card-max);
  margin: 0 auto;
  padding: var(--space-xl) var(--space-section-gap);
}
.post-likes__header {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.post-likes__back {
  align-self: flex-start;
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-decoration: none;
}
.post-likes__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.post-likes__count {
  margin: 0;
  color: var(--color-text3);
  font-size: var(--text-caption);
}
.post-likes__skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.post-likes__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
  margin: 0;
  padding: 0;
  list-style: none;
}
.post-likes__row {
  display: flex;
  align-items: center;
  padding: var(--space-md);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
}
.post-likes__person {
  display: flex;
  flex: 1;
  align-items: center;
  gap: var(--space-md);
  min-width: 0;
  color: inherit;
  text-decoration: none;
}
.post-likes__meta {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  min-width: 0;
}
.post-likes__name {
  overflow: hidden;
  color: var(--color-text1);
  font-weight: var(--weight-medium);
  white-space: nowrap;
  text-overflow: ellipsis;
}
.post-likes__time {
  color: var(--color-text3);
  font-size: var(--text-caption);
}
</style>
