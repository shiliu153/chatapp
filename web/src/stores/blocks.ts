import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as moderationApi from '@/api/moderation'
import type { BlockedUser } from '@/api/moderation'

const PAGE_SIZE = 20

export const useBlocksStore = defineStore('blocks', () => {
  const blocks = ref<BlockedUser[]>([])
  const count = ref(0)
  const offset = ref(0)

  async function load(reset = false): Promise<void> {
    if (reset) {
      blocks.value = []
      offset.value = 0
    }
    const page = await moderationApi.fetchBlocks(PAGE_SIZE, offset.value)
    blocks.value = [...blocks.value, ...page.results]
    count.value = page.count
    offset.value += page.results.length
  }

  async function unblock(userId: number): Promise<void> {
    await moderationApi.unblockUser(userId) // 幂等:解除不存在的拉黑也返回成功
    blocks.value = blocks.value.filter((item) => item.user_id !== userId)
    count.value = Math.max(0, count.value - 1)
  }

  async function block(targetUserId: number): Promise<void> {
    await moderationApi.blockUser(targetUserId)
  }

  return { blocks, count, load, unblock, block }
})
