<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import AppButton from '@/components/AppButton.vue'
import AppCard from '@/components/AppCard.vue'
import { parseApiError } from '@/api/error'
import { useChatStore } from '@/stores/chat'
import { useSessionStore } from '@/stores/session'
import DeleteAccountDialog from './DeleteAccountDialog.vue'

const router = useRouter()
const session = useSessionStore()
const chat = useChatStore()

const deleteOpen = ref(false)
const deleteError = ref('')

const groups = [
  {
    title: '账号与隐私',
    entries: [
      { name: 'profile-edit', label: '编辑资料' },
      { name: 'preference', label: '想找的人' },
      { name: 'my-posts', label: '我的动态' },
      { name: 'settings-blocks', label: '黑名单' },
      { name: 'settings-notifications', label: '通知设置' },
    ],
  },
  {
    title: '帮助与关于',
    entries: [
      { name: 'settings-about', label: '关于' },
      { name: 'legal-agreement', label: '用户协议' },
      { name: 'legal-privacy', label: '隐私政策' },
    ],
  },
] as const

async function onLogout() {
  if (!window.confirm('确定退出登录?')) return
  // 顺序不能反:先登出 IM,再清本地会话(否则 IM 还挂着旧账号的长连接)
  await chat.close().catch(() => {})
  session.logout()
  await router.push({ name: 'login' })
}

function onDeleteAccount() {
  if (
    !window.confirm(
      '注销后,你的资料、照片、配对关系、聊天关系与广场动态将被永久删除,且无法恢复。确定继续?',
    )
  ) {
    return
  }
  deleteError.value = ''
  deleteOpen.value = true
}

async function onDeleteSubmitted(phone: string) {
  try {
    await session.deleteAccount(phone)
  } catch (e) {
    deleteError.value = parseApiError(e).message
    return
  }
  deleteOpen.value = false
  // 顺序与 onLogout 一致:先登出 IM,再清本地会话
  await chat.close().catch(() => {})
  session.logout()
  await router.push({ name: 'login' })
}
</script>

<template>
  <section class="settings">
    <h1 class="settings__title">设置</h1>

    <AppCard v-for="group in groups" :key="group.title" padding="lg">
      <h2 class="settings__group">{{ group.title }}</h2>
      <ul class="settings__list">
        <li v-for="entry in group.entries" :key="entry.name">
          <RouterLink class="settings__item" :to="{ name: entry.name }">
            {{ entry.label }}
          </RouterLink>
        </li>
      </ul>
    </AppCard>

    <AppButton
      class="settings__delete"
      variant="danger"
      block
      size="lg"
      @click="onDeleteAccount"
    >
      注销账号
    </AppButton>

    <AppButton
      class="settings__logout"
      variant="ghost"
      block
      size="lg"
      @click="onLogout"
    >
      退出登录
    </AppButton>
    <p v-if="deleteError" class="settings__error">{{ deleteError }}</p>

    <DeleteAccountDialog
      :open="deleteOpen"
      @close="deleteOpen = false"
      @submitted="onDeleteSubmitted"
    />
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
.settings__group {
  margin: 0 0 var(--space-xs);
  color: var(--color-text3);
  font-size: var(--text-caption);
  font-weight: var(--weight-medium);
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
.settings__error {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-danger);
  text-align: center;
}
</style>
