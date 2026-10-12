<script setup lang="ts">
import { computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import AppAvatar from './AppAvatar.vue'
import AppBadge from './AppBadge.vue'
import { useProfileStore } from '@/stores/profile'

const props = defineProps<{ width: number; iconOnly: boolean; unreadTotal?: number }>()
const emit = defineEmits<{ 'resize-start': [PointerEvent]; 'resize-reset': [] }>()

const route = useRoute()
const profile = useProfileStore()

// 侧栏底部的「我」显示真实头像与昵称(资料只在首次进入时拉一次)
onMounted(() => {
  if (!profile.profile) profile.load().catch(() => {})
})

const myName = computed(() => profile.profile?.nickname || '我的资料')
const myAvatar = computed(() => profile.profile?.photos[0]?.url ?? null)

type NavName = 'discovery' | 'chats' | 'square' | 'mine'

const navItems: { name: NavName; label: string; icon: string; badge?: boolean }[] = [
  { name: 'discovery', label: '发现', icon: '❤️' },
  { name: 'chats', label: '消息', icon: '💬', badge: true },
  { name: 'square', label: '广场', icon: '🌟' },
  { name: 'mine', label: '我的', icon: '🙂' },
]

/** 当前子路由名(用于选中态);二级页高亮其所属一级页。 */
const currentSection = computed(() => {
  const name = String(route.name ?? '')
  if (name === 'chat') return 'chats'
  if (name === 'post-detail' || name === 'post-compose' || name === 'my-posts') return 'square'
  if (name === 'user-profile' || name === 'profile-edit' || name === 'preference') return 'mine'
  if (name === 'settings' || name === 'settings-blocks') return 'settings'
  return name
})
</script>

<template>
  <aside
    class="app-sidebar"
    :class="{ 'app-sidebar--icon-only': props.iconOnly }"
    :style="{ width: `${props.width}px` }"
  >
    <div class="app-sidebar__brand">♥<span v-if="!props.iconOnly"> 心跳</span></div>

    <nav class="app-sidebar__nav">
      <RouterLink
        v-for="item in navItems"
        :key="item.name"
        class="app-sidebar__item"
        :class="{ 'app-sidebar__item--active': currentSection === item.name }"
        :to="{ name: item.name }"
        :title="props.iconOnly ? item.label : undefined"
      >
        <span class="app-sidebar__icon">{{ item.icon }}</span>
        <span v-if="!props.iconOnly" class="app-sidebar__label">{{ item.label }}</span>
        <AppBadge v-if="item.badge && !props.iconOnly" :count="props.unreadTotal ?? 0" />
      </RouterLink>
    </nav>

    <div class="app-sidebar__foot">
      <RouterLink
        class="app-sidebar__item"
        :class="{ 'app-sidebar__item--active': currentSection === 'settings' }"
        :to="{ name: 'settings' }"
        :title="props.iconOnly ? '设置' : undefined"
      >
        <span class="app-sidebar__icon">⚙️</span>
        <span v-if="!props.iconOnly" class="app-sidebar__label">设置</span>
      </RouterLink>
      <RouterLink class="app-sidebar__me" :to="{ name: 'mine' }" :title="myName">
        <AppAvatar :src="myAvatar" :name="myName" :size="28" />
        <span v-if="!props.iconOnly" class="app-sidebar__label">{{ myName }}</span>
      </RouterLink>
    </div>

    <!-- 拖拽手柄:悬停变左右拖拽指针;双击复位默认宽度 -->
    <div
      class="app-sidebar__handle"
      role="separator"
      aria-orientation="vertical"
      @pointerdown="emit('resize-start', $event)"
      @dblclick="emit('resize-reset')"
    />
  </aside>
</template>

<style scoped>
.app-sidebar {
  position: relative;
  display: flex;
  flex-direction: column;
  flex: none;
  height: 100vh;
  padding: var(--space-lg) var(--space-md);
  background: var(--color-bg-card);
  border-right: 1px solid var(--color-divider);
}
.app-sidebar__brand {
  padding: 0 var(--space-sm) var(--space-lg);
  font-size: var(--text-subtitle);
  font-weight: var(--weight-bold);
  color: var(--color-brand);
}
.app-sidebar__nav {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: var(--space-xs);
}
.app-sidebar__item {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  height: 44px;
  padding: 0 var(--space-sm);
  border-radius: var(--radius-chip);
  color: var(--color-text1);
  transition: background var(--motion-fast) var(--ease-out);
}
.app-sidebar__item:hover {
  background: var(--hover-overlay);
}
/* 选中态:本屏唯一高音(spec §6.2) */
.app-sidebar__item--active {
  background: rgb(255 44 85 / 8%);
  color: var(--color-brand);
  font-weight: var(--weight-semibold);
}
.app-sidebar__icon {
  font-size: var(--text-body);
}
.app-sidebar__label {
  flex: 1;
  font-size: var(--text-body);
}
.app-sidebar__foot {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
}
.app-sidebar__me {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  height: 44px;
  padding: 0 var(--space-sm);
  border-radius: var(--radius-chip);
}
.app-sidebar__me:hover {
  background: var(--hover-overlay);
}
.app-sidebar--icon-only .app-sidebar__item,
.app-sidebar--icon-only .app-sidebar__me {
  justify-content: center;
  padding: 0;
}

.app-sidebar__handle {
  position: absolute;
  top: 0;
  right: -3px;
  width: 6px;
  height: 100%;
  cursor: col-resize;
}
.app-sidebar__handle:hover {
  background: var(--hover-overlay-strong);
}
</style>
