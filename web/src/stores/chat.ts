import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

/**
 * 聊天 store 的占位版(Task 6.4 会整体替换为完整实现)。
 * 这里只提供侧栏未读角标需要的 unreadTotal。
 */
export const useChatStore = defineStore('chat', () => {
  const conversations = ref<{ peerId: string; unreadCount: number }[]>([])
  const unreadTotal = computed(() =>
    conversations.value.reduce((sum, c) => sum + c.unreadCount, 0),
  )
  return { conversations, unreadTotal }
})
