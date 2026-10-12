<script setup lang="ts">
import AppSidebar from '@/components/AppSidebar.vue'
import { useSidebar } from '@/layout'
import { useChatStore } from '@/stores/chat'

const sidebar = useSidebar()
const chat = useChatStore()
</script>

<template>
  <div class="shell" :class="{ 'shell--dragging': sidebar.isDragging.value }">
    <AppSidebar
      :width="sidebar.width.value"
      :icon-only="sidebar.isIconOnly.value"
      :unread-total="chat.unreadTotal"
      @resize-start="sidebar.beginDrag"
      @resize-reset="sidebar.resetToDefault"
    />
    <main class="shell__content">
      <RouterView />
    </main>
  </div>
</template>

<style scoped>
.shell {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
/* 拖拽时禁止选中文本,否则会把侧栏文字一起框选 */
.shell--dragging {
  user-select: none;
}
.shell__content {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
}
</style>
