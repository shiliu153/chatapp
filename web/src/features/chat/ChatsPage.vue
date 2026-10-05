<script setup lang="ts">
import { computed, onMounted } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import AppBadge from '@/components/AppBadge.vue'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import { ChatMessageKind } from '@/im/types'
import { useChatStore } from '@/stores/chat'
import type { ChatMessage, ImConversation } from '@/im/types'

const store = useChatStore()

/** 连接中/重连中且还没有内容 → 骨架 */
const loading = computed(
  () => ['idle', 'connecting', 'reconnecting'].includes(store.status) && store.conversations.length === 0,
)
const failed = computed(() => store.status === 'error' && store.conversations.length === 0)
const showEmpty = computed(() => !loading.value && !failed.value && store.conversations.length === 0)

/** 最近联系人:有最后一条消息的前 10 个会话 */
const recent = computed(() => store.conversations.filter((item) => item.lastMessage).slice(0, 10))

onMounted(() => {
  void store.connect()
  void store.loadConversations().catch(() => {})
})

function summaryOf(message: ChatMessage | null): string {
  if (!message) return '打个招呼吧'
  if (message.isFailed) return '发送失败'
  if (message.kind === ChatMessageKind.image) return '[图片]'
  return message.text || '[消息]'
}

function timeOf(conversation: ImConversation): string {
  const timestamp = conversation.lastMessage?.timestamp
  if (!timestamp) return ''
  const date = new Date(timestamp)
  const now = new Date()
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  if (sameDay) {
    return `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
  }
  const yesterday = new Date(now)
  yesterday.setDate(now.getDate() - 1)
  if (
    date.getFullYear() === yesterday.getFullYear() &&
    date.getMonth() === yesterday.getMonth() &&
    date.getDate() === yesterday.getDate()
  ) {
    return '昨天'
  }
  return `${date.getMonth() + 1}-${date.getDate()}`
}
</script>

<template>
  <section class="chats">
    <h1 class="chats__title">消息</h1>

    <AppSkeleton v-if="loading" height="64px" />

    <AppErrorView
      v-else-if="failed"
      :message="store.error || '消息加载失败'"
      @retry="store.loadConversations()"
    />

    <AppEmpty
      v-else-if="showEmpty"
      emoji="💬"
      title="还没有聊天"
      description="去发现页滑一滑,互相喜欢就能开始聊天"
    />

    <template v-else>
      <!-- 最近联系人横滑条(spec §6.3) -->
      <div v-if="recent.length" class="chats__recent">
        <RouterLink
          v-for="item in recent"
          :key="`recent-${item.peerId}`"
          class="chats__recent-item"
          :to="{ name: 'chat', params: { peerId: item.peerId } }"
        >
          <AppAvatar :src="item.faceUrl" :name="item.showName" :size="52" />
          <span class="chats__recent-name">{{ item.showName }}</span>
        </RouterLink>
      </div>

      <ul class="chats__list">
        <li v-for="item in store.conversations" :key="item.peerId">
          <RouterLink
            class="chats__row"
            :to="{ name: 'chat', params: { peerId: item.peerId } }"
          >
            <AppAvatar :src="item.faceUrl" :name="item.showName" :size="48" />
            <div class="chats__main">
              <div class="chats__line">
                <span class="chats__name">{{ item.showName }}</span>
                <span class="chats__time">{{ timeOf(item) }}</span>
              </div>
              <p class="chats__summary">{{ summaryOf(item.lastMessage) }}</p>
            </div>
            <AppBadge :count="item.unreadCount" />
          </RouterLink>
        </li>
      </ul>
    </template>
  </section>
</template>

<style scoped>
.chats {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  padding: var(--space-lg) var(--space-section-gap);
}
.chats__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.chats__recent {
  display: flex;
  gap: var(--space-md);
  overflow-x: auto;
  padding-bottom: var(--space-xs);
}
.chats__recent-item {
  display: flex;
  flex: none;
  flex-direction: column;
  align-items: center;
  gap: var(--space-xs);
  width: 64px;
}
.chats__recent-name {
  max-width: 64px;
  overflow: hidden;
  font-size: var(--text-badge);
  color: var(--color-text2);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chats__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  margin: 0;
  padding: 0;
  list-style: none;
}
.chats__row {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  transition: background var(--motion-fast) var(--ease-out);
}
.chats__row:hover {
  background: var(--hover-overlay);
}
.chats__main {
  display: flex;
  flex: 1;
  min-width: 0;
  flex-direction: column;
  gap: var(--space-xs);
}
.chats__line {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--space-sm);
}
.chats__name {
  overflow: hidden;
  font-size: var(--text-body);
  font-weight: var(--weight-semibold);
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chats__time {
  flex: none;
  font-size: var(--text-badge);
  color: var(--color-text3);
}
.chats__summary {
  margin: 0;
  overflow: hidden;
  font-size: var(--text-caption);
  color: var(--color-text2);
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
