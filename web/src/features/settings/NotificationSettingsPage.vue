<script setup lang="ts">
import { RouterLink } from 'vue-router'

const rows = [
  { title: '新配对提醒', desc: '有人和你互相喜欢时提醒你' },
  { title: '新消息提醒', desc: '收到新消息时提醒你' },
]
</script>

<template>
  <section class="notify">
    <header class="notify__header">
      <RouterLink class="notify__back" :to="{ name: 'settings' }">← 返回</RouterLink>
      <h1 class="notify__title">通知设置</h1>
    </header>

    <ul class="notify__list">
      <li v-for="row in rows" :key="row.title" class="notify__row">
        <span class="notify__meta">
          <span class="notify__name">{{ row.title }}</span>
          <span class="notify__desc">{{ row.desc }}</span>
        </span>
        <span class="notify__soon">即将上线</span>
        <button
          type="button"
          class="notify__switch"
          role="switch"
          aria-checked="false"
          disabled
        >
          <span class="notify__knob" />
        </button>
      </li>
    </ul>

    <p class="notify__hint">
      推送功能将在后续版本上线,届时可以分别控制这两类提醒。当前开关仅为占位,不会保存任何设置。
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
.notify__soon {
  color: var(--color-text3);
  font-size: var(--text-micro);
}
.notify__switch {
  position: relative;
  width: 44px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: var(--radius-full);
  background: var(--color-divider);
  cursor: not-allowed;
}
.notify__knob {
  position: absolute;
  top: 3px;
  left: 3px;
  width: 20px;
  height: 20px;
  border-radius: var(--radius-full);
  background: var(--color-bg-card);
}
.notify__hint {
  margin: 0;
  color: var(--color-text3);
  font-size: var(--text-caption);
  line-height: 1.6;
}
</style>
