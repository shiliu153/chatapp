<script setup lang="ts">
/**
 * 消息页的一行会话(批次 N 从 `ChatsPage` 抽出来)。
 *
 * 抽成组件的原因:置顶后同一行的结构要在「置顶」与「全部会话」两个分组里各渲染一次,
 * 复制两遍模板迟早会改一处忘一处。行内还要放「更多」入口(`⋯` 按钮 + 右键),
 * 与整行跳转的 `RouterLink` 是两个不同的交互目标 —— 按钮必须放在链接**外面**,
 * 不能把 `<button>` 套进 `<a>` 里。
 */
import { computed } from 'vue'
import AppAvatar from '@/components/AppAvatar.vue'
import AppBadge from '@/components/AppBadge.vue'
import OnlineDot from '@/components/OnlineDot.vue'
import type { ImConversation } from '@/im/types'
import { conversationNameOf, conversationSummaryOf, conversationTimeOf } from './conversation'
import { hasDraft } from './draft'

const props = defineProps<{ conversation: ImConversation; online: boolean }>()
/** 菜单锚点(视口坐标):右键取鼠标位置,`⋯` 按钮取按钮下沿 */
const emit = defineEmits<{ more: [anchor: { x: number; y: number }] }>()

const name = computed(() => conversationNameOf(props.conversation))
const summary = computed(() => conversationSummaryOf(props.conversation.lastMessage))
const time = computed(() => conversationTimeOf(props.conversation))
/**
 * 有草稿 → 摘要前挂「[草稿] 」(批次 T,微信口径)。
 *
 * 草稿与摘要**并列展示**,不覆盖摘要:用户既要知道自己没发出去什么,
 * 也要知道对方最后说了什么。
 */
const drafted = computed(() => hasDraft(props.conversation.peerId))
const target = computed(() => ({
  name: 'chat',
  params: { peerId: props.conversation.peerId },
}))

/**
 * `⋯` 按钮点击:锚到按钮自身的下沿,而不是鼠标坐标。
 *
 * 键盘回车/空格触发的 click 在部分浏览器里 `clientX/clientY` 是 0,照鼠标坐标定位
 * 会把菜单甩到窗口左上角 —— 用元素矩形定位才对键盘和触屏都成立。
 */
function onMoreClick(event: MouseEvent): void {
  const rect = (event.currentTarget as HTMLElement | null)?.getBoundingClientRect()
  emit('more', rect ? { x: rect.left, y: rect.bottom + 4 } : { x: 0, y: 0 })
}

/** 右键整行:菜单出现在鼠标位置(PC 的肌肉记忆) */
function onContextMenu(event: MouseEvent): void {
  emit('more', { x: event.clientX, y: event.clientY })
}
</script>

<template>
  <div class="chats__item" @contextmenu.prevent="onContextMenu">
    <RouterLink class="chats__row" :to="target">
      <AppAvatar :src="props.conversation.faceUrl" :name="name" :size="48" />
      <OnlineDot :online="props.online" />
      <div class="chats__main">
        <div class="chats__line">
          <span class="chats__name">
            <span class="chats__name-text">{{ name }}</span>
            <!-- 免打扰(批次 N):静音图标;未读只出灰点,不出数字 -->
            <span
              v-if="props.conversation.muted"
              class="chats__muted"
              role="img"
              aria-label="消息免打扰"
              title="消息免打扰"
            >
              🔕
            </span>
          </span>
          <span class="chats__time">{{ time }}</span>
        </div>
        <p class="chats__summary">
          <span v-if="drafted" class="chats__draft" data-testid="chats-draft">[草稿] </span>
          {{ summary }}
        </p>
      </div>
      <span
        v-if="props.conversation.muted && props.conversation.unreadCount > 0"
        class="chats__unread-dot"
        role="img"
        aria-label="有未读消息"
      />
      <AppBadge v-else-if="!props.conversation.muted" :count="props.conversation.unreadCount" />
    </RouterLink>
    <button
      type="button"
      class="chats__more"
      aria-label="更多操作"
      title="更多操作"
      @click.stop="onMoreClick"
    >
      ⋯
    </button>
  </div>
</template>

<style scoped>
.chats__item {
  display: flex;
  align-items: center;
  gap: var(--space-xs);
  padding-right: var(--space-xs);
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  transition: background var(--motion-fast) var(--ease-out);
}
.chats__item:hover {
  background: var(--hover-overlay);
}
.chats__row {
  display: flex;
  flex: 1;
  min-width: 0;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md);
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
  display: flex;
  min-width: 0;
  align-items: center;
  gap: var(--space-xs);
  font-size: var(--text-body);
  font-weight: var(--weight-semibold);
}
.chats__name-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.chats__muted {
  flex: none;
  font-size: var(--text-badge);
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
/* 草稿前缀:用主色标出「这是你没发出去的话」,与对端的摘要区分开 */
.chats__draft {
  color: var(--color-brand);
  font-weight: var(--weight-semibold);
}
.chats__unread-dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: var(--radius-full);
  background: var(--color-text3);
}
/* 「更多」入口:常驻可见(不做 hover 才出现),触屏与键盘都能按到 */
.chats__more {
  flex: none;
  width: 32px;
  height: 32px;
  border: none;
  border-radius: var(--radius-chip);
  background: none;
  color: var(--color-text3);
  font-size: var(--text-subtitle);
  line-height: 1;
  cursor: pointer;
  transition: background var(--motion-fast) var(--ease-out);
}
.chats__more:hover {
  background: var(--hover-overlay-strong);
  color: var(--color-text1);
}
.chats__more:focus-visible {
  outline: 2px solid var(--color-focus-ring);
}
</style>
