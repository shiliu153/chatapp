<script setup lang="ts">
import { useRouter } from 'vue-router'
import AppButton from '@/components/AppButton.vue'
import AppCard from '@/components/AppCard.vue'
import { useChatStore } from '@/stores/chat'
import { useSessionStore } from '@/stores/session'

const router = useRouter()
const session = useSessionStore()
const chat = useChatStore()

const entries = [
  { name: 'profile-edit', label: '编辑资料' },
  { name: 'preference', label: '想找的人' },
  { name: 'settings-blocks', label: '黑名单' },
  { name: 'my-posts', label: '我的动态' },
  { name: 'legal-agreement', label: '用户协议' },
  { name: 'legal-privacy', label: '隐私政策' },
] as const

async function onLogout() {
  if (!window.confirm('确定退出登录?')) return
  // 顺序不能反:先登出 IM,再清本地会话(否则 IM 还挂着旧账号的长连接)
  await chat.close().catch(() => {})
  session.logout()
  await router.push({ name: 'login' })
}
</script>

<template>
  <section class="settings">
    <h1 class="settings__title">设置</h1>

    <AppCard padding="lg">
      <ul class="settings__list">
        <li v-for="entry in entries" :key="entry.name">
          <RouterLink class="settings__item" :to="{ name: entry.name }">
            {{ entry.label }}
          </RouterLink>
        </li>
      </ul>
    </AppCard>

    <AppButton
      class="settings__logout"
      variant="danger"
      block
      size="lg"
      @click="onLogout"
    >
      退出登录
    </AppButton>
  </section>
</template>

<style scoped>
.settings {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  width: clamp(480px, 48%, 640px);
  max-width: 100%;
  margin: 0 auto;
  padding: var(--space-section-gap) var(--space-page-h);
}
.settings__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.settings__list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}
.settings__item {
  display: flex;
  align-items: center;
  height: 48px;
  border-bottom: 1px solid var(--color-divider);
  transition: color var(--motion-fast) var(--ease-out);
}
.settings__list li:last-child .settings__item {
  border-bottom: none;
}
.settings__item:hover {
  color: var(--color-brand);
}
</style>
