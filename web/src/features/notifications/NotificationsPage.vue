<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import AppAvatar from '@/components/AppAvatar.vue'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import { useNotificationsStore } from '@/stores/notifications'
import type { AppNotification } from '@/api/types'

const store = useNotificationsStore()
const router = useRouter()
const hasMore = computed(() => store.items.length < store.count)
const hasUnread = computed(() => store.items.some((item) => !item.is_read))

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

async function markAll() {
  try {
    await store.markAll()
  } catch {
    /* 已读是副作用,失败不挡浏览 */
  }
}

/** 点一条:先标已读,再按 target 跳转(none 只标已读)。 */
async function open(item: AppNotification) {
  try {
    await store.markOne(item)
  } catch {
    /* 标记失败不挡跳转 */
  }
  const target = item.target
  if (target.kind === 'post' && target.id !== null) {
    router.push({ name: 'post-detail', params: { id: String(target.id) } })
  } else if (target.kind === 'user' && target.id !== null) {
    router.push({ name: 'chat', params: { peerId: `u${target.id}` } })
  }
}

/** 相对时间:刚刚 / x 分钟前 / x 小时前 / x 天前(7 天内)/ M-D。 */
function formatWhen(iso: string): string {
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (minutes < 1) return '刚刚'
  if (minutes < 60) return `${minutes} 分钟前`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days} 天前`
  const date = new Date(iso)
  return `${date.getMonth() + 1}-${date.getDate()}`
}
</script>

<template>
  <section class="notifications">
    <header class="notifications__header">
      <RouterLink class="notifications__back" :to="{ name: 'chats' }">← 返回</RouterLink>
      <div class="notifications__title-row">
        <h1 class="notifications__title">通知</h1>
        <button
          v-if="hasUnread"
          type="button"
          class="notifications__mark-all"
          @click="markAll"
        >
          全部已读
        </button>
      </div>
    </header>

    <p v-if="store.error && store.items.length > 0" class="notifications__error">
      {{ store.error }}
    </p>

    <div v-if="store.loading && store.items.length === 0" class="notifications__skeleton">
      <AppSkeleton v-for="i in 3" :key="i" height="64px" />
    </div>
    <AppErrorView
      v-else-if="store.error && store.items.length === 0"
      :message="store.error"
      @retry="reload"
    />
    <AppEmpty
      v-else-if="!store.loading && store.items.length === 0"
      emoji="🔔"
      title="还没有通知"
      description="有人赞你、评论你,或者配对成功时,会在这里提醒你"
    />

    <ul v-else class="notifications__list">
      <li v-for="item in store.items" :key="item.id">
        <button
          type="button"
          class="notifications__row"
          :class="{ 'notifications__row--unread': !item.is_read }"
          @click="open(item)"
        >
          <AppAvatar
            v-if="item.actor"
            :src="item.actor.avatar"
            :name="item.actor.nickname"
            :size="44"
          />
          <span v-else class="notifications__system-mark" aria-hidden="true">🔔</span>
          <span class="notifications__main">
            <span class="notifications__text">{{ item.text }}</span>
            <span class="notifications__time">{{ formatWhen(item.created_at) }}</span>
          </span>
          <span v-if="!item.is_read" class="notifications__dot" aria-label="未读" />
        </button>
      </li>
    </ul>

    <button
      v-if="hasMore"
      type="button"
      class="notifications__more"
      @click="loadMore"
    >
      加载更多
    </button>
  </section>
</template>

<style scoped>
.notifications {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  max-width: var(--form-card-max);
  margin: 0 auto;
  padding: var(--space-xl) var(--space-section-gap);
}
.notifications__header {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.notifications__back {
  align-self: flex-start;
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-decoration: none;
}
.notifications__title-row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-md);
}
.notifications__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.notifications__mark-all {
  border: none;
  background: none;
  color: var(--color-brand);
  font-size: var(--text-caption);
  font-weight: var(--weight-semibold);
  cursor: pointer;
}
.notifications__error {
  margin: 0;
  color: var(--color-danger);
  font-size: var(--text-caption);
}
.notifications__skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.notifications__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  margin: 0;
  padding: 0;
  list-style: none;
}
.notifications__row {
  display: flex;
  width: 100%;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md);
  border: none;
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  text-align: left;
  cursor: pointer;
  transition: background var(--motion-fast) var(--ease-out);
}
.notifications__row:hover {
  background: var(--hover-overlay);
}
.notifications__system-mark {
  display: inline-flex;
  flex: none;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: var(--radius-full);
  background: var(--tint-brand);
  font-size: var(--text-subtitle);
}
.notifications__main {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: var(--space-xs);
}
.notifications__text {
  overflow: hidden;
  color: var(--color-text1);
  font-size: var(--text-body);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.notifications__time {
  color: var(--color-text3);
  font-size: var(--text-badge);
}
.notifications__dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--color-brand);
}
.notifications__more {
  align-self: center;
  border: none;
  background: none;
  color: var(--color-brand);
  font-size: var(--text-caption);
  font-weight: var(--weight-semibold);
  cursor: pointer;
}
</style>
