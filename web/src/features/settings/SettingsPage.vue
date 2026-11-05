<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import AppButton from '@/components/AppButton.vue'
import AppCard from '@/components/AppCard.vue'
import { parseApiError } from '@/api/error'
import { useChatStore } from '@/stores/chat'
import { useProfileStore } from '@/stores/profile'
import { useSessionStore } from '@/stores/session'
import { useThemeStore, type ThemeMode } from '@/stores/theme'
import DeleteAccountDialog from './DeleteAccountDialog.vue'

const router = useRouter()
const session = useSessionStore()
const chat = useChatStore()
const profile = useProfileStore()
const theme = useThemeStore()

/** 外观三选一(与 App 侧「跟随系统 / 浅色 / 深色」同一组文案)。 */
const themeOptions: { value: ThemeMode; label: string }[] = [
  { value: 'system', label: '跟随系统' },
  { value: 'light', label: '浅色' },
  { value: 'dark', label: '深色' },
]

const deleteOpen = ref(false)
const deleteError = ref('')
const toggleError = ref('')
const togglingVisits = ref(false)
const visitsHidden = computed(() => profile.profile?.visits_hidden ?? false)

onMounted(() => {
  if (!profile.profile) profile.load()
})

/** 隐身浏览:乐观更新由 store 的 PATCH 响应兜底,失败提示并回滚(store 未写入) */
async function toggleVisitsHidden() {
  if (togglingVisits.value) return
  togglingVisits.value = true
  toggleError.value = ''
  try {
    await profile.save({ visits_hidden: !visitsHidden.value })
  } catch (e) {
    toggleError.value = parseApiError(e).message
  } finally {
    togglingVisits.value = false
  }
}

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
      { name: 'settings-feedback', label: '意见反馈' },
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
  await session.logout()
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
  await session.logout()
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
      <div v-if="group.title === '账号与隐私'" class="settings__toggle">
        <span class="settings__toggle-label">隐身浏览</span>
        <button
          class="settings__switch"
          type="button"
          role="switch"
          aria-label="隐身浏览"
          :aria-checked="visitsHidden"
          :disabled="togglingVisits"
          @click="toggleVisitsHidden"
        >
          <span class="settings__switch-knob" />
        </button>
      </div>
      <p v-if="group.title === '账号与隐私' && toggleError" class="settings__error">
        {{ toggleError }}
      </p>
    </AppCard>

    <!-- 外观(F-3):三态分段控件,与 App 设置页的「外观」行同口径 -->
    <AppCard padding="lg">
      <h2 class="settings__group">外观</h2>
      <div class="settings__segmented" role="group" aria-label="外观">
        <button
          v-for="option in themeOptions"
          :key="option.value"
          class="settings__segment"
          type="button"
          :aria-pressed="theme.mode === option.value"
          @click="theme.setMode(option.value)"
        >
          {{ option.label }}
        </button>
      </div>
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
.settings__toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  height: 48px;
  border-top: 1px solid var(--color-divider);
}
.settings__toggle-label {
  color: var(--color-text1);
}
.settings__switch {
  position: relative;
  width: 44px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-divider);
  cursor: pointer;
  transition: background var(--motion-fast) var(--ease-out);
}
.settings__switch[aria-checked='true'] {
  background: var(--color-brand);
}
.settings__switch:disabled {
  cursor: default;
  opacity: 0.6;
}
.settings__switch-knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 20px;
  height: 20px;
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  transition: transform var(--motion-fast) var(--ease-out);
}
.settings__switch[aria-checked='true'] .settings__switch-knob {
  transform: translateX(18px);
}
.settings__error {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-danger);
  text-align: center;
}
.settings__segmented {
  display: flex;
  gap: var(--space-xs);
  padding: var(--space-xs);
  border-radius: var(--radius-chip);
  background: var(--hover-overlay);
}
.settings__segment {
  flex: 1;
  height: 36px;
  border: none;
  border-radius: var(--radius-chip);
  background: transparent;
  color: var(--color-text2);
  font-family: inherit;
  font-size: var(--text-body);
  cursor: pointer;
  transition:
    background var(--motion-fast) var(--ease-out),
    color var(--motion-fast) var(--ease-out);
}
.settings__segment:hover {
  background: var(--hover-overlay-strong);
}
.settings__segment[aria-pressed='true'] {
  background: var(--color-bg-card);
  color: var(--color-brand);
  font-weight: var(--weight-semibold);
}
</style>
