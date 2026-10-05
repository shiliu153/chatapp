<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { parseApiError } from '@/api/error'
import * as feedApi from '@/api/feed'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import ReportDialog from '@/features/moderation/ReportDialog.vue'
import type { Post, ReportType } from '@/api/types'
import { useFeedStore } from '@/stores/feed'
import PostCard from './PostCard.vue'

const store = useFeedStore()
const notice = ref('')
const reportTarget = ref<Post | null>(null)

const showEmpty = computed(() => !store.loading && !store.error && store.posts.length === 0)

onMounted(() => {
  store.loadMine(true).catch(() => {})
})

async function onDelete(post: Post) {
  // 删除不可恢复,必须二次确认
  if (!window.confirm('删除这条动态?删除后不可恢复')) return
  notice.value = ''
  try {
    await store.removePost(post.id)
  } catch (e) {
    notice.value = parseApiError(e).message
  }
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
  <section class="my-posts">
    <h1 class="my-posts__title">我的动态</h1>
    <p v-if="notice" class="my-posts__notice">{{ notice }}</p>

    <AppEmpty
      v-if="showEmpty"
      emoji="📝"
      title="还没发过动态"
      description="去广场发一条吧"
    />
    <AppErrorView v-else-if="store.error" :message="store.error" @retry="store.loadMine(true)" />

    <div v-else class="my-posts__grid">
      <PostCard
        v-for="item in store.posts"
        :key="item.id"
        :post="item"
        mine
        @like="store.toggleLike(item)"
        @delete="onDelete(item)"
        @report="reportTarget = item"
      />
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
.my-posts {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  padding: var(--space-lg) var(--space-section-gap);
}
.my-posts__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.my-posts__notice {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.my-posts__grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 360px), var(--feed-card-max)));
  justify-content: center;
  gap: var(--space-card-gap);
}
</style>
