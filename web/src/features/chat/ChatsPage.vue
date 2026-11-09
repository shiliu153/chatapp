<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import AppAvatar from '@/components/AppAvatar.vue'
import AppBadge from '@/components/AppBadge.vue'
import AppEmpty from '@/components/AppEmpty.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import AppToast from '@/components/AppToast.vue'
import { useToast } from '@/composables/useToast'
import { parseApiError } from '@/api/error'
import { useChatStore } from '@/stores/chat'
import { useNotificationsStore } from '@/stores/notifications'
import { usePresenceStore } from '@/stores/presence'
import type { ImConversation } from '@/im/types'
import ConversationMenu from './ConversationMenu.vue'
import ConversationRow from './ConversationRow.vue'
import DeleteConversationDialog from './DeleteConversationDialog.vue'
import { conversationNameOf } from './conversation'

const store = useChatStore()
const notifications = useNotificationsStore()
const presence = usePresenceStore()
const router = useRouter()
const toast = useToast()

/** 连接中/重连中且还没有内容 → 骨架 */
const loading = computed(
  () => ['idle', 'connecting', 'reconnecting'].includes(store.status) && store.conversations.length === 0,
)
const failed = computed(() => store.status === 'error' && store.conversations.length === 0)
const showEmpty = computed(() => !loading.value && !failed.value && store.conversations.length === 0)
/** 同端另一个窗口接管了连接:只提示 + 手动接管,不自动抢(否则两个窗口互相踢) */
const inactive = computed(() => store.status === 'inactive')

/** 最近联系人:有最后一条消息的前 10 个会话 */
const recent = computed(() => store.conversations.filter((item) => item.lastMessage).slice(0, 10))

/** 打开中的「更多」菜单:记住是哪一行(不靠坐标反查,行更新了也不会认错) */
const menu = ref<{ conversation: ImConversation; x: number; y: number } | null>(null)
/** 删除确认:待删会话 + 进行中/错误态 */
const deleting = ref<{ conversation: ImConversation; busy: boolean; error: string } | null>(null)

onMounted(() => {
  void store.connect()
  void store.loadConversations().catch(() => {})
  // 站内通知角标:失败不影响消息页主流程
  void notifications.loadUnread().catch(() => {})
})

/** 会话对端(`u9`)→ 数字用户 id;系统通知不是真人,不查在线状态 */
function peerUserId(peerId: string): number | null {
  if (peerId === 'system_notice' || !peerId.startsWith('u')) return null
  const id = Number(peerId.slice(1))
  return Number.isFinite(id) ? id : null
}

const peerIds = computed(() =>
  store.conversations.map((item) => peerUserId(item.peerId)).filter((id): id is number => id !== null),
)

watch(peerIds, (ids) => presence.track('chats', ids), { immediate: true, deep: true })

function isOnline(conversation: ImConversation): boolean {
  const id = peerUserId(conversation.peerId)
  return id !== null && presence.isOnline(id)
}

function openMenu(conversation: ImConversation, anchor: { x: number; y: number }): void {
  menu.value = { conversation, x: anchor.x, y: anchor.y }
}

/** 菜单开着时,若那一行已经不在列表里(跨端删除等),直接收掉菜单 */
watch(
  () => store.conversations.map((item) => item.peerId).join(','),
  () => {
    if (menu.value && !store.conversations.some((item) => item.peerId === menu.value?.conversation.peerId)) {
      menu.value = null
    }
  },
)

/**
 * 统一错误提示(批次 N 的验收口径):
 * - `40401` 会话不存在 → 提示已不存在,并刷新列表(本地那条是过期数据);
 * - `42901`/429 → 限流提示,退避再试;
 * - 其他 → 走统一 `ApiError` 的文案。
 *
 * 返回 true 表示「会话已不存在」,调用方据此决定要不要清掉本地那一行。
 */
function reportError(error: unknown): boolean {
  const apiError = parseApiError(error)
  if (apiError.code === 40401 || apiError.status === 404) {
    toast.show('该会话已不存在,正在刷新列表')
    void store.loadConversations().catch(() => {})
    return true
  }
  if (apiError.isThrottled || apiError.code === 42901) {
    toast.show('操作太频繁,请稍后再试')
    return false
  }
  toast.show(apiError.message || '操作失败,请稍后再试')
  return false
}

/** 置顶 / 取消置顶、免打扰 / 取消免打扰:同一个 HTTP 接口,只是改的字段不同 */
async function onMenuAction(action: 'pin' | 'mute' | 'delete'): Promise<void> {
  const target = menu.value?.conversation
  menu.value = null
  if (!target) return
  if (action === 'delete') {
    deleting.value = { conversation: target, busy: false, error: '' }
    return
  }
  // 先记下「改之前」的状态:store 成功后会**就地**改这个对象,事后再读就成了新值
  const wasPinned = target.pinned
  const wasMuted = target.muted
  const flags = action === 'pin' ? { pinned: !wasPinned } : { muted: !wasMuted }
  try {
    await store.setConversationFlags(target.peerId, flags)
    if (action === 'pin') toast.show(wasPinned ? '已取消置顶' : '已置顶')
    else toast.show(wasMuted ? '已取消免打扰' : '已开启免打扰')
  } catch (error) {
    reportError(error)
  }
}

async function onDeleteConfirm(): Promise<void> {
  const target = deleting.value
  if (!target || target.busy) return
  target.busy = true
  target.error = ''
  try {
    await store.deleteConversation(target.conversation.peerId)
    deleting.value = null
  } catch (error) {
    // 会话本来就不存在(404):删除的目的一样达成了,直接收掉对话框
    const apiError = parseApiError(error)
    if (reportError(error)) {
      deleting.value = null
      return
    }
    target.busy = false
    target.error = apiError.message || '删除失败,请稍后再试'
  }
}
</script>

<template>
  <section class="chats">
    <header class="chats__head">
      <h1 class="chats__title">消息</h1>
      <div class="chats__actions">
        <!-- 只有自建 IM 后端支持搜索;能力位在连上之后才为 true(见 store.capabilities) -->
        <button
          v-if="store.capabilities.search"
          type="button"
          class="chats__search"
          aria-label="搜索聊天记录"
          title="搜索聊天记录"
          @click="router.push({ name: 'search' })"
        >
          🔍
        </button>
        <!-- 站内通知入口(批次 H):铃铛 + 未读角标,不加第 5 个底栏 tab -->
        <button
          type="button"
          class="chats__notifications"
          aria-label="通知"
          title="通知"
          @click="router.push({ name: 'notifications' })"
        >
          🔔
          <AppBadge class="chats__notifications-badge" :count="notifications.unread" />
        </button>
      </div>
    </header>

    <AppSkeleton v-if="loading" height="64px" />

    <p v-if="inactive" class="chats__inactive">
      账号已在另一个窗口连接。
      <button type="button" class="chats__takeover" @click="store.reconnect()">在此窗口接管</button>
    </p>

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
          <AppAvatar :src="item.faceUrl" :name="conversationNameOf(item)" :size="52" />
          <span class="chats__recent-name">{{ conversationNameOf(item) }}</span>
        </RouterLink>
      </div>

      <!-- 置顶组(批次 N):组内顺序 = 服务端返回顺序,客户端不再排一次 -->
      <section v-if="store.pinnedConversations.length" class="chats__group">
        <h2 class="chats__group-title">置顶</h2>
        <ul class="chats__list">
          <li v-for="item in store.pinnedConversations" :key="item.peerId">
            <ConversationRow
              :conversation="item"
              :online="isOnline(item)"
              @more="openMenu(item, $event)"
            />
          </li>
        </ul>
      </section>

      <section v-if="store.otherConversations.length" class="chats__group">
        <!-- 只有和置顶组并存时才需要标题,否则多一行纯属噪音 -->
        <h2 v-if="store.pinnedConversations.length" class="chats__group-title">全部会话</h2>
        <ul class="chats__list">
          <li v-for="item in store.otherConversations" :key="item.peerId">
            <ConversationRow
              :conversation="item"
              :online="isOnline(item)"
              @more="openMenu(item, $event)"
            />
          </li>
        </ul>
      </section>
    </template>

    <ConversationMenu
      v-if="menu"
      :pinned="menu.conversation.pinned"
      :muted="menu.conversation.muted"
      :x="menu.x"
      :y="menu.y"
      @close="menu = null"
      @action="onMenuAction"
    />

    <DeleteConversationDialog
      :open="deleting !== null"
      :name="deleting ? conversationNameOf(deleting.conversation) : ''"
      :busy="deleting?.busy ?? false"
      :error="deleting?.error ?? ''"
      @close="deleting = null"
      @confirm="onDeleteConfirm"
    />

    <AppToast :text="toast.text.value" />
  </section>
</template>

<style scoped>
.chats {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  padding: var(--space-lg) var(--space-section-gap);
}
.chats__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
}
.chats__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.chats__search {
  flex: none;
  width: 40px;
  height: 40px;
  border: none;
  border-radius: var(--radius-chip);
  background: var(--color-bg-card);
  font-size: var(--text-subtitle);
  line-height: 1;
  cursor: pointer;
  transition: background var(--motion-fast) var(--ease-out);
}
.chats__search:hover {
  background: var(--hover-overlay-strong);
}
.chats__actions {
  display: flex;
  flex: none;
  align-items: center;
  gap: var(--space-xs);
}
.chats__notifications {
  position: relative;
  flex: none;
  width: 40px;
  height: 40px;
  border: none;
  border-radius: var(--radius-chip);
  background: var(--color-bg-card);
  font-size: var(--text-subtitle);
  line-height: 1;
  cursor: pointer;
  transition: background var(--motion-fast) var(--ease-out);
}
.chats__notifications:hover {
  background: var(--hover-overlay-strong);
}
.chats__notifications-badge {
  position: absolute;
  top: 2px;
  right: 2px;
}
.chats__inactive {
  margin: 0;
  padding: var(--space-sm) var(--space-md);
  border-radius: var(--radius-chip);
  background: var(--tint-brand);
  color: var(--color-brand);
  font-size: var(--text-caption);
}
.chats__takeover {
  border: none;
  background: none;
  color: var(--color-brand);
  font-size: var(--text-caption);
  font-weight: var(--weight-semibold);
  text-decoration: underline;
  cursor: pointer;
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
.chats__group {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}
.chats__group-title {
  margin: var(--space-xs) 0 0;
  padding: 0 var(--space-xs);
  color: var(--color-text2);
  font-size: var(--text-badge);
  font-weight: var(--weight-semibold);
  letter-spacing: 0.02em;
}
.chats__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  margin: 0;
  padding: 0;
  list-style: none;
}
</style>
