<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { parseApiError } from '@/api/error'
import * as feedApi from '@/api/feed'
import AppButton from '@/components/AppButton.vue'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import ReportDialog from '@/features/moderation/ReportDialog.vue'
import type { Post, ReportType } from '@/api/types'
import { useFavoritesStore } from '@/stores/feed'
import PostCard from './PostCard.vue'

const store = useFavoritesStore()
const notice = ref('')
const reportTarget = ref<Post | null>(null)

const showEmpty = computed(() => !store.loading && !store.error && store.items.length === 0)

onMounted(reload)

function reload(): void {
  store.load(true)
}

function loadMore(): void {
  store.load()
}

async function onReport(type: ReportType, detail: string) {
  const target = reportTarget.value
  reportTarget.value = null
  if (!target) return
  try {
    await feedApi.reportPost(target.id, type, detail)
    notice.value = '已收到举报,我们会尽快核实'
  } catch (e) {
    notice.value = parseApiError(e).message
  }
}
</script>

<template>
  <section class="favorites">
    <header class="favorites__header">
      <h1 class="favorites__title">我的收藏</h1>
      <p class="favorites__hint">收藏是私密的书签:作者收不到通知,也不会出现在聊天里。</p>
    </header>
    <p v-if="notice" class="favorites__notice">{{ notice }}</p>

    <div v-if="store.loading && store.items.length === 0" class="favorites__grid">
      <AppSkeleton
        v-for="n in 4"
        :key="n"
        height="280px"
        radius="var(--radius-card)"
      />
    </div>

    <AppErrorView
      v-else-if="store.error && store.items.length === 0"
      :message="store.error"
      @retry="reload"
    />

    <AppEmpty
      v-else-if="showEmpty"
      emoji="🔖"
      title="还没有收藏"
      description="在广场看到想留着的动态,点右下角的书签就收进来了"
    />

    <div v-else class="favorites__grid">
      <PostCard
        v-for="item in store.items"
        :key="item.id"
        :post="item"
        @like="store.toggleLike(item)"
        @favorite="store.toggleFavorite(item)"
        @report="reportTarget = item"
      />
    </div>

    <div v-if="store.hasMore" class="favorites__footer">
      <AppButton
        class="favorites__more"
        variant="ghost"
        :loading="store.loadingMore"
        @click="loadMore"
      >
        加载更多
      </AppButton>
    </div>

    <ReportDialog
      :open="reportTarget !== null"
      target="post"
      @close="reportTarget = null"
      @submitted="onReport"
    />
  </section>
</template>

<style scoped>
.favorites {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  padding: var(--space-lg) var(--space-section-gap);
}
.favorites__header {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}
.favorites__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.favorites__hint {
  margin: 0;
  color: var(--color-text3);
  font-size: var(--text-caption);
}
.favorites__notice {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.favorites__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 360px), var(--feed-card-max)));
  justify-content: center;
  gap: var(--space-card-gap);
}
.favorites__footer {
  display: flex;
  justify-content: center;
}
</style>
