<script setup lang="ts">
import { onMounted, ref } from 'vue'
import AppButton from '@/components/AppButton.vue'
import AppCard from '@/components/AppCard.vue'
import AppEmpty from '@/components/AppEmpty.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import AppToast from '@/components/AppToast.vue'
import { parseApiError } from '@/api/error'
import { useToast } from '@/composables/useToast'
import { useDevicesStore, type DeviceRow } from '@/stores/devices'

const store = useDevicesStore()
const toast = useToast()
const error = ref('')
const busyType = ref<string | null>(null)

onMounted(async () => {
  error.value = ''
  try {
    await store.load()
  } catch (e) {
    error.value = parseApiError(e).message
  }
})

/**
 * 下线另一端的设备。
 * 该端令牌会立即失效、需要重新登录,属于不可恢复操作,所以走二次确认 ——
 * 与设置页「退出登录 / 注销账号」、我的动态删除同一套既有做法(`window.confirm`)。
 *
 * 当前端那一行没有按钮(见 store 的 `canLogout`);万一确认到当前端,
 * store 会走既有「清凭证回登录页」通道,这里不重复处理。
 */
async function onLogout(row: DeviceRow) {
  if (!window.confirm(`下线后${row.label}上的登录会立即失效,需要重新登录。确定下线?`)) return
  error.value = ''
  busyType.value = row.clientType
  try {
    await store.logout(row.clientType)
    toast.show(`已下线${row.label}`)
  } catch (e) {
    error.value = parseApiError(e).message
  } finally {
    busyType.value = null
  }
}
</script>

<template>
  <section class="devices">
    <h1 class="devices__title">登录设备</h1>
    <p class="devices__desc">这里能看到你在哪些端登录过,并单独把某一端下线</p>
    <p v-if="error" class="devices__error">{{ error }}</p>

    <div v-if="store.loading && store.devices.length === 0" class="devices__skeleton">
      <AppSkeleton height="72px" radius="var(--radius-card)" />
      <AppSkeleton height="72px" radius="var(--radius-card)" />
    </div>

    <AppEmpty
      v-else-if="store.devices.length === 0"
      emoji="📱"
      title="没有登录记录"
      description="登录过的端会出现在这里"
    />

    <AppCard v-else padding="lg">
      <ul class="devices__list">
        <li v-for="row in store.devices" :key="row.clientType" class="devices__item">
          <div class="devices__info">
            <p class="devices__label">
              {{ row.label }}
              <span v-if="row.current" class="devices__current">本机</span>
            </p>
            <p class="devices__meta">{{ row.firstLoginText }}</p>
            <p class="devices__meta">{{ row.lastActiveText }}</p>
          </div>
          <AppButton
            v-if="row.canLogout"
            class="devices__logout"
            variant="ghost"
            :loading="busyType === row.clientType"
            @click="onLogout(row)"
          >
            下线
          </AppButton>
        </li>
      </ul>
    </AppCard>

    <AppToast :text="toast.text.value" />
  </section>
</template>

<style scoped>
.devices {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  width: clamp(480px, 48%, 640px);
  max-width: 100%;
  margin: 0 auto;
  padding: var(--space-section-gap) var(--space-page-h);
}
.devices__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.devices__desc {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.devices__error {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-danger);
}
.devices__skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.devices__list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
}
.devices__item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-md);
  padding: var(--space-md) 0;
  border-bottom: 1px solid var(--color-divider);
}
.devices__list li:last-child {
  border-bottom: none;
}
.devices__info {
  display: flex;
  flex-direction: column;
  gap: var(--space-xs);
  min-width: 0;
}
.devices__label {
  display: flex;
  align-items: center;
  gap: var(--space-sm);
  margin: 0;
  font-size: var(--text-body);
  font-weight: var(--weight-semibold);
  color: var(--color-text1);
}
.devices__current {
  padding: 0 var(--space-sm);
  border-radius: var(--radius-chip);
  background: var(--tint-brand);
  color: var(--color-brand);
  font-size: var(--text-badge);
  font-weight: var(--weight-medium);
  line-height: var(--leading-tight);
}
.devices__meta {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.devices__logout {
  flex: none;
}
</style>
