<script setup lang="ts">
import { onMounted } from 'vue'
import { RouterLink } from 'vue-router'
import { storeToRefs } from 'pinia'
import { usePushStore } from '@/stores/push'
import type { PushPreferences } from '@/api/push'

const store = usePushStore()
const { prefs, loading, error } = storeToRefs(store)

const rows: { key: keyof PushPreferences; title: string; desc: string }[] = [
  { key: 'likes', title: '新的喜欢', desc: '有人喜欢你时提醒你' },
  { key: 'matches', title: '配对成功', desc: '互相喜欢时提醒你' },
  { key: 'system', title: '系统通知', desc: '举报处理、账号限制等通知' },
]

onMounted(() => {
  void store.load()
})
</script>

<template>
  <section class="notify">
    <header class="notify__header">
      <RouterLink class="notify__back" :to="{ name: 'settings' }">← 返回</RouterLink>
      <h1 class="notify__title">通知设置</h1>
      <p class="notify__hint">网页端不接收推送,这里的设置只影响 App。</p>
    </header>

    <p v-if="loading" class="notify__hint">加载中…</p>
    <p v-else-if="error" class="notify__error">{{ error }}</p>

    <ul v-if="prefs" class="notify__list">
      <li v-for="row in rows" :key="row.key" class="notify__row">
        <span class="notify__meta">
          <span class="notify__name">{{ row.title }}</span>
          <span class="notify__desc">{{ row.desc }}</span>
        </span>
        <button
          type="button"
          class="notify__switch"
          :class="{ 'notify__switch--on': prefs[row.key] }"
          role="switch"
          :aria-checked="prefs[row.key]"
          @click="store.toggle(row.key, !prefs[row.key])"
        >
          <span class="notify__knob" />
        </button>
      </li>
    </ul>

    <p class="notify__hint">
      新消息提醒需要接入离线推送,将在后续版本开放。
    </p>
  </section>
</template>

<style scoped>
.notify {
  display: flex;
  flex-direction: column;
  gap: var(--space-lg);
  max-width: var(--form-card-max);
  margin: 0 auto;
  padding: var(--space-xl) var(--space-section-gap);
}
.notify__header {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.notify__back {
  align-self: flex-start;
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-decoration: none;
}
.notify__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.notify__list {
  display: flex;
  flex-direction: column;
  margin: 0;
  padding: 0;
  list-style: none;
  border-radius: var(--radius-card);
  background: var(--color-bg-card);
  box-shadow: var(--shadow-card);
}
.notify__row {
  display: flex;
  align-items: center;
  gap: var(--space-md);
  padding: var(--space-md) var(--space-lg);
  border-bottom: 1px solid var(--color-divider);
}
.notify__row:last-child {
  border-bottom: none;
}
.notify__meta {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 2px;
}
.notify__name {
  color: var(--color-text1);
  font-size: var(--text-body);
}
.notify__desc {
  color: var(--color-text2);
  font-size: var(--text-caption);
}
.notify__switch {
  position: relative;
  width: 44px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-divider);
  cursor: pointer;
  transition: background var(--motion-fast);
}
.notify__switch--on {
  background: var(--color-brand);
}
.notify__knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 20px;
  height: 20px;
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
  transition: left var(--motion-fast);
}
.notify__switch--on .notify__knob {
  left: 21px;
}
.notify__hint {
  margin: 0;
  color: var(--color-text3);
  font-size: var(--text-caption);
  line-height: 1.6;
}
.notify__error {
  margin: 0;
  color: var(--color-danger);
  font-size: var(--text-caption);
}
</style>

