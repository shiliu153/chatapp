<script setup lang="ts">
import { onMounted } from 'vue'
import AppCard from '@/components/AppCard.vue'
import AppErrorView from '@/components/AppErrorView.vue'
import AppSegmented from '@/components/AppSegmented.vue'
import AppSkeleton from '@/components/AppSkeleton.vue'
import { STATS_PERIODS, useStatsStore } from '@/stores/stats'
import type { StatsPeriod } from '@/api/types'

const store = useStatsStore()

onMounted(() => {
  reload()
})

function reload(): void {
  // store.error 已承载失败文案,这里不再重复处理
  store.load().catch(() => {})
}

function onPeriod(next: StatsPeriod): void {
  // 切换即重新请求;失败同样由 store.error 展示
  store.setPeriod(next).catch(() => {})
}
</script>

<template>
  <section class="stats">
    <header class="stats__header">
      <RouterLink class="stats__back" :to="{ name: 'settings' }">← 返回</RouterLink>
      <h1 class="stats__title">我的数据</h1>
      <p class="stats__desc">按自然周 / 月 / 年统计你自己的使用情况</p>
    </header>

    <AppSegmented
      :options="STATS_PERIODS"
      :model-value="store.period"
      label="统计周期"
      @update:model-value="onPeriod"
    />

    <!-- 周期标签:让用户知道这些数字的统计范围(含首含尾) -->
    <p v-if="store.rangeText" class="stats__range">{{ store.rangeText }}</p>

    <div v-if="store.loading && !store.report" class="stats__grid">
      <AppSkeleton
        v-for="i in 7"
        :key="i"
        height="88px"
        radius="var(--radius-card)"
      />
    </div>

    <AppErrorView
      v-else-if="store.error && !store.report"
      :message="store.error"
      @retry="reload"
    />

    <template v-else-if="store.report">
      <!-- 周期切换失败但还留着上一份报告的情况:数字不动,只提示错误 -->
      <p v-if="store.error" class="stats__error">{{ store.error }}</p>
      <div class="stats__grid">
        <AppCard v-for="card in store.cards" :key="card.key" padding="lg">
          <div class="stats__card">
            <p class="stats__value">{{ card.value }}</p>
            <p class="stats__label">{{ card.label }}</p>
          </div>
        </AppCard>
      </div>
    </template>
  </section>
</template>

<style scoped>
.stats {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
  width: clamp(480px, 48%, 640px);
  max-width: 100%;
  margin: 0 auto;
  padding: var(--space-section-gap) var(--space-page-h);
}
.stats__header {
  display: flex;
  flex-direction: column;
  gap: var(--space-sm);
}
.stats__back {
  align-self: flex-start;
  color: var(--color-text2);
  font-size: var(--text-caption);
  text-decoration: none;
}
.stats__title {
  margin: 0;
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
}
.stats__desc {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
.stats__range {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
  font-variant-numeric: tabular-nums;
}
.stats__error {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-danger);
}
.stats__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: var(--space-md);
}
.stats__card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--space-xs);
}
.stats__value {
  margin: 0;
  font-family: var(--font-latin);
  font-size: var(--text-display);
  font-weight: var(--weight-extrabold);
  line-height: var(--leading-tight);
  font-variant-numeric: tabular-nums;
}
.stats__label {
  margin: 0;
  font-size: var(--text-caption);
  color: var(--color-text2);
}
</style>
